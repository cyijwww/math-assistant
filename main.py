import re
import gradio as gr
from openai import OpenAI

client = OpenAI(
    api_key="sk-wdbozclgazsabsitnvnoilptbzobxxsataxnxfqgdloehity",
    base_url="https://api.siliconflow.cn/v1"
)

def fix_latex(text):
    text = text.replace("\\(", "$").replace("\\)", "$")
    text = text.replace("\\[", "$$").replace("\\]", "$$")
    text = re.sub(r'\$\s*\n\s*\$', '$$', text)
    return text

def ask(message, history, deep_think):
    model = "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B" if deep_think else "Qwen/Qwen2.5-7B-Instruct"
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
        model=model,
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
    #chatbot {height: calc(100vh - 160px) !important; overflow-y: auto;}
    #chatbot .bot {background: transparent !important; border: none !important; box-shadow: none !important; padding: 16px !important;}
    #chatbot .user {background: transparent !important; border: none !important; box-shadow: none !important;}
    #input-row {position: fixed; bottom: 0; width: 100%; background: white; padding: 8px; border-top: 1px solid #eee;}
    #history-box {height: 400px; overflow-y: auto; border: 1px solid #eee; border-radius: 8px; padding: 8px;}
    footer {display: none !important;}
    """
) as demo:
    with gr.Tabs():
        with gr.Tab("💬 对话"):
            gr.Markdown("## 📐 小明 - 你的专属数学助手")
            chatbot = gr.Chatbot(
                elem_id="chatbot",
                show_label=False,
                latex_delimiters=[
                    {"left": "$$", "right": "$$", "display": True},
                    {"left": "$", "right": "$", "display": False}
                ],
                height=500
            )
            with gr.Row(elem_id="input-row"):
                deep_think = gr.Checkbox(label="🧠 深度思考", value=False)
                msg = gr.Textbox(
                    placeholder="向小明提问数学问题，按回车发送...",
                    show_label=False,
                    scale=6,
                    lines=2
                )

        with gr.Tab("📋 历史问题"):
            gr.Markdown("## 📋 学生提问记录")
            history_display = gr.Dataframe(
                headers=["序号", "问题"],
                datatype=["number", "str"],
                label="",
                elem_id="history-box",
                interactive=False
            )
            clear_history_btn = gr.Button("🗑️ 清空记录", variant="stop")

    question_log = gr.State([])

    def respond(message, chat_history, deep, log):
        if not message.strip():
            return "", chat_history, log, log_to_table(log)
        answer = ask(message, chat_history, deep)
        chat_history.append({"role": "user", "content": message})
        chat_history.append({"role": "assistant", "content": answer})
        log.append(message)
        return "", chat_history, log, log_to_table(log)

    def log_to_table(log):
        return [[i+1, q] for i, q in enumerate(log)]

    def clear_history(log):
        return [], []

    msg.submit(respond, [msg, chatbot, deep_think, question_log], [msg, chatbot, question_log, history_display])
    clear_history_btn.click(clear_history, [question_log], [question_log, history_display])

demo.launch(server_name="0.0.0.0", server_port=7860)