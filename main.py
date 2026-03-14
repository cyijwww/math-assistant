import os
import json
import hashlib
import secrets
import gradio as gr
from openai import OpenAI
from duckduckgo_search import DDGS
import psycopg2

# ── 配置 ──
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ADMIN_EMAIL  = "abc13112629791@qq.com"

# ── 数据库连接 ──
def get_conn():
    import urllib.parse
    r = urllib.parse.urlparse(DATABASE_URL)
    return psycopg2.connect(
        host=r.hostname, port=r.port or 6543,
        database=r.path.lstrip("/"),
        user=r.username, password=r.password,
        sslmode="require"
    )

def db_exec(sql, params=(), fetch=None):
    """统一执行 SQL，减少重复代码"""
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(sql, params)
        result = None
        if fetch == "one":  result = cur.fetchone()
        if fetch == "all":  result = cur.fetchall()
        conn.commit()
        conn.close()
        return result
    except Exception as e:
        print(f"DB error: {e}")
        return None

def init_db():
    db_exec("""CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS conversations (
        id SERIAL PRIMARY KEY,
        email TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
    )""")
    # 兼容旧表（无 salt 列）
    try:
        db_exec("ALTER TABLE users ADD COLUMN IF NOT EXISTS salt TEXT NOT NULL DEFAULT ''")
    except:
        pass

init_db()

# ── 密码安全（SHA256 + salt）──
def hash_pw(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return h, salt

# ── 用户认证 ──
def do_register(email, password, confirm):
    email = email.lower().strip()
    if not email or not password:    return "❌ 请填写邮箱和密码"
    if "@" not in email:             return "❌ 邮箱格式不正确"
    if password != confirm:          return "❌ 两次密码不一致"
    if len(password) < 6:            return "❌ 密码至少6位"
    h, salt = hash_pw(password)
    try:
        db_exec("INSERT INTO users (email, password_hash, salt) VALUES (%s,%s,%s)", (email, h, salt))
        return "✅ 注册成功！请切换到登录标签登录"
    except psycopg2.errors.UniqueViolation:
        return "❌ 该邮箱已注册"
    except Exception as e:
        return f"❌ 错误：{e}"

def do_login(email, password):
    email = email.lower().strip()
    if not email or not password:
        return None, None, "❌ 请输入邮箱和密码"
    row = db_exec("SELECT email, password_hash, salt FROM users WHERE email=%s", (email,), fetch="one")
    if not row:
        return None, None, "❌ 邮箱或密码错误"
    db_email, db_hash, salt = row
    h, _ = hash_pw(password, salt or "")
    if h == db_hash:
        nickname = email.split("@")[0]
        return db_email, nickname, None
    return None, None, "❌ 邮箱或密码错误"

# ── 对话存储 ──
def save_conversation(email, question, answer):
    db_exec("INSERT INTO conversations (email,question,answer) VALUES (%s,%s,%s)", (email, question, answer))

def load_history(email):
    rows = db_exec(
        "SELECT question, answer FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 50",
        (email,), fetch="all") or []
    return [(q, a) for q, a in reversed(rows)]

def load_history_with_meta(email):
    rows = db_exec(
        "SELECT question, answer, created_at FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 50",
        (email,), fetch="all") or []
    result = []
    for q, a, t in rows:
        ts = t.strftime("%Y-%m-%d %H:%M") if t else ""
        result.append((f"[{ts}] {q}", a))
    return result

def delete_last_conversation(email):
    db_exec(
        "DELETE FROM conversations WHERE id=(SELECT id FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 1)",
        (email,))

def clear_all_history(email):
    db_exec("DELETE FROM conversations WHERE email=%s", (email,))

def load_all_conversations():
    rows = db_exec(
        "SELECT email, question, answer, created_at FROM conversations ORDER BY created_at DESC LIMIT 200",
        fetch="all") or []
    result = []
    for email, q, a, t in rows:
        ts = t.strftime("%m-%d %H:%M") if t else ""
        result.append((f"[{ts}] {email}：{q}", a))
    return result

# ── AI 核心 ──
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-3b1488b14e6349a2b3d366c23814a053"),
    base_url="https://api.deepseek.com/v1"
)

