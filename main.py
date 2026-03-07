import torch
import gradio as gr
from openai import OpenAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from math_prompts import MATH_PROMPTS

# ===== API 客户端 =====
client = OpenAI(
    api_key="sk-wdbozclgazsabsitnvnoilptbzobxxsataxnxfqgdloehity",
    base_url="https://api.siliconflow.cn/v1"
)

# ===== 加载向量库 =====
print("📚 加载数学知识库...")
from langchain_community.embeddings import FakeEmbeddings
embeddings = FakeEmbeddings(size=768)
vectordb = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)
retriever = vectordb.as_retriever(search_kwargs={"k": 4})
print("✅ 加载完成！")

# ===== 问答函数 =====
def ask(user_input, history, mode):
    docs = retriever.invoke(user_input)
    context = "\n\n".join([
        f"[{doc.metadata.get('title','资料')}]\n{doc.page_content}"
        for doc in docs
    ])
    sources = list(set([doc.metadata.get("title", "未知") for doc in docs]))
    system_content = MATH_PROMPTS[mode].format(context=context)
    messages = [{"role": "system", "content": system_content}]
    for item in history[-4:]:
        content = item["content"]
        if isinstance(content, list):
            content = " ".join([c.get("text","") if isinstance(c,dict) else str(c) for c in content])
        messages.append({"role": item["role"], "content": str(content)})
    messages.append({"role": "user", "content": user_input})
    response = client.chat.completions.create(
        model="Qwen/Qwen2.5-7B-Instruct",
        messages=messages,
        max_tokens=700,
        temperature=0.3
    )
    answer = response.choices[0].message.content
    return f"{answer}\n\n---\n📎 来源：{'、'.join(sources[:3])}"

# ===== 界面 =====
with gr.Blocks(theme=gr.themes.Soft(), title="大学数学助手") as demo:
    gr.Markdown("# 🧮 大学数学专属学习助手")
    with gr.Row():
        mode = gr.Radio(
            choices=["概念解释", "例题解析", "出题考核", "知识梳理"],
            value="概念解释",
            label="📌 学习模式"
        )
    chatbot = gr.Chatbot(height=500)
    with gr.Row():
        msg = gr.Textbox(placeholder="输入你的问题...", label="输入", scale=5)
        send = gr.Button("发送 🚀", variant="primary", scale=1)
    clear = gr.Button("🗑️ 清空对话")

    def respond(message, chat_history, selected_mode):
        if not message.strip():
            return "", chat_history
        answer = ask(message, chat_history, selected_mode)
        chat_history.append({"role": "user", "content": message})
        chat_history.append({"role": "assistant", "content": answer})
        return "", chat_history

    send.click(respond, [msg, chatbot, mode], [msg, chatbot])
    msg.submit(respond, [msg, chatbot, mode], [msg, chatbot])
    clear.click(lambda: [], None, chatbot)

demo.launch(server_name="0.0.0.0", server_port=7860, share=False)