import os
import json
import hashlib
import secrets
import sys
import logging
import urllib.parse
from datetime import datetime

import gradio as gr
import psycopg2
from psycopg2 import pool
from openai import OpenAI
from duckduckgo_search import DDGS
import bcrypt  # 更安全的密码哈希

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 配置常量 ---
DEFAULT_MODEL = "deepseek-chat"
REASONER_MODEL = "deepseek-reasoner"
MAX_HISTORY = 20  # 历史记录最大条数
MAX_QUESTION_LENGTH = 1000
MAX_EMAIL_LENGTH = 255
MIN_PASSWORD_LENGTH = 8
SEARCH_RESULTS_LIMIT = 3
SEARCH_MAX_CHARS = 500  # 每个搜索结果最大字符数

# 环境变量检查
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("环境变量 DATABASE_URL 未设置")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise ValueError("环境变量 DEEPSEEK_API_KEY 未设置")

# --- 数据库连接池 ---
class DatabasePool:
    _instance = None
    _pool = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._init_pool()
        return cls._instance

    @classmethod
    def _init_pool(cls):
        try:
            r = urllib.parse.urlparse(DATABASE_URL)
            cls._pool = psycopg2.pool.SimpleConnectionPool(
                1, 10,  # 最小1，最大10个连接
                host=r.hostname,
                port=r.port or 5432,
                database=r.path.lstrip("/"),
                user=r.username,
                password=r.password,
                sslmode="prefer"
            )
            logger.info("数据库连接池初始化成功")
        except Exception as e:
            logger.error(f"数据库连接池初始化失败: {e}")
            raise

    def get_conn(self):
        return self._pool.getconn()

    def return_conn(self, conn):
        self._pool.putconn(conn)

    def close_all(self):
        self._pool.closeall()

db_pool = DatabasePool()

# --- 数据库操作封装 ---
def db_exec(sql, params=(), fetch=None):
    conn = None
    try:
        conn = db_pool.get_conn()
        cur = conn.cursor()
        cur.execute(sql, params)
        result = None
        if fetch == "one":
            result = cur.fetchone()
        elif fetch == "all":
            result = cur.fetchall()
        conn.commit()
        return result
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        logger.error(f"数据库执行错误: {e}", exc_info=True)
        raise
    finally:
        if conn:
            db_pool.return_conn(conn)

def init_db():
    try:
        db_exec("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        db_exec("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                email TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        logger.info("数据库表初始化完成")
    except Exception as e:
        logger.error(f"初始化数据库表失败: {e}")
        raise

init_db()

# --- 用户认证逻辑（使用 bcrypt）---
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()

def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def validate_email(email: str) -> bool:
    return "@" in email and len(email) <= MAX_EMAIL_LENGTH

def validate_password(password: str) -> bool:
    return len(password) >= MIN_PASSWORD_LENGTH

def do_register(email, password, confirm):
    email = email.lower().strip()
    if not email or not password:
        return "❌ 请填写邮箱和密码"
    if not validate_email(email):
        return "❌ 邮箱格式不正确或过长"
    if password != confirm:
        return "❌ 两次密码不一致"
    if not validate_password(password):
        return f"❌ 密码至少 {MIN_PASSWORD_LENGTH} 位"

    # 先检查邮箱是否已存在
    existing = db_exec("SELECT 1 FROM users WHERE email=%s", (email,), fetch="one")
    if existing:
        return "❌ 该邮箱已注册"

    hashed = hash_password(password)
    try:
        db_exec("INSERT INTO users (email, password_hash) VALUES (%s, %s)", (email, hashed))
        logger.info(f"新用户注册: {email}")
        return "✅ 注册成功！请登录"
    except Exception as e:
        logger.error(f"注册失败: {e}")
        return f"❌ 注册失败，请稍后重试"

def do_login(email, password):
    email = email.lower().strip()
    if not email or not password:
        return None, None, "❌ 请输入邮箱和密码"

    row = db_exec("SELECT email, password_hash FROM users WHERE email=%s", (email,), fetch="one")
    if not row:
        return None, None, "❌ 邮箱或密码错误"

    db_email, db_hash = row
    if check_password(password, db_hash):
        nickname = db_email.split("@")[0]
        return db_email, nickname, None
    else:
        return None, None, "❌ 邮箱或密码错误"

# --- 历史记录管理 ---
def save_conversation(email, question, answer):
    if not email or not question or not answer:
        return
    # 限制问题长度
    question = question[:MAX_QUESTION_LENGTH]
    try:
        db_exec("INSERT INTO conversations (email, question, answer) VALUES (%s, %s, %s)",
                (email, question, answer))
    except Exception as e:
        logger.error(f"保存对话失败: {e}")

def load_history(email, limit=MAX_HISTORY):
    """返回用于聊天界面的历史记录列表（格式：messages）"""
    if not email:
        return []
    try:
        rows = db_exec(
            "SELECT question, answer FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT %s",
            (email, limit), fetch="all") or []
        messages = []
        for q, a in reversed(rows):
            messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": a})
        return messages
    except Exception as e:
        logger.error(f"加载历史失败: {e}")
        return []

def load_history_questions(email, limit=MAX_HISTORY):
    """返回仅包含问题的列表，用于侧边栏显示"""
    if not email:
        return []
    try:
        rows = db_exec(
            "SELECT question FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT %s",
            (email, limit), fetch="all") or []
        return [[r[0], ""] for r in rows]  # 格式兼容原JS
    except Exception as e:
        logger.error(f"加载问题列表失败: {e}")
        return []

def delete_last_conversation(email):
    if not email:
        return
    try:
        db_exec("""
            DELETE FROM conversations
            WHERE id = (
                SELECT id FROM conversations
                WHERE email=%s
                ORDER BY id DESC
                LIMIT 1
            )
        """, (email,))
    except Exception as e:
        logger.error(f"删除最近对话失败: {e}")

def clear_all_history(email):
    if not email:
        return
    try:
        db_exec("DELETE FROM conversations WHERE email=%s", (email,))
    except Exception as e:
        logger.error(f"清空历史失败: {e}")

# --- AI 与搜索逻辑 ---
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")

def web_search(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=SEARCH_RESULTS_LIMIT))
        if not results:
            return ""

        # 精简搜索结果，避免过长
        summaries = []
        for r in results:
            title = r.get('title', '')[:100]
            body = r.get('body', '')[:SEARCH_MAX_CHARS]
            summaries.append(f"来源：{title}\n{body}")
        return "\n\n【搜索结果】\n" + "\n\n".join(summaries)
    except Exception as e:
        logger.warning(f"搜索失败: {e}")
        return ""