def web_search(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results: return ""
        return "\n\n【网络搜索结果】\n" + "\n\n".join(
            [f"来源：{r['title']}\n内容：{r['body']}" for r in results]
        ) + "\n【搜索结束】\n"
    except:
        return ""

def fix_latex(text):
    for s in ["\\(","\\)","\\[","\\]","$$","$"]:
        text = text.replace(s, "")
    return text

def ask(message, history, deep_think, use_search, nickname):
    model = "deepseek-reasoner" if deep_think else "deepseek-chat"
    search_ctx = web_search(message) if use_search else ""
    n = len(history)
    level = "这是第一次提问，请友好介绍自己。" if n==0 else ("请耐心详细解释。" if n<5 else "可以适当加深难度。")
    name_str = f"同学叫【{nickname}】，请称呼他/她的名字。" if nickname else ""
    sys = f"""你叫pig，是专业的大学数学辅导老师。{name_str}{level}
回答要求：步骤清晰、先思路后计算、最后总结答案、态度亲切。"""
    if search_ctx:
        sys += f"\n\n参考搜索结果：{search_ctx}"
    messages = [{"role":"system","content":sys}]
    for item in history:
        if isinstance(item, tuple):
            messages.append({"role":"user","content":item[0]})
            if item[1]: messages.append({"role":"assistant","content":item[1]})
    messages.append({"role":"user","content":message})
    resp = client.chat.completions.create(model=model, messages=messages, max_tokens=4000, temperature=0.3)
    return fix_latex(resp.choices[0].message.content)

def respond(message, chat_history, deep, search, current_user, nickname):
    if not message.strip():
        return "", chat_history, make_sidebar_js(current_user)
    try:
        answer = ask(message, chat_history, deep, search, nickname)
        if current_user:
            save_conversation(current_user, message, answer)
    except Exception as e:
        answer = f"⚠️ 请求失败：{str(e)}"
    chat_history.append((message, answer))
    return "", chat_history, make_sidebar_js(current_user)

def make_sidebar_js(email):
    items = load_history_with_meta(email) if email else []
    data  = json.dumps(items, ensure_ascii=False)
    return f"<script>window._pigHistoryData={data};if(typeof renderSidebar==='function')renderSidebar();</script>"

# ── CSS ──
CSS = """
* { box-sizing:border-box; margin:0; padding:0; }
body,.gradio-container { background:#f7f7f5 !important; font-family:Georgia,serif !important; max-width:100% !important; }
footer,.built-with { display:none !important; }
#auth-box { max-width:400px; margin:60px auto; background:#fff; border-radius:20px; padding:36px 32px; box-shadow:0 4px 24px rgba(0,0,0,.08); }
#auth-submit { background:#cc6a45 !important; border-radius:10px !important; color:white !important; font-size:15px !important; width:100% !important; }
#auth-msg { text-align:center; font-size:14px; margin-top:8px; }
#chatbot { background:transparent !important; border:none !important; width:100% !important; padding:12px !important; flex:1 !important; overflow-y:auto !important; }
.chat-wrap { display:flex !important; flex-direction:column !important; height:100vh !important; overflow:hidden !important; }
.input-area { background:#f7f7f5 !important; border-top:1px solid #e5e5e0 !important; padding:10px 12px 20px !important; flex-shrink:0 !important; }
.input-inner { background:#fff; border:1.5px solid #ddddd8; border-radius:18px; padding:10px 12px 8px; box-shadow:0 2px 10px rgba(0,0,0,.07); }
#deep-check { font-size:12px !important; color:#888880 !important; margin-bottom:6px !important; }
#deep-check label { color:#888880 !important; font-size:12px !important; }
#msg-input textarea { background:transparent !important; border:none !important; outline:none !important; font-size:15px !important; color:#1a1a1a !important; resize:none !important; font-family:inherit !important; line-height:1.5 !important; padding:0 !important; width:100% !important; }
#msg-input textarea::placeholder { color:#b0b0a8 !important; }
#msg-input .wrap { border:none !important; box-shadow:none !important; background:transparent !important; padding:0 !important; }
#msg-input { border:none !important; flex:1 !important; }
#send-btn { background:#cc6a45 !important; border:none !important; border-radius:10px !important; width:36px !important; height:36px !important; min-width:36px !important; padding:0 !important; cursor:pointer !important; color:white !important; font-size:20px !important; line-height:1 !important; }
.welcome-wrap { text-align:center; padding:30px 16px 20px; max-width:580px; margin:0 auto; }
#sidebar-overlay { display:none; position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(0,0,0,.35); z-index:1000; }
#sidebar-overlay.open { display:block; }
#sidebar { position:fixed; top:0; left:0; width:300px; max-width:85vw; height:100vh; background:#fff; z-index:1001; transform:translateX(-100%); transition:transform .3s ease; display:flex; flex-direction:column; box-shadow:4px 0 20px rgba(0,0,0,.15); }
#sidebar.open { transform:translateX(0); }
#sidebar-header { padding:16px; border-bottom:1px solid #e5e5e0; display:flex; align-items:center; justify-content:space-between; }
#sidebar-title { font-size:15px; font-weight:600; color:#1a1a1a; }
#sidebar-close { background:none; border:none; font-size:20px; cursor:pointer; color:#888; padding:4px 8px; }
#sidebar-actions { padding:10px 12px; display:flex; gap:8px; border-bottom:1px solid #e5e5e0; }
#sidebar-del-btn,#sidebar-clear-btn { flex:1; padding:7px; border-radius:8px; border:1px solid #ddd; font-size:12px; cursor:pointer; background:#fff; }
#sidebar-clear-btn { border-color:#e88; color:#c44; }
#sidebar-list { flex:1; overflow-y:auto; padding:8px 0; }
.sidebar-item { padding:12px 16px; border-bottom:1px solid #f0f0ee; }
.sidebar-item-time { font-size:11px; color:#aaa; margin-bottom:4px; }
.sidebar-item-q { font-size:13px; color:#1a1a1a; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
#sidebar-status { padding:8px 16px; font-size:12px; color:#cc6a45; min-height:24px; }
"""

SIDEBAR_JS = """
<div id="sidebar-overlay" onclick="closeSidebar()"></div>
<div id="sidebar">
  <div id="sidebar-header">
    <span id="sidebar-title">📋 历史提问</span>
    <button id="sidebar-close" onclick="closeSidebar()">✕</button>
  </div>
  <div id="sidebar-actions">
    <button id="sidebar-del-btn" onclick="deleteLastItem()">🗑 删除最近一条</button>
    <button id="sidebar-clear-btn" onclick="clearAllItems()">⚠️ 清空全部</button>
  </div>
  <div id="sidebar-status"></div>
  <div id="sidebar-list"></div>
</div>
<script>
window._pigHistoryData = [];
function openSidebar() {
    renderSidebar();
    document.getElementById('sidebar').classList.add('open');
    document.getElementById('sidebar-overlay').classList.add('open');
}
function closeSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-overlay').classList.remove('open');
}
function renderSidebar() {
    var list  = document.getElementById('sidebar-list');
    var items = window._pigHistoryData || [];
    if (!items.length) {
        list.innerHTML = '<div style="padding:24px;text-align:center;color:#aaa;font-size:13px;">暂无历史记录</div>';
        return;
    }
    list.innerHTML = items.map(function(item) {
        var m = item[0].match(/^\\x5B(.+?)\\x5D (.+)$/);
        var time = m ? m[1] : '';
        var q    = m ? m[2] : item[0];
        return '<div class="sidebar-item"><div class="sidebar-item-time">'+time+'</div><div class="sidebar-item-q">'+q+'</div></div>';
    }).join('');
}
function setStatus(msg) {
    var el = document.getElementById('sidebar-status');
    el.innerText = msg;
    setTimeout(function(){ el.innerText=''; }, 2000);
}
function deleteLastItem() {
    var btn = document.getElementById('del-trigger-btn');
    if (btn) { btn.click(); setStatus('✅ 已删除最近一条'); }
}
function clearAllItems() {
    if (!confirm('确定清空全部历史记录？')) return;
    var btn = document.getElementById('clear-trigger-btn');
    if (btn) { btn.click(); setStatus('✅ 已清空全部'); }
}
</script>
"""

# ── UI ──
with gr.Blocks(theme=gr.themes.Base(), title="pig", css=CSS) as demo:

    logged_in_user = gr.State(None)   # 存邮箱
    logged_in_nick = gr.State(None)   # 存昵称

    # ── 登录/注册页 ──
    with gr.Column(elem_id="auth-box", visible=True) as auth_page:
        gr.HTML("""
        <div style="text-align:center;margin-bottom:24px;">
          <div style="width:52px;height:52px;background:#cc6a45;border-radius:14px;
                      display:inline-flex;align-items:center;justify-content:center;font-size:24px;">📐</div>
          <h2 style="font-size:22px;font-weight:600;color:#1a1a1a;margin-top:12px;">pig</h2>
          <p style="color:#888;font-size:13px;margin-top:4px;">你的专属数学辅导老师</p>
        </div>""")
        with gr.Tabs() as tabs:
            with gr.Tab("登录"):
                login_email = gr.Textbox(placeholder="邮箱", show_label=False)
                login_pass  = gr.Textbox(placeholder="密码", show_label=False, type="password")
                login_btn   = gr.Button("登录", elem_id="auth-submit", variant="primary")
                login_msg   = gr.HTML(elem_id="auth-msg")
            with gr.Tab("注册"):
                reg_email   = gr.Textbox(placeholder="邮箱（QQ/163/Gmail均可）", show_label=False)
                reg_pass    = gr.Textbox(placeholder="密码（至少6位）", show_label=False, type="password")
                reg_confirm = gr.Textbox(placeholder="确认密码", show_label=False, type="password")
                reg_btn     = gr.Button("注册", elem_id="auth-submit", variant="primary")
                reg_msg     = gr.HTML(elem_id="auth-msg")
                gr.HTML("""<p style='text-align:center;color:#aaa;font-size:12px;margin-top:8px;'>注册成功后请点击上方"登录"标签</p>""")

    # ── 聊天页 ──
    with gr.Column(visible=False) as chat_page:
        gr.HTML(SIDEBAR_JS)

        # 顶部导航
        gr.HTML("""
        <div style="display:flex;align-items:center;padding:10px 12px;border-bottom:1px solid #e5e5e0;background:#f7f7f5;gap:10px;">
          <button onclick="openSidebar()" style="background:none;border:none;font-size:20px;cursor:pointer;padding:0 4px;">☰</button>
          <span style="font-size:15px;font-weight:600;color:#1a1a1a;flex:1;text-align:center;">📐 pig</span>
        </div>""")

        logout_btn = gr.Button("退出登录", variant="secondary", size="sm")
        admin_btn  = gr.Button("🔧 管理员后台", variant="secondary", visible=False, size="sm")

        # 隐藏触发按钮
        delete_last_btn = gr.Button("del",   visible=False, elem_id="del-trigger-btn")
        clear_all_btn   = gr.Button("clear", visible=False, elem_id="clear-trigger-btn")
        sidebar_updater = gr.HTML("", visible=False)

        # 聊天视图
        with gr.Column(visible=True, elem_classes="chat-wrap") as chat_view:
            gr.HTML("""
            <div class="welcome-wrap">
              <div style="width:56px;height:56px;background:#cc6a45;border-radius:16px;
                          display:flex;align-items:center;justify-content:center;font-size:26px;margin:0 auto 20px;">📐</div>
              <h1 style="font-size:26px;font-weight:600;color:#1a1a1a;margin:0 0 10px;">你好，我是pig</h1>
              <p style="font-size:15px;color:#777770;margin:0;line-height:1.7;">
                你的专属大学数学辅导老师<br>微积分 · 线性代数 · 概率论 · 离散数学
              </p>
            </div>""")
            chatbot = gr.Chatbot(elem_id="chatbot", show_label=False, height=600)
            with gr.Column(elem_classes="input-area"):
                deep_think = gr.Checkbox(label="🧠 深度思考（DeepSeek-R1）", value=False, elem_id="deep-check")
                use_search = gr.Checkbox(label="🔍 智能搜索", value=False, elem_id="deep-check")
                with gr.Column(elem_classes="input-inner"):
                    with gr.Row():
                        msg  = gr.Textbox(placeholder="向pig提问任何数学问题...", show_label=False, scale=5, lines=1, max_lines=8, elem_id="msg-input")
                        send = gr.Button("↑", variant="primary", scale=0, elem_id="send-btn")

        # 管理员视图
        with gr.Column(visible=False) as admin_view:
            gr.HTML("""<div style='padding:16px;border-bottom:1px solid #e5e5e0;'>
              <h3 style='color:#cc6a45;margin:0;'>🔧 管理员后台</h3>
              <p style='color:#888;font-size:13px;margin:4px 0 0;'>所有学生提问记录</p>
            </div>""")
            back_admin_btn = gr.Button("← 返回聊天", variant="secondary")
            admin_display  = gr.Chatbot(show_label=False, height=600)

    # ── 事件处理 ──
    def handle_login(email, password):
        db_email, nickname, error = do_login(email, password)
        if db_email:
            history  = load_history(db_email)
            is_admin = db_email == ADMIN_EMAIL
            sidebar_js = make_sidebar_js(db_email)
            return (gr.update(visible=False), gr.update(visible=True),
                    db_email, nickname, "", history,
                    gr.update(visible=is_admin), sidebar_js)
        return (gr.update(visible=True), gr.update(visible=False),
                None, None, f'<p style="color:red">{error}</p>', [],
                gr.update(visible=False), "")

    def handle_register(email, password, confirm):
        result = do_register(email, password, confirm)
        color  = "green" if "✅" in result else "red"
        msg_html = f'<p style="color:{color}">{result}</p>'
        return msg_html, (gr.update(selected=0) if "✅" in result else gr.update())

    def handle_logout():
        return (gr.update(visible=True), gr.update(visible=False),
                None, None, [], "")

    def do_delete_last(email):
        if not email: return make_sidebar_js(None)
        delete_last_conversation(email)
        return make_sidebar_js(email)

    def do_clear_all(email):
        if not email: return make_sidebar_js(None)
        clear_all_history(email)
        return make_sidebar_js(email)

    def show_admin():
        return gr.update(visible=False), gr.update(visible=True), load_all_conversations()

    def hide_admin():
        return gr.update(visible=True), gr.update(visible=False)

    # 登录输出：auth_page, chat_page, user, nick, login_msg, chatbot, admin_btn, sidebar_updater
    login_outputs = [auth_page, chat_page, logged_in_user, logged_in_nick, login_msg, chatbot, admin_btn, sidebar_updater]
    login_btn.click(handle_login, [login_email, login_pass], login_outputs)
    login_email.submit(handle_login, [login_email, login_pass], login_outputs)

    reg_btn.click(handle_register, [reg_email, reg_pass, reg_confirm], [reg_msg, tabs])

    logout_btn.click(handle_logout, [],
        [auth_page, chat_page, logged_in_user, logged_in_nick, chatbot, sidebar_updater])

    send.click(respond, [msg, chatbot, deep_think, use_search, logged_in_user, logged_in_nick],
               [msg, chatbot, sidebar_updater])
    msg.submit(respond,  [msg, chatbot, deep_think, use_search, logged_in_user, logged_in_nick],
               [msg, chatbot, sidebar_updater])

    delete_last_btn.click(do_delete_last, [logged_in_user], [sidebar_updater])
    clear_all_btn.click(do_clear_all,     [logged_in_user], [sidebar_updater])

    admin_btn.click(show_admin, [], [chat_view, admin_view, admin_display])
    back_admin_btn.click(hide_admin, [], [chat_view, admin_view])

port = int(os.environ.get("PORT", 7860))
demo.launch(server_name="0.0.0.0", server_port=port)
