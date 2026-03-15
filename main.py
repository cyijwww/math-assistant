import os
import json
import hashlib
import secrets
import gradio as gr
from openai import OpenAI
from duckduckgo_search import DDGS
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "")

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
        db_exec("ALTER TABLE users ADD COLUMN IF NOT EXISTS salt TEXT NOT NULL DEFAULT ''")
    except Exception as e:
        print(f"Init DB note: {e}")

init_db()

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
    except psycopg2.errors.UniqueViolation:
        return "❌ 该邮箱已注册"
    except Exception as e:
        return f"❌ 错误：{e}"

def do_login(email, password):
    email = email.lower().strip()
    if not email or not password:
        return None, None, "❌ 请输入邮箱和密码"
    try:
        row = db_exec("SELECT email,password_hash,salt FROM users WHERE email=%s", (email,), fetch="one")
    except:
        return None, None, "❌ 数据库连接失败"
    if not row: return None, None, "❌ 邮箱或密码错误"
    db_email, db_hash, salt = row
    h, _ = hash_pw(password, salt or "")
    if h == db_hash: return db_email, db_email.split("@")[0], None
    return None, None, "❌ 邮箱或密码错误"

def save_conversation(email, q, a):
    try: db_exec("INSERT INTO conversations (email,question,answer) VALUES (%s,%s,%s)", (email, q, a))
    except Exception as e: print(f"Save error: {e}")

def load_history(email):
    try:
        rows = db_exec("SELECT question,answer FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 50", (email,), fetch="all") or []
        return [(q, a) for q, a in reversed(rows)]
    except: return []

def load_history_with_meta(email):
    try:
        rows = db_exec("SELECT question,answer,created_at FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 50", (email,), fetch="all") or []
        return [(f"[{t.strftime('%Y-%m-%d %H:%M') if t else ''}] {q}", a) for q, a, t in rows]
    except: return []

def delete_last_conversation(email):
    try: db_exec("DELETE FROM conversations WHERE id=(SELECT id FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 1)", (email,))
    except Exception as e: print(f"Delete error: {e}")

def clear_all_history(email):
    try: db_exec("DELETE FROM conversations WHERE email=%s", (email,))
    except Exception as e: print(f"Clear error: {e}")

client = OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY","sk-3b1488b14e6349a2b3d366c23814a053"), base_url="https://api.deepseek.com/v1")

