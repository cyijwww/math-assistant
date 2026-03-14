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

ADMIN_EMAIL = "abc13112629791@qq.com"

def load_all_conversations():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT email, question, answer, created_at FROM conversations ORDER BY created_at DESC LIMIT 200"
        )
        rows = cur.fetchall()
        conn.close()
        result = []
        for email, question, answer, created_at in rows:
            time_str = created_at.strftime("%m-%d %H:%M") if created_at else ""
            result.append((f"[{time_str}] {email}：{question}", answer))
        return result
    except Exception as e:
        print(f"Load all conversations error: {e}")
        return []

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

def load_history_with_meta(email):
    """返回带时间和id的历史，用于历史记录页面显示"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, question, answer, created_at FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 50",
            (email,)
        )
        rows = cur.fetchall()
        conn.close()
        result = []
        for rid, question, answer, created_at in rows:
            time_str = created_at.strftime("%Y-%m-%d %H:%M") if created_at else ""
            result.append((f"[{time_str}] {question}", answer))
        return result
    except Exception as e:
        print(f"Load history meta error: {e}")
        return []

def delete_last_conversation(email):
    """删除最近一条记录"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM conversations WHERE id = (SELECT id FROM conversations WHERE email=%s ORDER BY created_at DESC LIMIT 1)",
            (email,)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Delete error: {e}")
        return False

def clear_all_history(email):
    """清空该用户所有历史"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM conversations WHERE email=%s", (email,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Clear history error: {e}")
        return False

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

ADMIN_EMAIL = "abc13112629791@qq.com"

def load_all_conversations():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT email, question, answer, created_at FROM conversations ORDER BY created_at DESC LIMIT 200"
        )
        rows = cur.fetchall()
        conn.close()
        result = []
        for email, question, answer, created_at in rows:
            time_str = created_at.strftime("%m-%d %H:%M") if created_at else ""
            result.append((f"[{time_str}] {email}：{question}", answer))
        return result
    except Exception as e:
        print(f"Load all conversations error: {e}")
        return []

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
#chatbot { background: transparent !important; border: none !important; width: 100% !important; padding: 12px !important; flex: 1 !important; overflow-y: auto !important; }
.chat-wrap { display: flex !important; flex-direction: column !important; height: 100vh !important; overflow: hidden !important; }
.input-area { background: #f7f7f5 !important; border-top: 1px solid #e5e5e0 !important; padding: 10px 12px 20px !important; flex-shrink: 0 !important; }
.input-inner { background: #ffffff; border: 1.5px solid #ddddd8; border-radius: 18px; padding: 10px 12px 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.07); }
#deep-check { font-size: 12px !important; color: #888880 !important; margin-bottom: 6px !important; }
#deep-check label { color: #888880 !important; font-size: 12px !important; }
#msg-input textarea { background: transparent !important; border: none !important; outline: none !important; font-size: 15px !important; color: #1a1a1a !important; resize: none !important; font-family: inherit !important; line-height: 1.5 !important; padding: 0 !important; width: 100% !important; }
#msg-input textarea::placeholder { color: #b0b0a8 !important; }
#msg-input .wrap { border: none !important; box-shadow: none !important; background: transparent !important; padding: 0 !important; }
#msg-input { border: none !important; flex: 1 !important; }
#send-btn { background: #cc6a45 !important; border: none !important; border-radius: 10px !important; width: 36px !important; height: 36px !important; min-width: 36px !important; padding: 0 !important; cursor: pointer !important; color: white !important; font-size: 20px !important; line-height: 1 !important; }
.welcome-wrap { text-align: center; padding: 30px 16px 20px; max-width: 580px; margin: 0 auto; }
/* 侧边栏 */
#sidebar-overlay { display:none; position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(0,0,0,0.35); z-index:1000; }
#sidebar-overlay.open { display:block; }
#sidebar { position:fixed; top:0; left:0; width:300px; max-width:85vw; height:100vh; background:#fff; z-index:1001; transform:translateX(-100%); transition:transform 0.3s ease; display:flex; flex-direction:column; box-shadow:4px 0 20px rgba(0,0,0,0.15); }
#sidebar.open { transform:translateX(0); }
#sidebar-header { padding:16px; border-bottom:1px solid #e5e5e0; display:flex; align-items:center; justify-content:space-between; }
#sidebar-title { font-size:15px; font-weight:600; color:#1a1a1a; }
#sidebar-close { background:none; border:none; font-size:20px; cursor:pointer; color:#888; padding:4px 8px; }
#sidebar-actions { padding:10px 12px; display:flex; gap:8px; border-bottom:1px solid #e5e5e0; }
#sidebar-del-btn, #sidebar-clear-btn { flex:1; padding:7px; border-radius:8px; border:1px solid #ddd; font-size:12px; cursor:pointer; background:#fff; }
#sidebar-clear-btn { border-color:#e88; color:#c44; }
#sidebar-list { flex:1; overflow-y:auto; padding:8px 0; }
.sidebar-item { padding:12px 16px; border-bottom:1px solid #f0f0ee; cursor:pointer; }
.sidebar-item:hover { background:#f7f7f5; }
.sidebar-item-time { font-size:11px; color:#aaa; margin-bottom:4px; }
.sidebar-item-q { font-size:13px; color:#1a1a1a; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
#sidebar-status { padding:8px 16px; font-size:12px; color:#cc6a45; min-height:24px; }
"""

