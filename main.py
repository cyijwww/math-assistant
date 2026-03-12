import re
import os
import requests
import gradio as gr
from openai import OpenAI
from duckduckgo_search import DDGS

# Authing 配置
AUTHING_DOMAIN = "https://pig-math.authing.cn"
AUTHING_APP_ID = os.environ.get("AUTHING_APP_ID", "69b2c0fe301a31829372d43f")
AUTHING_APP_SECRET = os.environ.get("AUTHING_APP_SECRET", "f336dab59369aef6b8a318078bb3144c")

def check_login(email, password):
    """通过 Authing API 验证邮箱和密码"""
    try:
        resp = requests.post(
            f"{AUTHING_DOMAIN}/api/v2/login/account",
            json={
                "account": email,
                "password": password,
                "appId": AUTHING_APP_ID,
            },
            timeout=10
        )
        data = resp.json()
        return data.get("code") == 200
    except Exception:
        return False

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-3b1488b14e6349a2b3d366c23814a053"),
    base_url="https://api.deepseek.com/v1"
)

def web_search(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results:
            return ""
        search_text = "\n\n".join([
            f"来源：{r['title']}\n内容：{r['body']}"
            for r in results
        ])
        return f"\n\n【网络搜索结果】\n{search_text}\n【搜索结束】\n"
    except Exception as e:
        return ""

def fix_latex(text):
    text = text.replace("\\(", "").replace("\\)", "")
    text = text.replace("\\[", "").replace("\\]", "")
    text = text.replace("$$", "").replace("$", "")
    return text

def ask(message, history, deep_think, use_search, username):
    model = "deepseek-reasoner" if deep_think else "deepseek-chat"

    search_context = ""
    if use_search:
        search_context = web_search(message)

    history_len = len(history)
    if history_len == 0:
        level_hint = "这是该同学第一次提问，请友好介绍自己。"
    elif history_len < 5:
        level_hint = "该同学刚开始学习，请耐心详细解释。"
    else:
        level_hint = "该同学已有一定基础，可以适当加深难度。"

    name_str = f"同学的名字是【{username}】，请在回答时称呼他/她的名字。" if username.strip() else ""

    system_prompt = f"""你叫pig，是一位专业的大学数学辅导老师。
{name_str}
{level_hint}
回答要求：
1. 解题步骤清晰，分步骤说明
2. 先给出思路，再一步一步计算
3. 最后给出总结答案
4. 态度亲切，像老师辅导学生
5. 根据同学的提问水平调整回答难度"""

    if search_context:
        system_prompt += f"\n\n你可以参考以下网络搜索结果来补充回答：{search_context}"

    messages = [{"role": "system", "content": system_prompt}]
    for item in history:
        if isinstance(item, tuple):
            messages.append({"role": "user", "content": item[0]})
            if item[1]:
                messages.append({"role": "assistant", "content": item[1]})
        elif isinstance(item, dict):
            messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": message})
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=4000,
        temperature=0.3
    )
    result = response.choices[0].message.content
    return fix_latex(result)

def respond(message, chat_history, deep, search, username):
    if not message.strip():
        return "", chat_history
    try:
        answer = ask(message, chat_history, deep, search, username)
    except Exception as e:
        answer = f"⚠️ 请求失败：{str(e)}"
    chat_history.append((message, answer))
    return "", chat_history

CLAUDE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body, .gradio-container {
    background: #f7f7f5 !important;
    font-family: Georgia, serif !important;
    max-width: 100% !important;
}

footer, .built-with { display: none !important; }

#chatbot {
    background: transparent !important;
    border: none !important;
    width: 100% !important;
    padding: 12px 12px 180px 12px !important;
    min-height: 100vh !important;
}

.input-area {
    position: fixed !important;
    bottom: 0 !important;
    left: 0 !important;
    right: 0 !important;
    background: #f7f7f5 !important;
    border-top: 1px solid #e5e5e0 !important;
    padding: 10px 12px 40px !important;
    z-index: 9999 !important;
}

.input-inner {
    background: #ffffff;
    border: 1.5px solid #ddddd8;
    border-radius: 18px;
    padding: 10px 12px 8px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.07);
}

#deep-check {
    font-size: 12px !important;
    color: #888880 !important;
    margin-bottom: 6px !important;
}

#deep-check label { color: #888880 !important; font-size: 12px !important; }

