import re
import gradio as gr
from openai import OpenAI

client = OpenAI(
    api_key="sk-wubb2clgazsabsitnvnoilptbzobxxsataxnxfqgdloehity",
    base_url="https://api.siliconflow.cn/v1"
)

def fix_latex(text):
    text = text.replace("\\(", "$").replace("\\)", "$")
    text = text.replace("\\[", "$$").replace("\\]", "$$")
    text = re.sub(r'\$\s*\n\s*\$', '$$', text)
    return text

def ask(message, history):
    messages = [{"role": "system", "content": """你叫小明，是一位专业的大学数学辅导老师。
回答要求：
1. 所有数学公式必须用$$...$$包裹
2. 解题步骤清晰，分步骤说明
3. 先给出思路，再一步一步计算
4. 最后给出总结答案
5. 态度亲切，像老师辅导学生"""}]
    for item in history:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": message})
    response = client.chat.completions.create(
        model="Qwen/Qwen2.5-7B-Instruct",
        messages=messages,
        max_tokens=1000,
        temperature=0.3
    )
    result = response.choices[0].message.content
    return fix_latex(result)

with gr.Blocks(
    theme=gr.themes.Soft(),
    title="小明数学助手",
    css="""
    body {margin: 0; padding: 0;}
    .gradio-container {max-width: 100% !important; margin: 0 !important; padding: 0 !important;}
    #chatbot {height: calc(100vh - 120px) !important; overflow-y: auto;}
    #chatbot .message {max-width: 100% !important; width: 100% !important;}
    #chatbot .bot {background: transparent !important; border: none !important; box-shadow: none !important; padding: 16px !important;}
    #chatbot .user {background: transparent !important; border: none !important; box-shadow: none !important;}
    #input-row {position: fixed; bottom: 0; width: 100%; background: white; padding: 8px; border-top: 1px solid #eee;}
    footer {display: none !important;}
    """
) as demo:
    gr.Markdown("## 📐 小明 - 你的专属数学助手")
    chatbot = gr.Chatbot(
        elem_id="chatbot",
        show_label=False,
        latex_delimiters=[
            {"left": "$$", "right": "$$", "display": True},
            {"left": "$", "right": "$", "display": False}
        ],
        height=600
    )
    with gr.Row(elem_id="input-row"):
        msg = gr.Textbox(
            placeholder="向小明提问数学问题...",
            show_label=False,
            scale=5,
            lines=2
        )
        send = gr.Button("发送 🚀", variant="primary", scale=1)
    clear = gr.Button("🗑️ 清空对话")

    def respond(message, chat_history):
        if not message.strip():
            return "", chat_history
        answer = ask(message, chat_history)
        chat_history.append({"role": "user", "content": message})
        chat_history.append({"role": "assistant", "content": answer})
        return "", chat_history

    send.click(respond, [msg, chatbot], [msg, chatbot])
    msg.submit(respond, [msg, chatbot], [msg, chatbot])
    clear.click(lambda: [], None, chatbot)

demo.launch(server_name="0.0.0.0", server_port=7860)