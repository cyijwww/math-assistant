import re
import os
import hashlib
import gradio as gr
from openai import OpenAI
from duckduckgo_search import DDGS
import psycopg2
from psycopg2.extras import RealDictCursor

# ── 数据库 ──
DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_conn():
    import urllib.parse
    r = urllib.parse.urlparse(DATABASE_URL)
    return psycopg2.connect(
        host=r.hostname,
        port=r.port or 6543,
        database=r.path.lstrip("/"),
        user=r.username,
        password=r.password,
        sslmode="require"
    )

def init_db():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                email TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB init error: {e}")

def save_conversation(email, question, answer):
    try:
        conn = get_conn()
        conn.cursor().execute(
            "INSERT INTO conversations (email, question, answer) VALUES (%s, %s, %s)",
            (email, question, answer)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Save conversation error: {e}")

def load_history(email):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT question, answer FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 50",
            (email,)
        )
        rows = cur.fetchall()
        conn.close()
        return [(q, a) for q, a in reversed(rows)]
    except Exception as e:
        print(f"Load history error: {e}")
        return []

def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def do_register(email, password, confirm):
    if not email or not password:
        return "❌ 请填写邮箱和密码"
    if "@" not in email:
        return "❌ 请输入正确的邮箱格式"
    if password != confirm:
        return "❌ 两次密码不一致"
    if len(password) < 6:
        return "❌ 密码至少6位"
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s)",
                    (email.lower().strip(), hash_pw(password)))
        conn.commit()
        conn.close()
        return "✅ 注册成功！请切换到登录标签登录"
    except psycopg2.errors.UniqueViolation:
        return "❌ 该邮箱已注册，请直接登录"
    except Exception as e:
        return f"❌ 错误：{str(e)}"

def do_login(email, password):
    if not email or not password:
        return None, "❌ 请输入邮箱和密码"
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT email FROM users WHERE email=%s AND password_hash=%s",
                    (email.lower().strip(), hash_pw(password)))
        row = cur.fetchone()
        conn.close()
        if row:
            return email.split("@")[0], None
        else:
            return None, "❌ 邮箱或密码错误"
    except Exception as e:
        return None, f"❌ 错误：{str(e)}"

init_db()

# ── AI ──
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
        return "\n\n【网络搜索结果】\n" + "\n\n".join([
            f"来源：{r['title']}\n内容：{r['body']}" for r in results
        ]) + "\n【搜索结束】\n"
    except Exception:
        return ""

def fix_latex(text):
    for s in ["\\(", "\\)", "\\[", "\\]", "$$", "$"]:
        text = text.replace(s, "")
    return text

def ask(message, history, deep_think, use_search, username):
    model = "deepseek-reasoner" if deep_think else "deepseek-chat"
    search_context = web_search(message) if use_search else ""
    history_len = len(history)
    if history_len == 0:
        level_hint = "这是该同学第一次提问，请友好介绍自己。"
    elif history_len < 5:
        level_hint = "该同学刚开始学习，请耐心详细解释。"
    else:
        level_hint = "该同学已有一定基础，可以适当加深难度。"
    name_str = f"同学的名字是【{username}】，请在回答时称呼他/她的名字。" if username and username.strip() else ""
    system_prompt = f"""你叫pig，是一位专业的大学数学辅导老师。
{name_str}{level_hint}
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
    response = client.chat.completions.create(model=model, messages=messages, max_tokens=4000, temperature=0.3)
    return fix_latex(response.choices[0].message.content)

def respond(message, chat_history, deep, search, current_user):
    if not message.strip():
        return "", chat_history
    try:
        answer = ask(message, chat_history, deep, search, "")
        if current_user:
            save_conversation(current_user, message, answer)
    except Exception as e:
        answer = f"⚠️ 请求失败：{str(e)}"
    chat_history.append((message, answer))
    return "", chat_history

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body, .gradio-container { background: #f7f7f5 !important; font-family: Georgia, serif !important; max-width: 100% !important; }
footer, .built-with { display: none !important; }
#auth-box { max-width: 400px; margin: 60px auto; background: #fff; border-radius: 20px; padding: 36px 32px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }
#auth-submit { background: #cc6a45 !important; border-radius: 10px !important; color: white !important; font-size: 15px !important; width: 100% !important; }
#auth-msg { text-align: center; font-size: 14px; margin-top: 8px; }
#chatbot { background: transparent !important; border: none !important; width: 100% !important; padding: 12px 12px 180px 12px !important; min-height: 100vh !important; }
.input-area { position: fixed !important; bottom: 0 !important; left: 0 !important; right: 0 !important; background: #f7f7f5 !important; border-top: 1px solid #e5e5e0 !important; padding: 10px 12px 40px !important; z-index: 9999 !important; }
.input-inner { background: #ffffff; border: 1.5px solid #ddddd8; border-radius: 18px; padding: 10px 12px 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.07); }
#deep-check { font-size: 12px !important; color: #888880 !important; margin-bottom: 6px !important; }
#deep-check label { color: #888880 !important; font-size: 12px !important; }
#msg-input textarea { background: transparent !important; border: none !important; outline: none !important; font-size: 15px !important; color: #1a1a1a !important; resize: none !important; font-family: inherit !important; line-height: 1.5 !important; padding: 0 !important; width: 100% !important; }
#msg-input textarea::placeholder { color: #b0b0a8 !important; }
#msg-input .wrap { border: none !important; box-shadow: none !important; background: transparent !important; padding: 0 !important; }
#msg-input { border: none !important; flex: 1 !important; }
#send-btn { background: #cc6a45 !important; border: none !important; border-radius: 10px !important; width: 36px !important; height: 36px !important; min-width: 36px !important; padding: 0 !important; cursor: pointer !important; color: white !important; font-size: 20px !important; line-height: 1 !important; }
.welcome-wrap { text-align: center; padding: 30px 16px 20px; max-width: 580px; margin: 0 auto; }
"""