#msg-input textarea {
    background: transparent !important;
    border: none !important;
    outline: none !important;
    font-size: 15px !important;
    color: #1a1a1a !important;
    resize: none !important;
    font-family: inherit !important;
    line-height: 1.5 !important;
    padding: 0 !important;
    width: 100% !important;
}

#msg-input textarea::placeholder { color: #b0b0a8 !important; }
#msg-input .wrap { border: none !important; box-shadow: none !important; background: transparent !important; padding: 0 !important; }
#msg-input { border: none !important; flex: 1 !important; }

#send-btn {
    background: #cc6a45 !important;
    border: none !important;
    border-radius: 10px !important;
    width: 36px !important;
    height: 36px !important;
    min-width: 36px !important;
    padding: 0 !important;
    cursor: pointer !important;
    color: white !important;
    font-size: 20px !important;
    line-height: 1 !important;
}

.welcome-wrap {
    text-align: center;
    padding: 30px 16px 20px;
    max-width: 580px;
    margin: 0 auto;
}
"""

with gr.Blocks(
    theme=gr.themes.Base(),
    title="pig",
    css=CLAUDE_CSS
) as demo:

    gr.HTML("""
    <div style="text-align:center;padding:10px;border-bottom:1px solid #e5e5e0;background:#f7f7f5;">
        <span style="font-size:15px;font-weight:600;color:#1a1a1a;">📐 pig</span>
    </div>
    """)

    gr.HTML("""
    <div class="welcome-wrap">
        <div style="width:56px;height:56px;background:#cc6a45;border-radius:16px;
                    display:flex;align-items:center;justify-content:center;
                    font-size:26px;margin:0 auto 20px;">📐</div>
        <h1 style="font-size:26px;font-weight:600;color:#1a1a1a;margin:0 0 10px;letter-spacing:-0.5px;">
            你好，我是pig
        </h1>
        <p style="font-size:15px;color:#777770;margin:0;line-height:1.7;">
            你的专属大学数学辅导老师<br>
            微积分 · 线性代数 · 概率论 · 离散数学
        </p >
        <div style="display:flex;gap:8px;justify-content:center;margin-top:22px;flex-wrap:wrap;">
            <span style="background:#f0ece6;border:1px solid #e5e0d8;padding:7px 14px;
                         border-radius:20px;font-size:13px;color:#555550;cursor:pointer;">
                什么是导数？
            </span>
            <span style="background:#f0ece6;border:1px solid #e5e0d8;padding:7px 14px;
                         border-radius:20px;font-size:13px;color:#555550;cursor:pointer;">
                帮我解一道积分题
            </span>
            <span style="background:#f0ece6;border:1px solid #e5e0d8;padding:7px 14px;
                         border-radius:20px;font-size:13px;color:#555550;cursor:pointer;">
                解释矩阵的特征值
            </span>
        </div>
    </div>
    """)

    chatbot = gr.Chatbot(
        elem_id="chatbot",
        show_label=False,
        height=520
    )

    with gr.Column(elem_classes="input-area"):
        username = gr.Textbox(
            placeholder="请输入你的名字（可选）",
            show_label=False,
            lines=1,
            max_lines=1,
            elem_id="msg-input"
        )
        deep_think = gr.Checkbox(
            label="🧠 深度思考（使用 DeepSeek-R1，更慢更精准）",
            value=False,
            elem_id="deep-check"
        )
        use_search = gr.Checkbox(
            label="🔍 智能搜索（联网搜索相关资料）",
            value=False,
            elem_id="deep-check"
        )
        with gr.Column(elem_classes="input-inner"):
            with gr.Row():
                msg = gr.Textbox(
                    placeholder="向pig提问任何数学问题...",
                    show_label=False,
                    scale=5,
                    lines=1,
                    max_lines=8,
                    elem_id="msg-input"
                )
                send = gr.Button("↑", variant="primary", scale=0, elem_id="send-btn")

    send.click(respond, [msg, chatbot, deep_think, use_search, username], [msg, chatbot])
    msg.submit(respond, [msg, chatbot, deep_think, use_search, username], [msg, chatbot])

port = int(os.environ.get("PORT", 7860))
demo.launch(
    server_name="0.0.0.0",
    server_port=port,
    auth=check_login,
    auth_message="请用在 pig 注册的邮箱和密码登录"
)
