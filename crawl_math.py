import requests
import json
import time
import re
from bs4 import BeautifulSoup
MY_URLS = [
    # ===== 数学乐（最稳定）=====
    "https://www.shuxuele.com/calculus/limits.html",
    "https://www.shuxuele.com/calculus/derivatives-introduction.html",
    "https://www.shuxuele.com/calculus/integration-introduction.html",
    "https://www.shuxuele.com/calculus/integrals.html",
    "https://www.shuxuele.com/calculus/taylor-series.html",
    "https://www.shuxuele.com/algebra/matrix-introduction.html",
    "https://www.shuxuele.com/algebra/matrix-multiplying.html",
    "https://www.shuxuele.com/algebra/systems-linear-equations.html",
    "https://www.shuxuele.com/data/probability.html",
    "https://www.shuxuele.com/data/standard-normal-distribution.html",
    "https://www.shuxuele.com/data/random-variables.html",
    "https://www.shuxuele.com/calculus/partial-derivatives.html",
    "https://www.shuxuele.com/algebra/determinant.html",
    "https://www.shuxuele.com/algebra/eigenvalue.html",
    "https://www.shuxuele.com/calculus/chain-rule.html",
]

# pip install requests beautifulsoup4 latex2sympy2

def clean_math_text(text):
    """清理数学文本，保留公式可读性"""
    # 把常见数学符号替换成文字描述，方便模型理解
    replacements = {
        "∫": "积分",
        "∑": "求和",
        "∏": "连乘",
        "∂": "偏导",
        "∇": "梯度",
        "∞": "无穷大",
        "≈": "约等于",
        "≠": "不等于",
        "≤": "小于等于",
        "≥": "大于等于",
        "∈": "属于",
        "⊂": "包含于",
        "∪": "并集",
        "∩": "交集",
        "√": "根号",
        "α": "alpha",
        "β": "beta",
        "γ": "gamma",
        "λ": "lambda",
        "μ": "mu",
        "σ": "sigma",
        "θ": "theta",
        "π": "pi",
    }
    for symbol, word in replacements.items():
        text = text.replace(symbol, word)

    # 去除 LaTeX 标记但保留内容
    text = re.sub(r'\$\$(.+?)\$\$', r'公式：\1', text, flags=re.DOTALL)
    text = re.sub(r'\$(.+?)\$', r'\1', text)
    text = re.sub(r'\\[a-zA-Z]+\{(.+?)\}', r'\1', text)  # \frac{a}{b} → a/b

    # 清理多余空白
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 5]
    return "\n".join(lines)


def crawl_math_page(url):
    """专为数学页面优化的爬虫"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 去除干扰元素
        for tag in soup(["script", "style", "nav", "footer",
                         "header", "aside", ".sidebar", ".ad"]):
            tag.decompose()

        title = soup.find("title")
        title = title.get_text(strip=True).replace(" - 维基百科", "") if title else "未知"

        # Wikipedia 优先取 #mw-content-text
        main = (soup.find(id="mw-content-text") or
                soup.find("article") or
                soup.find("main") or
                soup.find("body"))

        raw_text = main.get_text(separator="\n") if main else ""
        clean_text = clean_math_text(raw_text)

        # 过滤太短的页面
        if len(clean_text) < 200:
            print(f"  ⚠️  内容太短，跳过：{url}")
            return None

        return {
            "url": url,
            "title": title,
            "content": clean_text,
            "length": len(clean_text)
        }

    except Exception as e:
        print(f"  ❌ 失败：{url} → {e}")
        return None


def batch_crawl_math(url_list, save_path="./knowledge/math_data.json"):
    import os
    os.makedirs("./knowledge", exist_ok=True)

    results = []
    for i, url in enumerate(url_list):
        print(f"[{i + 1}/{len(url_list)}] {url}")
        data = crawl_math_page(url)
        if data:
            results.append(data)
            print(f"  ✅ 《{data['title']}》 {data['length']} 字")
        time.sleep(1.5)

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n🎉 抓取完成！共 {len(results)} 页，保存至 {save_path}")

if __name__ == "__main__":
    import os
    os.makedirs("./knowledge", exist_ok=True)
    batch_crawl_math(MY_URLS)   # 直接用，不需要import
