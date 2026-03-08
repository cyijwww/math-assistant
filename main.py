import sys
import io
import os

# 1. 彻底解决编码问题
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ["PYTHONUTF8"] = "1"

import gradio as gr
from openai import OpenAI

# 2. 初始化客户端
client = OpenAI(
    api_key="sk-wdbozclgazsabsitnvnoilptbzobxxsataxnxfqgdloehity",  # 建议检查Key前后是否有空格
    base_url="https://api.siliconflow.cn/v1"
)


def predict(message, history):
    # 将 history 转换为 OpenAI 需要的格式
    messages = [{"role": "system", "content": "你是一位专业的大学数学辅导老师，擅长解答微积分、线性代数、概率论等问题。"}]

    # 修正 history 的读取逻辑
    for h in history:
        messages.append({"role": "user", "content": h[0]})
        messages.append({"role": "assistant", "content": h[1]})

    messages.append({"role": "user", "content": message})

    try:
        response = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=messages,
            max_tokens=700,
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"发生错误: {str(e)}"


# 3. 构建界面
with gr.Blocks(theme=gr.themes.Soft(), title="大学数学助手", css="* {max-width: 100% !important}") as demo:
    gr.Markdown("# 🧮 大学数学专属学习助手")
    chatbot = gr.Chatbot(label="对话历史")
    msg = gr.Textbox(placeholder="输入数学问题并回车...", label="输入框")
    clear = gr.Button("🗑️ 清空对话")


    def user(user_message, history):
        return "", history + [[user_message, None]]


    def bot(history):
        user_message = history[-1][0]
        # 调用 AI
        bot_message = predict(user_message, history[:-1])
        history[-1][1] = bot_message
        return history


    # 提交逻辑：先更新用户消息，再生成机器人回复
    msg.submit(user, [msg, chatbot], [msg, chatbot], queue=False).then(
        bot, chatbot, chatbot
    )
    clear.click(lambda: None, None, chatbot, queue=False)

# 4. 启动服务
if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)