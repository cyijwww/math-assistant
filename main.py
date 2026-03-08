import gradio as gr
from openai import OpenAI

client = OpenAI(
    api_key="sk-wdbozclgazsabsitnvnoilptbzobxxsataxnxfqgdloehity",
    base_url="https://api.siliconflow.cn/v1"
)

def ask(message, history):
    messages = [{"role": "system", "content": "你叫小明，是一位专业的大学数学辅导老师，擅长解答微积分、线性代数、概率论等问题。所有数学公式必须用$$...$$包裹，例如：$$x^2+y^2=r^2$$，$$\\int_0^1 x^2 dx = \\frac{1}{3}$$。禁止使用\\(...\\)格式，只用$$...$$。请用清晰易懂的方式一步一步解答。"}]
    for item in history:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": message})
    response = client.chat.completions.create(
        model="Qwen/Qwen2.5-7B-Instruct",
        messages=messages,
        max_tokens=700,
        temperature=0.3
    )
    return response.choices[0].message.content

with gr.Blocks(
    theme=gr.themes.Soft(),
    title="小明",
    css="""
    body {margin: 0; padding: 0;}
    .gradio-container {max-width: 100% !important; margin: 0 !important; padding: 0 !important;}
    #chatbot {height: calc(100vh - 130px) !important; overflow-y: auto;}
    #input-row {position: fixed; bottom: 0; width: 100%; background: white; padding: 8px;}
    footer {display: none !important;}
    """
) as demo:
    gr.Markdown("## 📐 小明 ")
    chatbot = gr.Chatbot(
        elem_id="chatbot",
        show_label=False,
        latex_delimiters=[
            {"left": "$$", "right": "$$", "display": True},
            {"left": "$", "right": "$", "display": False}
        ]
    )
    with gr.Row(elem_id="input-row"):
        msg = gr.Textbox(placeholder="向小明提问...", show_label=False, scale=5)
        send = gr.Button("发送", variant="primary", scale=1)
    clear = gr.Button("清空对话")

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