def ask(message, history, deep_think, use_search, nickname):
    model = REASONER_MODEL if deep_think else DEFAULT_MODEL
    search_ctx = web_search(message) if use_search else ""

    user_msg_count = len([m for m in history if m["role"] == "user"])
    level = "这是第一次提问，请友好介绍自己。" if user_msg_count == 0 else "请耐心详细解释。"

    name_str = f"同学叫【{nickname}】，请称呼他/她。" if nickname else ""
    sys_prompt = f"你叫pig，是专业的大学数学辅导老师。{name_str}{level}\n使用 LaTeX 渲染公式。步骤清晰、先思路后计算、最后总结、态度亲切。"
    if search_ctx:
        sys_prompt += f"\n\n参考搜索结果：{search_ctx}"

    messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": message}]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=4000,
            temperature=0.3
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"AI 请求失败: {e}")
        raise  # 让上层处理，避免保存错误回答

def respond(message, chat_history, deep, search, current_user, nickname):
    if not message or not message.strip():
        return "", chat_history
    message = message.strip()[:MAX_QUESTION_LENGTH]  # 前端也需限制

    if not isinstance(chat_history, list):
        chat_history = []

    try:
        answer = ask(message, chat_history, deep, search, nickname)
        if current_user:
            save_conversation(current_user, message, answer)
    except Exception as e:
        answer = f"⚠️ 请求失败：{str(e)}"
        # 不保存错误回答

    chat_history.append({"role": "user", "content": message})
    chat_history.append({"role": "assistant", "content": answer})
    return "", chat_history

# --- 处理注册和登录的辅助函数 ---
def handle_register(email, password, confirm):
    msg = do_register(email, password, confirm)
    # 如果注册成功，切换到登录标签
    if msg.startswith("✅"):
        return gr.update(visible=True), gr.update(selected="登录"), msg
    else:
        return gr.update(visible=True), gr.update(), msg

def handle_login(email, password):
    db_email, nickname, error = do_login(email, password)
    if db_email:
        history = load_history(db_email)
        js_update = make_update_js(db_email)
        return (gr.update(visible=False), gr.update(visible=True), db_email, nickname,
                "", history, js_update)
    return (gr.update(visible=True), gr.update(visible=False), None, None,
            f'<p style="color:red">{error}</p>', [], "")

def handle_logout():
    return gr.update(visible=True), gr.update(visible=False), None, None, [], ""

def make_update_js(email):
    """生成更新侧边栏历史问题的JavaScript代码"""
    items = load_history_questions(email)
    data = json.dumps(items, ensure_ascii=False)
    return f'<script>window._pigData={data}; if(window.pigRender) pigRender();</script>'