with gr.Blocks(theme=gr.themes.Base(), title="pig", css=CSS) as demo:

    logged_in_user = gr.State(None)

    with gr.Column(elem_id="auth-box", visible=True) as auth_page:
        gr.HTML("""
        <div style="text-align:center;margin-bottom:24px;">
            <div style="width:52px;height:52px;background:#cc6a45;border-radius:14px;
                        display:inline-flex;align-items:center;justify-content:center;font-size:24px;">📐</div>
            <h2 style="font-size:22px;font-weight:600;color:#1a1a1a;margin-top:12px;">pig</h2>
            <p style="color:#888;font-size:13px;margin-top:4px;">你的专属数学辅导老师</p >
        </div>
        """)
        with gr.Tabs() as tabs:
            with gr.Tab("登录"):
                login_email = gr.Textbox(placeholder="邮箱", show_label=False)
                login_pass = gr.Textbox(placeholder="密码", show_label=False, type="password")
                login_btn = gr.Button("登录", elem_id="auth-submit", variant="primary")
                login_msg = gr.HTML(elem_id="auth-msg")

            with gr.Tab("注册"):
                reg_email = gr.Textbox(placeholder="邮箱（QQ/163/Gmail均可）", show_label=False)
                reg_pass = gr.Textbox(placeholder="密码（至少6位）", show_label=False, type="password")
                reg_confirm = gr.Textbox(placeholder="确认密码", show_label=False, type="password")
                reg_btn = gr.Button("注册", elem_id="auth-submit", variant="primary")
                reg_msg = gr.HTML(elem_id="auth-msg")


    with gr.Column(visible=False) as chat_page:
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
            <h1 style="font-size:26px;font-weight:600;color:#1a1a1a;margin:0 0 10px;">你好，我是pig</h1>
            <p style="font-size:15px;color:#777770;margin:0;line-height:1.7;">
                你的专属大学数学辅导老师<br>微积分 · 线性代数 · 概率论 · 离散数学
            </p >
        </div>
        """)
        chatbot = gr.Chatbot(elem_id="chatbot", show_label=False, height=520)
        with gr.Column(elem_classes="input-area"):
            deep_think = gr.Checkbox(label="🧠 深度思考（使用 DeepSeek-R1，更慢更精准）", value=False, elem_id="deep-check")
            use_search = gr.Checkbox(label="🔍 智能搜索（联网搜索相关资料）", value=False, elem_id="deep-check")
            with gr.Column(elem_classes="input-inner"):
                with gr.Row():
                    msg = gr.Textbox(placeholder="向pig提问任何数学问题...", show_label=False, scale=5, lines=1, max_lines=8, elem_id="msg-input")
                    send = gr.Button("↑", variant="primary", scale=0, elem_id="send-btn")

    def handle_login(email, password):
        nickname, error = do_login(email, password)
        if nickname:
            history = load_history(email.lower().strip())
            return gr.update(visible=False), gr.update(visible=True), email.lower().strip(), "", history
        else:
            return gr.update(visible=True), gr.update(visible=False), None, f'<p style="color:red">{error}</p >', []

    def handle_register(email, password, confirm):
        result = do_register(email, password, confirm)
        color = "green" if "✅" in result else "red"
        msg_html = f'<p style="color:{color}">{result}</p >'
        if "✅" in result:
            return msg_html, gr.update(selected=0)
        else:
            return msg_html, gr.update()

    login_btn.click(handle_login, [login_email, login_pass], [auth_page, chat_page, logged_in_user, login_msg, chatbot])
    login_email.submit(handle_login, [login_email, login_pass], [auth_page, chat_page, logged_in_user, login_msg, chatbot])
    reg_btn.click(handle_register, [reg_email, reg_pass, reg_confirm], [reg_msg, tabs])
    send.click(respond, [msg, chatbot, deep_think, use_search, logged_in_user], [msg, chatbot])
    msg.submit(respond, [msg, chatbot, deep_think, use_search, logged_in_user], [msg, chatbot])

port = int(os.environ.get("PORT", 7860))
demo.launch(server_name="0.0.0.0", server_port=port)
