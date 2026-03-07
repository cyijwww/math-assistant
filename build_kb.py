import json # 确保 i 是小写
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma


def build_from_web_data(json_path="./knowledge/web_data.json"):
    # 1. 读取抓取的网页数据
    with open(json_path, "r", encoding="utf-8") as f:
        web_data = json.load(f)

    print(f"📂 共加载 {len(web_data)} 个网页")

    # 2. 转换为 Document 格式（保留来源信息）
    docs = []
    for item in web_data:
        doc = Document(
            page_content=item["content"],
            metadata={
                "source": item["url"],
                "title": item["title"]
            }
        )
        docs.append(doc)

    # 3. 切片（学科知识建议切小一点，更精准）
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=80,
        separators=["。", "；", "！", "？", "\n\n", "\n", " "]
    )
    chunks = splitter.split_documents(docs)
    print(f"✂️  切分为 {len(chunks)} 个知识片段")

    # 4. 向量化（中文嵌入模型，自动下载约400MB）
    print("🔄 向量化中，首次需要几分钟...")
    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-base-zh-v1.5",  # base版比small更准确
        model_kwargs={"device": "cpu"} ,  # 先用 CPU 跑通，虽然慢一点但不会报错
        encode_kwargs={"normalize_embeddings": True}
    )

    # 5. 存入本地向量数据库
    vectordb = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory="./chroma_db"
    )

    print(f"✅ 知识库构建完成！共 {vectordb._collection.count()} 条")


if __name__ == "__main__":
    build_from_web_data()