import gradio as gr
from openai import OpenAI

client = OpenAI(
    api_key="你的Key",
    base_url="https://api.siliconflow.cn/v1"
)

def ask(message, history):
    messages = [{"role": "system", "content": "你是一位专业的大学数学辅导老师，擅长解答微积分、线性代数、概率论等问题。"}]
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

with gr.Blocks(theme=gr.themes.Soft(), title="大学数学助手") as demo:
    gr.Markdown("# 🧮 大学数学专属学习助手")
    chatbot = gr.Chatbot(height=500)
    msg = gr.Textbox(placeholder="输入数学问题...", label="输入")
    clear = gr.Button("🗑️ 清空对话")

    def respond(message, chat_history):
        if not message.strip():
            return "", chat_history
        answer = ask(message, chat_history)
        chat_history.append({"role": "user", "content": message})
        chat_history.append({"role": "assistant", "content": answer})
        return "", chat_history

    msg.submit(respond, [msg, chatbot], [msg, chatbot])
    clear.click(lambda: [], None, chatbot)

demo.launch(server_name="0.0.0.0", server_port=7860)