# --- UI 定义（基本保持不变，但修复了注册逻辑和切换）---
CSS = """
* { box-sizing:border-box; margin:0; padding:0; }
body,.gradio-container { background:#f7f7f5 !important; font-family:Georgia,serif !important; max-width:100% !important; }
footer,.built-with { display:none !important; }
#auth-box { max-width:400px; margin:60px auto; background:#fff; border-radius:20px; padding:36px 32px; box-shadow:0 4px 24px rgba(0,0,0,.08); }
#auth-submit { background:#cc6a45 !important; border-radius:10px !important; color:white !important; font-size:15px !important; width:100% !important; }
#auth-msg { text-align:center; font-size:14px; margin-top:8px; }
#chatbot { background:transparent !important; border:none !important; }
.input-area { background:#f7f7f5 !important; border-top:1px solid #e5e5e0 !important; padding:8px 12px 24px !important; }
.input-inner { background:#fff; border:1.5px solid #ddddd8; border-radius:18px; padding:10px 12px 8px; box-shadow:0 2px 10px rgba(0,0,0,.07); }
#msg-input textarea { background:transparent !important; border:none !important; outline:none !important; font-size:15px !important; resize:none !important; font-family:inherit !important; }
#send-btn { background:#cc6a45 !important; border:none !important; border-radius:10px !important; width:36px !important; height:36px !important; min-width:36px !important; padding:0 !important; color:white !important; font-size:20px !important; }
.welcome-wrap { text-align:center; padding:20px 16px; }
#pig-drawer { position: fixed; top: 0; left: 0; width: 280px; max-width: 80vw; height: 100vh; background: #fff; z-index: 9999; transform: translateX(-100%); transition: transform 0.28s ease; box-shadow: 4px 0 24px rgba(0,0,0,0.15); display: flex; flex-direction: column; }
#pig-drawer.open { transform: translateX(0); }
#pig-overlay { display: none; position: fixed; top:0; left:0; width:100vw; height:100vh; background: rgba(0,0,0,0.4); z-index: 9998; }
#pig-overlay.open { display: block; }
#pig-topbar { display: flex; align-items: center; padding: 8px 12px; border-bottom: 1px solid #e5e5e0; background: #f7f7f5; position: sticky; top: 0; z-index: 100; }
#pig-topbar .pig-nav-btn { background: none; border: none; cursor: pointer; font-size: 20px; padding: 4px 8px; border-radius: 8px; line-height: 1; }
#pig-exit-btn { background: none; border: 1px solid #ddd; border-radius: 8px; font-size: 12px; cursor: pointer; padding: 4px 10px; color: #888; }
"""

NAV_AND_DRAWER = """
<div id="pig-overlay" onclick="pigClose()"></div>
<div id="pig-drawer">
  <div style="padding:16px;border-bottom:1px solid #e5e5e0;display:flex;align-items:center;justify-content:space-between;">
    <span style="font-size:15px;font-weight:600;">📋 历史提问</span>
    <button class="pig-nav-btn" onclick="pigClose()" style="color:#888;">✕</button>
  </div>
  <div style="padding:10px 12px;display:flex;gap:8px;border-bottom:1px solid #e5e5e0;">
    <button onclick="pigDel()" style="flex:1;padding:7px;border-radius:8px;border:1px solid #ddd;font-size:12px;cursor:pointer;background:#fff;">🗑 删除最近</button>
    <button onclick="pigClearAll()" style="flex:1;padding:7px;border-radius:8px;border:1px solid #e88;font-size:12px;cursor:pointer;background:#fff;color:#c44;">⚠️ 清空</button>
  </div>
  <div id="pig-status" style="padding:6px 16px;font-size:12px;color:#cc6a45;min-height:22px;"></div>
  <div id="pig-list" style="flex:1;overflow-y:auto;padding:8px 0;"></div>
</div>
<div id="pig-topbar">
  <button class="pig-nav-btn" onclick="pigOpen()">☰</button>
  <span style="flex:1;text-align:center;font-size:15px;font-weight:600;color:#1a1a1a;">📐 pig</span>
  <button class="pig-nav-btn" onclick="pigClearChat()" title="清空对话">🗑</button>
  <button id="pig-exit-btn" onclick="pigLogout()">退出</button>
</div>
<script>
window._pigData = [];
window.pigRender = function() {
    var el = document.getElementById('pig-list');
    if (!el) return;
    var items = window._pigData || [];
    if (!items.length) { el.innerHTML = '<div style="padding:24px;text-align:center;color:#aaa;font-size:13px;">暂无历史记录</div>'; return; }
    el.innerHTML = items.map(function(it) {
        return '<div style="padding:12px 16px;border-bottom:1px solid #f0f0ee;"><div style="font-size:13px;">'+it[0]+'</div></div>';
    }).join('');
};
window.pigOpen = function() { pigRender(); document.getElementById('pig-drawer').classList.add('open'); document.getElementById('pig-overlay').classList.add('open'); };
window.pigClose = function() { document.getElementById('pig-drawer').classList.remove('open'); document.getElementById('pig-overlay').classList.remove('open'); };
function clickById(id) { var b = document.getElementById(id); if (b) b.click(); }
function pigDel() { clickById('_pdel'); }
function pigClearAll() { if(confirm('确定清空？')) clickById('_pclr'); }
function pigClearChat(){ clickById('_pcc'); }
function pigLogout()   { clickById('_plo'); }
</script>
"""

