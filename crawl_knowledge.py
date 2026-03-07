import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin, urlparse


# pip install requests beautifulsoup4 markdownify

def crawl_single_page(url):
    """抓取单个网页的正文内容"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        # 去除无用标签
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # 提取标题和正文
        title = soup.find("title")
        title = title.get_text(strip=True) if title else "未知标题"

        # 提取主体内容（优先找 article/main/content 区域）
        main = (soup.find("article") or
                soup.find("main") or
                soup.find(id="content") or
                soup.find(class_="content") or
                soup.find("body"))

        text = main.get_text(separator="\n", strip=True) if main else ""

        # 清理空行
        lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 10]
        clean_text = "\n".join(lines)

        return {"url": url, "title": title, "content": clean_text}

    except Exception as e:
        print(f"  ❌ 抓取失败 {url}: {e}")
        return None


def batch_crawl(url_list, save_path="./knowledge/web_data.json"):
    """批量抓取一组网址"""
    results = []
    for i, url in enumerate(url_list):
        print(f"[{i + 1}/{len(url_list)}] 抓取中: {url}")
        data = crawl_single_page(url)
        if data and len(data["content"]) > 100:
            results.append(data)
            print(f"  ✅ 成功，内容长度: {len(data['content'])} 字")
        time.sleep(1)  # 礼貌性延迟，别被封IP

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n🎉 共抓取 {len(results)} 个页面，保存至 {save_path}")
    return results


# ========== 在这里填入你要学习的网页地址 ==========
# 示例：高中数学、物理、历史等知识页面
MY_URLS = [
# ===== 用百度百科替代维基百科 =====
    "https://baike.baidu.com/item/极限/3742081",
    "https://baike.baidu.com/item/导数/579]7",
    "https://baike.baidu.com/item/积分/5749",
    "https://baike.baidu.com/item/泰勒级数/7519016",
    "https://baike.baidu.com/item/矩阵/18069",
    "https://baike.baidu.com/item/行列式/1843726",
    "https://baike.baidu.com/item/特征值/5880165",
    "https://baike.baidu.com/item/概率论/46476",
    "https://baike.baidu.com/item/随机变量/828980",
    "https://baike.baidu.com/item/正态分布/829892",

    # ===== 数学乐（中文数学教程）=====
    "https://www.shuxuele.com/calculus/limits.html",
    "https://www.shuxuele.com/calculus/derivatives-introduction.html",
    "https://www.shuxuele.com/calculus/integration-introduction.html",
    "https://www.shuxuele.com/algebra/matrix-introduction.html",
    "https://www.shuxuele.com/algebra/matrix-multiplying.html",

    "https://baike.baidu.com/item/...",   # 百度百科
    "https://www.runoob.com/...",          # 菜鸟教程
    # ===== 系统教程网站 =====
    "https://www.shuxuele.com/calculus/index.html",
    "https://www.shuxuele.com/algebra/matrix-introduction.html",
    # 可以加几十个，越多知识库越丰富
]

if __name__ == "__main__":
    import os

    os.makedirs("./knowledge", exist_ok=True)
    batch_crawl(MY_URLS)