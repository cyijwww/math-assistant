import os
import json
import hashlib
import secrets
import sys
import time
import gradio as gr
from openai import OpenAI
from duckduckgo_search import DDGS
import psycopg2
from datetime import datetime

# --- 1. 系统保护配置 ---
sys.setrecursionlimit(2000)

# --- 2. 数据库连接优化 ---
DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_conn():
    if not DATABASE_URL:
        raise ValueError("环境变量 DATABASE_URL 为空，请在 Railway 中配置！")
    import urllib.parse
    r = urllib.parse.urlparse(DATABASE_URL)
    # Railway 推荐使用 sslmode=require 或不设置，这里尝试更通用的方式
    return psycopg2.connect(
        host=r.hostname, 
        port=r.port or 5432,
        database=r.path.lstrip("/"),
        user=r.username, 
        password=r.password,
        sslmode="require" if "railway" in DATABASE_URL else "prefer",
        connect_timeout=10
    )

def db_exec(sql, params=(), fetch=None):
    conn = None
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(sql, params)
        result = None
        if fetch == "one": result = cur.fetchone()
        if fetch == "all": result = cur.fetchall()
        conn.commit()
        return result
    except Exception as e:
        if conn: conn.rollback()
        print(f"❌ 数据库执行错误: {e}")
        raise e
    finally:
        if conn: conn.close()

def init_db():
    print("🔄 正在初始化数据库...")
    # 给予数据库 3 次启动重试机会，防止 Railway 数据库响应延迟
    for i in range(3):
        try:
            db_exec("""CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )""")
            db_exec("""CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                email TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )""")
            print("✅ 数据库初始化成功！")
            return
        except Exception as e:
            print(f"⚠️ 第 {i+1} 次尝试初始化失败: {e}")
            time.sleep(2)
    print("🛑 数据库最终初始化失败，程序将带病运行...")

# 执行初始化
init_db()

# --- 3. 业务逻辑 (保持精简稳定) ---
def hash_pw(password, salt=None):
    if salt is None: salt = secrets.token_hex(16)
    return hashlib.sha256((salt + password).encode()).hexdigest(), salt

def do_login(email, password):
    email = email.lower().strip()
    try:
        row = db_exec("SELECT email, password_hash, salt FROM users WHERE email=%s", (email,), fetch="one")
        if not row: return None, None, "❌ 邮箱或密码错误"
        db_email, db_hash, salt = row
        h, _ = hash_pw(password, salt or "")
        if h == db_hash: return db_email, db_email.split("@")[0], None
    except Exception as e:
        return None, None, f"❌ 登录异常: {str(e)}"
    return None, None, "❌ 邮箱或密码错误"

def load_history_chat(email):
    if not email: return []
    try:
        rows = db_exec("SELECT question, answer FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 15", (email,), fetch="all") or []
        result = []
        for q, a in reversed(rows):
            result.append({"role": "user", "content": str(q)})
            result.append({"role": "assistant", "content": str(a)})
        return result
    except:
        return []

# --- 4. AI 核心 ---
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
client = OpenAI(api_key=DEEPSEEK_KEYsk-3b1488b14e6349a2b3d366c23814a053, base_url="https://api.deepseek.com/v1")

def ask(message, history, deep_think, use_search, nickname):
    if not DEEPSEEK_KEY: return "⚠️ 未配置 API Key，请检查环境变量。"
    
    model = "deepseek-reasoner" if deep_think else "deepseek-chat"
    
    # 搜索逻辑
    search_ctx = ""
    if use_search:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(message, max_results=3))
                if results:
                    search_ctx = "\n\n【搜索参考】\n" + "\n".join([f"- {r['body']}" for r in results])
        except: pass

    sys_prompt = f"你叫pig，数学辅导老师。同学叫【{nickname}】。请用 LaTeX 格式书写公式。"
    if search_ctx: sys_prompt += search_ctx
    
    msgs = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": message}]
    
    resp = client.chat.completions.create(model=model, messages=msgs, max_tokens=2000)
    return resp.choices[0].message.content

def respond(message, chat_history, deep, search, current_user, nickname):
    if not message: return "", chat_history
    try:
        answer = ask(message, chat_history, deep, search, nickname)
        if current_user:
            try: db_exec("INSERT INTO conversations (email, question, answer) VALUES (%s, %s, %s)", (current_user, message, answer))
            except: pass
    except Exception as e:
        answer = f"⚠️ 发生错误: {str(e)}"
    
    chat_history.append({"role": "user", "content": message})
    chat_history.append({"role": "assistant", "content": answer})
    return "", chat_history

# --- 5. UI 部分 (保持你的精美样式) ---
CSS = """
body { background: #f7f7f5 !important; }
#auth-box { max-width: 400px; margin: 50px auto; padding: 20px; background: white; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }
#send-btn { background: #cc6a45 !important; color: white !important; }
"""

with gr.Blocks(css=CSS, title="pig Math") as demo:
    logged_in_user = gr.State(None)
    logged_in_nick = gr.State(None)

    # 登录界面
    with gr.Column(elem_id="auth-box", visible=True) as auth_page:
        gr.Markdown("# 📐 pig 数学助教\n请先登录以保存你的学习进度")
        email_input = gr.Textbox(label="邮箱")
        pass_input  = gr.Textbox(label="密码", type="password")
        login_btn   = gr.Button("登录 / 进入", variant="primary", elem_id="send-btn")
        msg_out     = gr.HTML()

    # 聊天界面
    with gr.Column(visible=False) as chat_page:
        gr.Markdown("### 🍎 欢迎回来，pig 老师已准备好为你答疑")
        chatbot = gr.Chatbot(height=500, type="messages")
        with gr.Row():
            deep_check = gr.Checkbox(label="🧠 深度思考", value=False)
            srch_check = gr.Checkbox(label="🔍 联网搜索", value=False)
        with gr.Row():
            txt = gr.Textbox(show_label=False, placeholder="输入数学题，例如：求 sin(x) 的导数", scale=4)
            btn = gr.Button("发送", scale=1)

    # 逻辑绑定
    def start_app(email, password):
        # 简单演示：如果数据库挂了，也允许临时测试
        u, n, err = do_login(email, password)
        if u:
            return gr.update(visible=False), gr.update(visible=True), u, n, load_history_chat(u)
        return gr.update(), gr.update(), None, None, []

    login_btn.click(start_app, [email_input, pass_input], [auth_page, chat_page, logged_in_user, logged_in_nick, chatbot])
    
    btn.click(respond, [txt, chatbot, deep_check, srch_check, logged_in_user, logged_in_nick], [txt, chatbot])
    txt.submit(respond, [txt, chatbot, deep_check, srch_check, logged_in_user, logged_in_nick], [txt, chatbot])

# --- 6. 关键：监听 Railway 端口 ---
if __name__ == "__main__":
    # 必须从环境变量读取 PORT，否则 Railway 无法识别服务
    raw_port = os.environ.get("PORT", "7860")
    print(f"🚀 程序启动中，监听端口: {raw_port}")
    demo.launch(
        server_name="0.0.0.0", 
        server_port=int(raw_port),
        share=False,
        show_error=True # 开启报错显示
    )
