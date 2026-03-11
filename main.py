import re
import os
import gradio as gr
from openai import OpenAI
from duckduckgo_search import DDGS

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

def ask(message, history, deep_think, use_search):
    model = "deepseek-reasoner" if deep_think else "deepseek-chat"
    
    search_context = ""
    if use_search:
        search_context = web_search(message)
    
    system_prompt = """你叫小明，是一位专业的大学数学辅导老师。
回答要求：
1. 解题步骤清晰，分步骤说明
2. 先给出思路，再一步一步计算
3. 最后给出总结答案
4. 态度亲切，像老师辅导学生"""

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
        max_tokens=1000,
        temperature=0.3
    )
    result = response.choices[0].message.content
    return fix_latex(result)

def respond(message, chat_history, deep, search):
    if not message.strip():
        return "", chat_history
    try:
        answer = ask(message, chat_history, deep, search)
    except Exception as e:
        answer = f"⚠️ 请求失败：{str(e)}"
    chat_history.append((message, answer))
    return "", chat_history

CLAUDE_CSS = """
* { box-sizing: border-box; }

body, .gradio-container {
    background: #f7f7f5 !important;
    font-family: Georgia, serif !important;
    margin: 0 !important;
    padding: 0 !important;
    max-width: 100% !important;
}

footer, .built-with { display: none !important; }

.top-bar {
    position: fixed;
    top: 0; left: 0; right: 0;
    height: 52px;
    background: #f7f7f5;
    border-bottom: 1px solid #e5e5e0;
    display: flex;
    align-items: center;
    padding: 0 16px;
    z-index: 100;
}

#chatbot {
    background: transparent !important;
    border: none !important;
    max-width: 760px !important;
    margin: 0 auto !important;
    padding: 60px 8px 200px 8px !important;
    min-height: 100vh !important;
}

#chatbot .wrap { padding: 0 !important; gap: 4px !important; }

.input-area {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    background: linear-gradient(to top, #f7f7f5 80%, transparent);
    padding: 8px 12px 16px;
    z-index: 100;
}

.input-inner {
    max-width: 760px;
    margin: 0 auto;
    background: #ffffff;
    border: 1.5px solid #ddddd8;
    border-radius: 18px;
    padding: 10px 12px 8px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.07);
}

#deep-check {
    max-width: 760px !important;
    margin: 0 auto 6px !important;
    font-size: 12px !important;
    color: #888880 !important;
}

#deep-check label { color: #888880 !important; font-size: 12px !important; }

#msg-input textarea {
    background: transparent !important;
    border: none !important;
    outline: none !important;
    font-size: 14px !important;
    color: #1a1a1a !important;
    resize: none !important;
    font-family: inherit !important;
    line-height: 1.55 !important;
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
    width: 34px !important;
    height: 34px !important;
    min-width: 34px !important;
    padding: 0 !important;
    margin-top: 2px !important;
    cursor: pointer !important;
    color: white !important;
    font-size: 20px !important;
    line-height: 1 !important;
}

#send-btn:hover { background: #b55c39 !important; }

.welcome-wrap {
    text-align: center;
    padding: 80px 16px 30px;
    max-width: 580px;
    margin: 0 auto;
}

@media (max-width: 600px) {
    .welcome-wrap { padding: 70px 12px 20px; }
    .welcome-wrap h1 { font-size: 22px !important; }
    .welcome-wrap p { font-size: 13px !important; }
    .welcome-wrap span { font-size: 12px !important; padding: 5px 10px !important; }
    #chatbot { padding: 60px 4px 180px 4px !important; }
    .input-area { padding: 6px 8px 12px; }
}
"""

with gr.Blocks(
    theme=gr.themes.Base(),
    title="小明数学助手",
    css=CLAUDE_CSS
) as demo:

    gr.HTML("""
    <div class="top-bar">
        <span style="font-size:16px;font-weight:600;color:#1a1a1a;letter-spacing:-0.3px;">📐 小明数学助手</span>
        <span style="margin-left:10px;font-size:11px;color:#888;background:#eeeae4;
                     padding:2px 9px;border-radius:20px;font-family:monospace;">
            Qwen · DeepSeek-R1
        </span>
    </div>
    """)

    gr.HTML("""
    <div class="welcome-wrap">
        <div style="width:56px;height:56px;background:#cc6a45;border-radius:16px;
                    display:flex;align-items:center;justify-content:center;
                    font-size:26px;margin:0 auto 20px;">📐</div>
        <h1 style="font-size:26px;font-weight:600;color:#1a1a1a;margin:0 0 10px;letter-spacing:-0.5px;">
            你好，我是小明
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
                    placeholder="向小明提问任何数学问题...",
                    show_label=False,
                    scale=5,
                    lines=1,
                    max_lines=8,
                    elem_id="msg-input"
                )
                send = gr.Button("↑", variant="primary", scale=0, elem_id="send-btn")

    send.click(respond, [msg, chatbot, deep_think, use_search], [msg, chatbot])
    msg.submit(respond, [msg, chatbot, deep_think, use_search], [msg, chatbot])

port = int(os.environ.get("PORT", 7860))
demo.launch(server_name="0.0.0.0", server_port=port)