# --- Gradio 应用构建 ---
with gr.Blocks(theme=gr.themes.Base(), title="pig", css=CSS) as demo:
    logged_in_user = gr.State(None)
    logged_in_nick = gr.State(None)

    with gr.Column(elem_id="auth-box", visible=True) as auth_page:
        gr.HTML('<div style="text-align:center;margin-bottom:24px;"><div style="width:52px;height:52px;background:#cc6a45;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;font-size:24px;">📐</div><h2 style="font-size:22px;font-weight:600;margin-top:12px;">pig</h2><p style="color:#888;font-size:13px;">你的数学辅导老师</p></div>')
        with gr.Tabs() as tabs:
            with gr.Tab("登录", id="login"):
                login_email = gr.Textbox(placeholder="邮箱", show_label=False, max_lines=1)
                login_pass  = gr.Textbox(placeholder="密码", show_label=False, type="password", max_lines=1)
                login_btn   = gr.Button("登录", elem_id="auth-submit", variant="primary")
                login_msg   = gr.HTML(elem_id="auth-msg")
            with gr.Tab("注册", id="register"):
                reg_email   = gr.Textbox(placeholder="邮箱", show_label=False, max_lines=1)
                reg_pass    = gr.Textbox(placeholder="密码", show_label=False, type="password", max_lines=1)
                reg_confirm = gr.Textbox(placeholder="确认密码", show_label=False, type="password", max_lines=1)
                reg_btn     = gr.Button("注册", elem_id="auth-submit", variant="primary")
                reg_msg     = gr.HTML(elem_id="auth-msg")

    with gr.Column(visible=False) as chat_page:
        gr.HTML(NAV_AND_DRAWER)
        data_updater = gr.HTML("")

        _pdel = gr.Button("d", visible=False, elem_id="_pdel")
        _pclr = gr.Button("c", visible=False, elem_id="_pclr")
        _pcc  = gr.Button("cc", visible=False, elem_id="_pcc")
        _plo  = gr.Button("lo", visible=False, elem_id="_plo")

        chatbot = gr.Chatbot(elem_id="chatbot", show_label=False, height=550, type="messages")

        with gr.Column(elem_classes="input-area"):
            with gr.Row():
                deep_think = gr.Checkbox(label="🧠 深度思考", value=False)
                use_search = gr.Checkbox(label="🔍 联网搜索", value=False)
            with gr.Column(elem_classes="input-inner"):
                with gr.Row():
                    msg  = gr.Textbox(placeholder="输入数学问题...", show_label=False, scale=5, lines=1,
                                      elem_id="msg-input", max_lines=5)
                    send = gr.Button("↑", variant="primary", scale=0, elem_id="send-btn")

    # 注册事件
    reg_btn.click(
        handle_register,
        [reg_email, reg_pass, reg_confirm],
        [auth_page, tabs, reg_msg]  # 更新 auth_page（保持可见）、tabs（切换选中标签）、reg_msg
    )

    login_btn.click(
        handle_login,
        [login_email, login_pass],
        [auth_page, chat_page, logged_in_user, logged_in_nick, login_msg, chatbot, data_updater]
    )

    _plo.click(
        handle_logout,
        [],
        [auth_page, chat_page, logged_in_user, logged_in_nick, chatbot, data_updater]
    )

    _pcc.click(lambda: [], [], [chatbot])

    def del_and_reload(user):
        delete_last_conversation(user)
        return load_history(user), make_update_js(user)

    _pdel.click(del_and_reload, [logged_in_user], [chatbot, data_updater])

    def clear_and_reload(user):
        clear_all_history(user)
        return [], make_update_js(user)

    _pclr.click(clear_and_reload, [logged_in_user], [chatbot, data_updater])

    send.click(respond, [msg, chatbot, deep_think, use_search, logged_in_user, logged_in_nick], [msg, chatbot])
    msg.submit(respond, [msg, chatbot, deep_think, use_search, logged_in_user, logged_in_nick], [msg, chatbot])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
