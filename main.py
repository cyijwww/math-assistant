import os
import json
import hashlib
import secrets
import sys
import gradio as gr
from openai import OpenAI
from duckduckgo_search import DDGS
import psycopg2
from datetime import datetime

# --- 系统保护：防止递归深度超限 ---
sys.setrecursionlimit(2000)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_conn():
    import urllib.parse
    r = urllib.parse.urlparse(DATABASE_URL)
    return psycopg2.connect(
        host=r.hostname, port=r.port or 5432,
        database=r.path.lstrip("/"),
        user=r.username, password=r.password,
        sslmode="prefer"
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
        if conn:
            try: conn.rollback()
            except: pass
        print(f"DB error: {e}")
        raise
    finally:
        if conn:
            try: conn.close()
            except: pass

def init_db():
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
    except Exception as e:
        print(f"Init DB note: {e}")

init_db()

# --- 用户认证逻辑 ---
def hash_pw(password, salt=None):
    if salt is None: salt = secrets.token_hex(16)
    return hashlib.sha256((salt + password).encode()).hexdigest(), salt

def do_register(email, password, confirm):
    email = email.lower().strip()
    if not email or not password: return "❌ 请填写邮箱和密码"
    if "@" not in email:          return "❌ 邮箱格式不正确"
    if password != confirm:       return "❌ 两次密码不一致"
    if len(password) < 6:         return "❌ 密码至少6位"
    h, salt = hash_pw(password)
    try:
        db_exec("INSERT INTO users (email,password_hash,salt) VALUES (%s,%s,%s)", (email, h, salt))
        return "✅ 注册成功！请切换到登录标签登录"
    except Exception as e:
        if "UniqueViolation" in str(e) or "duplicate key" in str(e).lower():
            return "❌ 该邮箱已注册"
        return f"❌ 错误：{e}"

def do_login(email, password):
    email = email.lower().strip()
    if not email or not password:
        return None, None, "❌ 请输入邮箱和密码"
    try:
        row = db_exec("SELECT email,password_hash,salt FROM users WHERE email=%s", (email,), fetch="one")
        if not row: return None, None, "❌ 邮箱或密码错误"
        db_email, db_hash, salt = row
        h, _ = hash_pw(password, salt or "")
        if h == db_hash: return db_email, db_email.split("@")[0], None
    except:
        return None, None, "❌ 数据库连接失败"
    return None, None, "❌ 邮箱或密码错误"

# --- 历史记录逻辑（优化：防止嵌套死循环） ---
def save_conversation(email, q, a):
    try: db_exec("INSERT INTO conversations (email,question,answer) VALUES (%s,%s,%s)", (email, q, a))
    except Exception as e: print(f"Save error: {e}")

def load_history_chat(email):
    """
    专门为 Gradio Chatbot 组件格式化的历史记录
    """
    if not email: return []
    try:
        # 限制数量，避免数据量过大导致解析变慢
        rows = db_exec("SELECT question,answer FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 20", (email,), fetch="all") or []
        result = []
        for q, a in reversed(rows):
            result.append({"role": "user", "content": str(q)})
            result.append({"role": "assistant", "content": str(a)})
        return result
    except Exception as e: 
        print(f"Load error: {e}")
        return []

def delete_last_conversation(email):
    try: db_exec("DELETE FROM conversations WHERE id=(SELECT id FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 1)", (email,))
    except Exception as e: print(f"Delete error: {e}")

def clear_all_history(email):
    try: db_exec("DELETE FROM conversations WHERE email=%s", (email,))
    except Exception as e: print(f"Clear error: {e}")

# --- AI 与搜索逻辑 ---
client = OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY","sk-3b1488b14e6349a2b3d366c23814a053"), base_url="https://api.deepseek.com/v1")

def web_search(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results: return ""
        return "\n\n【搜索结果】\n" + "\n\n".join([f"来源：{r['title']}\n{r['body']}" for r in results])
    except: return ""

def ask(message, history, deep_think, use_search, nickname):
    model = "deepseek-reasoner" if deep_think else "deepseek-chat"
    search_ctx = web_search(message) if use_search else ""
    
    # 获取提问次数
    user_msgs_count = len([m for m in history if m["role"]=="user"])
    level = "这是第一次提问，请友好介绍自己。" if user_msgs_count == 0 else "请耐心详细解释。"
    
    name_str = f"同学叫【{nickname}】，请称呼他/她。" if nickname else ""
    sys_prompt = f"你叫pig，是专业的大学数学辅导老师。{name_str}{level}\n使用 LaTeX 渲染公式。步骤清晰、先思路后计算、最后总结、态度亲切。"
    if search_ctx: sys_prompt += f"\n\n参考搜索结果：{search_ctx}"
    
    msgs = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": message}]
    
    resp = client.chat.completions.create(model=model, messages=msgs, max_tokens=4000, temperature=0.3)
    return resp.choices[0].message.content

def respond(message, chat_history, deep, search, current_user, nickname):
    if not message or not message.strip():
        return "", chat_history
    
    # 确保 chat_history 是列表且不包含破坏性嵌套
    if not isinstance(chat_history, list): chat_history = []
    
    try:
        answer = ask(message, chat_history, deep, search, nickname)
        if current_user: 
            save_conversation(current_user, message, answer)
    except Exception as e:
        answer = f"⚠️ 请求失败：{str(e)}"
    
    chat_history.append({"role": "user", "content": message})
    chat_history.append({"role": "assistant", "content": answer})
    return "", chat_history

# --- CSS 与 UI 部分 (保持你的原样) ---
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

def make_update_js(email):
    items = []
    if email:
        try:
            rows = db_exec("SELECT question FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 50", (email,), fetch="all") or []
            items = [[r[0], ""] for r in rows]
        except: pass
    data = json.dumps(items, ensure_ascii=False)
    return f'<script>window._pigData={data}; if(window.pigRender) pigRender();</script>'

# --- Gradio 应用构建 ---
with gr.Blocks(theme=gr.themes.Base(), title="pig", css=CSS) as demo:
    logged_in_user = gr.State(None)
    logged_in_nick = gr.State(None)

    with gr.Column(elem_id="auth-box", visible=True) as auth_page:
        gr.HTML('<div style="text-align:center;margin-bottom:24px;"><div style="width:52px;height:52px;background:#cc6a45;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;font-size:24px;">📐</div><h2 style="font-size:22px;font-weight:600;margin-top:12px;">pig</h2><p style="color:#888;font-size:13px;">你的数学辅导老师</p></div>')
        with gr.Tabs() as tabs:
            with gr.Tab("登录"):
                login_email = gr.Textbox(placeholder="邮箱", show_label=False)
                login_pass  = gr.Textbox(placeholder="密码", show_label=False, type="password")
                login_btn   = gr.Button("登录", elem_id="auth-submit", variant="primary")
                login_msg   = gr.HTML(elem_id="auth-msg")
            with gr.Tab("注册"):
                reg_email   = gr.Textbox(placeholder="邮箱", show_label=False)
                reg_pass    = gr.Textbox(placeholder="密码", show_label=False, type="password")
                reg_confirm = gr.Textbox(placeholder="确认密码", show_label=False, type="password")
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
                    msg  = gr.Textbox(placeholder="输入数学问题...", show_label=False, scale=5, lines=1, elem_id="msg-input")
                    send = gr.Button("↑", variant="primary", scale=0, elem_id="send-btn")

    # 事件逻辑
    def handle_login(email, password):
        db_email, nickname, error = do_login(email, password)
        if db_email:
            return (gr.update(visible=False), gr.update(visible=True), db_email, nickname, "", load_history_chat(db_email), make_update_js(db_email))
        return (gr.update(visible=True), gr.update(visible=False), None, None, f'<p style="color:red">{error}</p>', [], "")

    def handle_logout():
        return gr.update(visible=True), gr.update(visible=False), None, None, [], ""

    login_btn.click(handle_login, [login_email, login_pass], [auth_page, chat_page, logged_in_user, logged_in_nick, login_msg, chatbot, data_updater])
    reg_btn.click(handle_register, [reg_email, reg_pass, reg_confirm], [reg_msg, tabs])
    
    _plo.click(handle_logout, [], [auth_page, chat_page, logged_in_user, logged_in_nick, chatbot, data_updater])
    _pcc.click(lambda: [], [], [chatbot])
    _pdel.click(lambda u: (load_history_chat(u), make_update_js(u)), [logged_in_user], [chatbot, data_updater])
    _pclr.click(lambda u: ([], make_update_js(u)), [logged_in_user], [chatbot, data_updater])

    send.click(respond, [msg, chatbot, deep_think, use_search, logged_in_user, logged_in_nick], [msg, chatbot])
    msg.submit(respond, [msg, chatbot, deep_think, use_search, logged_in_user, logged_in_nick], [msg, chatbot])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