with gr.Blocks(theme=gr.themes.Base(), title="pig", css=CSS) as demo:

    logged_in_user = gr.State(None)

    with gr.Column(elem_id="auth-box", visible=True) as auth_page:
        gr.HTML("""
        <div style="text-align:center;margin-bottom:24px;">
            <div style="width:52px;height:52px;background:#cc6a45;border-radius:14px;
                        display:inline-flex;align-items:center;justify-content:center;font-size:24px;">📐</div>
            <h2 style="font-size:22px;font-weight:600;color:#1a1a1a;margin-top:12px;">pig</h2>
            <p style="color:#888;font-size:13px;margin-top:4px;">你的专属数学辅导老师</p>
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
        # 左滑侧边栏（纯HTML+JS实现）
        sidebar_html = gr.HTML("""
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
        function openSidebar(items) {
            window._pigHistoryData = items || [];
            renderSidebar();
            document.getElementById('sidebar').classList.add('open');
            document.getElementById('sidebar-overlay').classList.add('open');
        }
        function closeSidebar() {
            document.getElementById('sidebar').classList.remove('open');
            document.getElementById('sidebar-overlay').classList.remove('open');
        }
        function renderSidebar() {
            var list = document.getElementById('sidebar-list');
            var items = window._pigHistoryData;
            if (!items || items.length === 0) {
                list.innerHTML = '<div style="padding:24px;text-align:center;color:#aaa;font-size:13px;">暂无历史记录</div>';
                return;
            }
            list.innerHTML = items.map(function(item, i) {
                var parts = item[0].match(/^\x5B(.+?)\x5D (.+)$/);
                var time = parts ? parts[1] : '';
                var q = parts ? parts[2] : item[0];
                return '<div class="sidebar-item"><div class="sidebar-item-time">' + time + '</div><div class="sidebar-item-q">' + q + '</div></div>';
            }).join('');
        }
        function setStatus(msg) {
            document.getElementById('sidebar-status').innerText = msg;
            setTimeout(function(){ document.getElementById('sidebar-status').innerText = ''; }, 2000);
        }
        function deleteLastItem() {
            var btn = document.querySelector('#del-trigger-btn');
            if (btn) { btn.click(); setStatus('✅ 已删除最近一条'); }
        }
        function clearAllItems() {
            if (!confirm('确定清空全部历史记录？')) return;
            var btn = document.querySelector('#clear-trigger-btn');
            if (btn) { btn.click(); setStatus('✅ 已清空全部'); }
        }
        </script>
        """)

        # 顶部导航
        with gr.Row():
            gr.HTML("""
            <div style="display:flex;align-items:center;padding:10px 12px;border-bottom:1px solid #e5e5e0;background:#f7f7f5;width:100%;gap:10px;">
                <button onclick="if(window._pigOpenSidebar)window._pigOpenSidebar()" style="background:none;border:none;font-size:20px;cursor:pointer;padding:0 4px;">☰</button>
                <span style="font-size:15px;font-weight:600;color:#1a1a1a;flex:1;text-align:center;">📐 pig</span>
            </div>
            """)
        admin_btn = gr.Button("🔧 管理员后台", variant="secondary", visible=False, size="sm")

        # 隐藏触发按钮（侧边栏JS调用）
        history_btn = gr.Button("load_history", visible=False, elem_id="history-load-btn")
        delete_last_btn = gr.Button("del", visible=False, elem_id="del-trigger-btn")
        clear_all_btn = gr.Button("clear", visible=False, elem_id="clear-trigger-btn")
        history_data = gr.State([])

        # 聊天视图
        with gr.Column(visible=True, elem_classes="chat-wrap") as chat_view:
            gr.HTML("""
            <div class="welcome-wrap">
                <div style="width:56px;height:56px;background:#cc6a45;border-radius:16px;
                            display:flex;align-items:center;justify-content:center;
                            font-size:26px;margin:0 auto 20px;">📐</div>
                <h1 style="font-size:26px;font-weight:600;color:#1a1a1a;margin:0 0 10px;">你好，我是pig</h1>
                <p style="font-size:15px;color:#777770;margin:0;line-height:1.7;">
                    你的专属大学数学辅导老师<br>微积分 · 线性代数 · 概率论 · 离散数学
                </p>
            </div>
            """)
            chatbot = gr.Chatbot(elem_id="chatbot", show_label=False, height=600)
            with gr.Column(elem_classes="input-area"):
                deep_think = gr.Checkbox(label="🧠 深度思考（DeepSeek-R1）", value=False, elem_id="deep-check")
                use_search = gr.Checkbox(label="🔍 智能搜索", value=False, elem_id="deep-check")
                with gr.Column(elem_classes="input-inner"):
                    with gr.Row():
                        msg = gr.Textbox(placeholder="向pig提问任何数学问题...", show_label=False, scale=5, lines=1, max_lines=8, elem_id="msg-input")
                        send = gr.Button("↑", variant="primary", scale=0, elem_id="send-btn")

        # 管理员视图
        with gr.Column(visible=False) as admin_view:
            gr.HTML("""<div style='padding:16px;border-bottom:1px solid #e5e5e0;'>
                <h3 style='color:#cc6a45;margin:0;'>🔧 管理员后台</h3>
                <p style='color:#888;font-size:13px;margin:4px 0 0;'>所有学生提问记录</p>
            </div>""")
            back_admin_btn = gr.Button("← 返回聊天", variant="secondary")
            admin_display = gr.Chatbot(show_label=False, height=600)

        # JS桥接：把历史数据传给侧边栏
        sidebar_updater = gr.HTML("", visible=False)

    def handle_login(email, password):
        nickname, error = do_login(email, password)
        if nickname:
            clean_email = email.lower().strip()
            history = load_history(clean_email)
            is_admin = clean_email == ADMIN_EMAIL
            return gr.update(visible=False), gr.update(visible=True), clean_email, "", history, gr.update(visible=is_admin)
        else:
            return gr.update(visible=True), gr.update(visible=False), None, f'<p style="color:red">{error}</p>', [], gr.update(visible=False)

    def handle_register(email, password, confirm):
        result = do_register(email, password, confirm)
        color = "green" if "✅" in result else "red"
        msg_html = f'<p style="color:{color}">{result}</p>'
        if "✅" in result:
            return msg_html, gr.update(selected=0)
        else:
            return msg_html, gr.update()

    def load_sidebar_history(email):
        items = load_history_with_meta(email) if email else []
        # 把数据注入JS
        import json
        js = f"<script>window._pigHistoryData={json.dumps(items, ensure_ascii=False)};window._pigOpenSidebar=function(){{openSidebar(window._pigHistoryData)}};openSidebar(window._pigHistoryData);</script>"
        return items, js

    def do_delete_last(email):
        if not email:
            return [], "<script>setStatus('❌ 未登录')</script>"
        delete_last_conversation(email)
        items = load_history_with_meta(email)
        import json
        js = f"<script>window._pigHistoryData={json.dumps(items, ensure_ascii=False)};renderSidebar();</script>"
        return items, js

    def do_clear_all(email):
        if not email:
            return [], "<script>setStatus('❌ 未登录')</script>"
        clear_all_history(email)
        import json
        js = "<script>window._pigHistoryData=[];renderSidebar();</script>"
        return [], js

    def show_admin():
        records = load_all_conversations()
        return gr.update(visible=False), gr.update(visible=True), records

    def hide_admin():
        return gr.update(visible=True), gr.update(visible=False)

    login_btn.click(handle_login, [login_email, login_pass], [auth_page, chat_page, logged_in_user, login_msg, chatbot, admin_btn])
    login_email.submit(handle_login, [login_email, login_pass], [auth_page, chat_page, logged_in_user, login_msg, chatbot, admin_btn])
    reg_btn.click(handle_register, [reg_email, reg_pass, reg_confirm], [reg_msg, tabs])
    send.click(respond, [msg, chatbot, deep_think, use_search, logged_in_user], [msg, chatbot])
    msg.submit(respond, [msg, chatbot, deep_think, use_search, logged_in_user], [msg, chatbot])
    history_btn.click(load_sidebar_history, [logged_in_user], [history_data, sidebar_updater])
    delete_last_btn.click(do_delete_last, [logged_in_user], [history_data, sidebar_updater])
    clear_all_btn.click(do_clear_all, [logged_in_user], [history_data, sidebar_updater])
    admin_btn.click(show_admin, [], [chat_view, admin_view, admin_display])
    back_admin_btn.click(hide_admin, [], [chat_view, admin_view])

port = int(os.environ.get("PORT", 7860))
demo.launch(server_name="0.0.0.0", server_port=port)