def web_search(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results: return ""
        return "\n\n【搜索结果】\n" + "\n\n".join([f"来源：{r['title']}\n{r['body']}" for r in results])
    except: return ""

def fix_latex(text):
    for s in ["\\(","\\)","\\[","\\]","$$","$"]: text = text.replace(s, "")
    return text

def ask(message, history, deep_think, use_search, nickname):
    model = "deepseek-reasoner" if deep_think else "deepseek-chat"
    search_ctx = web_search(message) if use_search else ""
    n = len(history)
    level = "这是第一次提问，请友好介绍自己。" if n==0 else ("请耐心详细解释。" if n<5 else "可以适当加深难度。")
    name_str = f"同学叫【{nickname}】，请称呼他/她。" if nickname else ""
    sys = f"你叫pig，是专业的大学数学辅导老师。{name_str}{level}\n步骤清晰、先思路后计算、最后总结、态度亲切。"
    if search_ctx: sys += f"\n\n参考搜索结果：{search_ctx}"
    msgs = [{"role":"system","content":sys}]
    for item in history:
        if isinstance(item, tuple):
            msgs.append({"role":"user","content":item[0]})
            if item[1]: msgs.append({"role":"assistant","content":item[1]})
    msgs.append({"role":"user","content":message})
    resp = client.chat.completions.create(model=model, messages=msgs, max_tokens=4000, temperature=0.3)
    return fix_latex(resp.choices[0].message.content)

def make_sidebar_js(email):
    items = load_history_with_meta(email) if email else []
    data  = json.dumps(items, ensure_ascii=False)
    uid   = secrets.token_hex(4)
    return f'<span id="sb-{uid}" style="display:none" data-pig-update="1"></span><script>window._pigData={data};if(window._pigRender)window._pigRender();</script>'

def respond(message, chat_history, deep, search, current_user, nickname):
    if not message.strip():
        return "", chat_history, make_sidebar_js(current_user)
    try:
        answer = ask(message, chat_history, deep, search, nickname)
        if current_user: save_conversation(current_user, message, answer)
    except Exception as e:
        answer = f"⚠️ 请求失败：{str(e)}"
    chat_history.append((message, answer))
    return "", chat_history, make_sidebar_js(current_user)

CSS = """
* { box-sizing:border-box; margin:0; padding:0; }
body, .gradio-container { background:#f7f7f5 !important; font-family:Georgia,serif !important; max-width:100% !important; }
footer, .built-with { display:none !important; }

/* 登录页 */
#auth-box { max-width:400px; margin:60px auto; background:#fff; border-radius:20px; padding:36px 32px; box-shadow:0 4px 24px rgba(0,0,0,.08); }
#auth-submit { background:#cc6a45 !important; border-radius:10px !important; color:white !important; font-size:15px !important; width:100% !important; }
#auth-msg { text-align:center; font-size:14px; margin-top:8px; }

/* 聊天区 */
#chatbot { background:transparent !important; border:none !important; padding:8px !important; }
#chatbot > div { max-height:55vh !important; overflow-y:auto !important; }

/* 输入区固定底部 */
.input-area { position:fixed !important; bottom:0 !important; left:0 !important; right:0 !important;
    background:#f7f7f5 !important; border-top:1px solid #e5e5e0 !important;
    padding:8px 12px 24px !important; z-index:500 !important; }
.input-inner { background:#fff; border:1.5px solid #ddddd8; border-radius:18px; padding:10px 12px 8px; box-shadow:0 2px 10px rgba(0,0,0,.07); }
#deep-check { font-size:12px !important; color:#888 !important; margin-bottom:4px !important; }
#deep-check label { color:#888 !important; font-size:12px !important; }
#msg-input textarea { background:transparent !important; border:none !important; outline:none !important; font-size:15px !important; resize:none !important; font-family:inherit !important; line-height:1.5 !important; padding:0 !important; }
#msg-input .wrap { border:none !important; box-shadow:none !important; background:transparent !important; padding:0 !important; }
#msg-input { border:none !important; flex:1 !important; }
#send-btn { background:#cc6a45 !important; border:none !important; border-radius:10px !important; width:36px !important; height:36px !important; min-width:36px !important; padding:0 !important; cursor:pointer !important; color:white !important; font-size:20px !important; }

/* 底部留白避免被输入框遮住 */
#chatbot-wrap { padding-bottom:160px !important; }

.welcome-wrap { text-align:center; padding:20px 16px; }
#pig-topbar { background:#f7f7f5 !important; border-bottom:1px solid #e5e5e0 !important; padding:6px 8px !important; position:sticky !important; top:0 !important; z-index:100 !important; align-items:center !important; }
#pig-topbar button { min-width:36px !important; height:32px !important; padding:0 8px !important; }
#menu-btn { font-size:18px !important; }

/* 侧边栏 */
#pig-toggle { display:none; }
#pig-sidebar { position:fixed; top:0; left:0; width:300px; max-width:85vw; height:100vh;
    background:#fff; z-index:1001; transform:translateX(-100%);
    transition:transform .3s ease; display:flex; flex-direction:column;
    box-shadow:4px 0 20px rgba(0,0,0,.15); }
#pig-overlay { display:none; position:fixed; top:0; left:0; width:100vw; height:100vh;
    background:rgba(0,0,0,.35); z-index:1000; }
#pig-toggle:checked ~ * #pig-sidebar,
#pig-sidebar.open { transform:translateX(0) !important; }
#pig-toggle:checked ~ * #pig-overlay,
#pig-overlay.open { display:block !important; }
"""

SIDEBAR_HTML = """
<input type="checkbox" id="pig-toggle">
<div id="pig-overlay" onclick="this.classList.remove('open');document.getElementById('pig-sidebar').classList.remove('open');"></div>
<div id="pig-sidebar">
  <div style="padding:16px;border-bottom:1px solid #e5e5e0;display:flex;align-items:center;justify-content:space-between;">
    <span style="font-size:15px;font-weight:600;color:#1a1a1a;">📋 历史提问</span>
    <button id="pig-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#888;padding:4px 8px;">✕</button>
  </div>
  <div style="padding:10px 12px;display:flex;gap:8px;border-bottom:1px solid #e5e5e0;">
    <button id="pig-del-btn" style="flex:1;padding:7px;border-radius:8px;border:1px solid #ddd;font-size:12px;cursor:pointer;background:#fff;">🗑 删除最近一条</button>
    <button id="pig-clear-btn" style="flex:1;padding:7px;border-radius:8px;border:1px solid #e88;font-size:12px;cursor:pointer;background:#fff;color:#c44;">⚠️ 清空全部</button>
  </div>
  <div id="pig-status" style="padding:8px 16px;font-size:12px;color:#cc6a45;min-height:24px;"></div>
  <div id="pig-list" style="flex:1;overflow-y:auto;padding:8px 0;"></div>
</div>
<script>
window._pigData = [];
window._pigRender = function() {
    var list = document.getElementById('pig-list');
    if (!list) return;
    var items = window._pigData || [];
    if (!items.length) {
        list.innerHTML = '<div style="padding:24px;text-align:center;color:#aaa;font-size:13px;">暂无历史记录</div>';
        return;
    }
    list.innerHTML = items.map(function(item) {
        var m = item[0].match(/^\x5B(.+?)\x5D (.+)$/);
        var time = m ? m[1] : '';
        var q = m ? m[2] : item[0];
        return '<div style="padding:12px 16px;border-bottom:1px solid #f0f0ee;">'
            + '<div style="font-size:11px;color:#aaa;margin-bottom:4px;">' + time + '</div>'
            + '<div style="font-size:13px;color:#1a1a1a;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + q + '</div>'
            + '</div>';
    }).join('');
};
function pigOpen() {
    window._pigRender();
    document.getElementById('pig-sidebar').classList.add('open');
    document.getElementById('pig-overlay').classList.add('open');
}
function pigClose() {
    document.getElementById('pig-sidebar').classList.remove('open');
    document.getElementById('pig-overlay').classList.remove('open');
}
function pigStatus(msg) {
    var el = document.getElementById('pig-status');
    if (el) { el.innerText = msg; setTimeout(function(){ el.innerText=''; }, 2000); }
}
document.addEventListener('click', function(e) {
    var id = e.target && e.target.id;
    if (id === 'pig-close') { pigClose(); }
    if (id === 'pig-del-btn') {
        var btns = document.querySelectorAll('button');
        for (var i=0; i<btns.length; i++) {
            if (btns[i].id === 'del-trigger-btn') { btns[i].click(); pigStatus('✅ 已删除'); break; }
        }
    }
    if (id === 'pig-clear-btn') {
        if (!confirm('确定清空全部历史记录？')) return;
        var btns = document.querySelectorAll('button');
        for (var i=0; i<btns.length; i++) {
            if (btns[i].id === 'clear-trigger-btn') { btns[i].click(); pigStatus('✅ 已清空'); break; }
        }
    }
    if (id === 'pig-menu') { pigOpen(); }
});
new MutationObserver(function(muts) {
    muts.forEach(function(m) {
        m.addedNodes.forEach(function(n) {
            if (n.dataset && n.dataset.pigUpdate && window._pigData) window._pigRender();
        });
    });
}).observe(document.body, { childList:true, subtree:true });
</script>
"""

with gr.Blocks(theme=gr.themes.Base(), title="pig", css=CSS) as demo:

    logged_in_user = gr.State(None)
    logged_in_nick = gr.State(None)

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

    with gr.Column(visible=False) as chat_page:
        gr.HTML(SIDEBAR_HTML)
        with gr.Row(elem_id="pig-topbar"):
            menu_btn      = gr.Button("☰",    variant="secondary", scale=0, size="sm", elem_id="menu-btn")
            gr.HTML("<span style='flex:1;text-align:center;font-size:15px;font-weight:600;color:#1a1a1a;line-height:36px;'>📐 pig</span>")
            clear_chat_btn2 = gr.Button("🗑",  variant="secondary", scale=0, size="sm")
            logout_btn2   = gr.Button("退出",  variant="secondary", scale=0, size="sm")



        logout_btn      = gr.Button("退出登录", visible=False)
        delete_last_btn = gr.Button("del",   visible=False, elem_id="del-trigger-btn")

        clear_all_btn   = gr.Button("clear", visible=False, elem_id="clear-trigger-btn")
        sidebar_updater = gr.HTML("")

        with gr.Column(elem_id="chatbot-wrap"):
            gr.HTML("""
            <div class="welcome-wrap">
              <div style="width:56px;height:56px;background:#cc6a45;border-radius:16px;
                          display:flex;align-items:center;justify-content:center;
                          font-size:26px;margin:0 auto 16px;">📐</div>
              <h1 style="font-size:24px;font-weight:600;color:#1a1a1a;margin:0 0 8px;">你好，我是pig</h1>
              <p style="font-size:14px;color:#777;margin:0;line-height:1.7;">
                你的专属大学数学辅导老师<br>微积分 · 线性代数 · 概率论 · 离散数学
              </p>
            </div>""")
            chatbot = gr.Chatbot(elem_id="chatbot", show_label=False, height=400)

        with gr.Column(elem_classes="input-area"):
            deep_think = gr.Checkbox(label="🧠 深度思考（DeepSeek-R1）", value=False, elem_id="deep-check")
            use_search = gr.Checkbox(label="🔍 智能搜索", value=False, elem_id="deep-check")
            with gr.Column(elem_classes="input-inner"):
                with gr.Row():
                    msg  = gr.Textbox(placeholder="向pig提问任何数学问题...", show_label=False, scale=5, lines=1, max_lines=6, elem_id="msg-input")
                    send = gr.Button("↑", variant="primary", scale=0, elem_id="send-btn")

    def handle_login(email, password):
        db_email, nickname, error = do_login(email, password)
        if db_email:
            return (gr.update(visible=False), gr.update(visible=True),
                    db_email, nickname, "", load_history(db_email), make_sidebar_js(db_email))
        return (gr.update(visible=True), gr.update(visible=False),
                None, None, f'<p style="color:red">{error}</p>', [], "")

    def handle_register(email, password, confirm):
        result = do_register(email, password, confirm)
        color  = "green" if "✅" in result else "red"
        return f'<p style="color:{color}">{result}</p>', (gr.update(selected=0) if "✅" in result else gr.update())

    def handle_logout():
        return gr.update(visible=True), gr.update(visible=False), None, None, [], make_sidebar_js(None)

    def do_delete_last(email):
        if email: delete_last_conversation(email)
        return load_history(email) if email else [], make_sidebar_js(email)

    def do_clear_all(email):
        if email: clear_all_history(email)
        return [], make_sidebar_js(email)

    login_outputs = [auth_page, chat_page, logged_in_user, logged_in_nick, login_msg, chatbot, sidebar_updater]
    login_btn.click(handle_login,    [login_email, login_pass], login_outputs)
    login_email.submit(handle_login, [login_email, login_pass], login_outputs)
    reg_btn.click(handle_register,   [reg_email, reg_pass, reg_confirm], [reg_msg, tabs])

    send.click(respond, [msg, chatbot, deep_think, use_search, logged_in_user, logged_in_nick],
               [msg, chatbot, sidebar_updater])
    msg.submit(respond, [msg, chatbot, deep_think, use_search, logged_in_user, logged_in_nick],
               [msg, chatbot, sidebar_updater])

    delete_last_btn.click(do_delete_last, [logged_in_user], [chatbot, sidebar_updater])
    clear_all_btn.click(do_clear_all,     [logged_in_user], [chatbot, sidebar_updater])
    clear_chat_btn2.click(lambda: [], [], [chatbot])
    logout_btn2.click(handle_logout, [], [auth_page, chat_page, logged_in_user, logged_in_nick, chatbot, sidebar_updater])
    menu_btn.click(None, [], [], js="pigOpen()")

port = int(os.environ.get("PORT", 7860))
demo.launch(server_name="0.0.0.0", server_port=port)
