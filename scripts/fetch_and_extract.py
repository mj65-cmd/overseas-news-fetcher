import feedparser, requests, json, os, re, time, sys
from pathlib import Path

BASE = Path(__file__).parent.parent
SOURCES_PATH = BASE / "config" / "sources.json"
BLACKLIST_PATH = BASE / "config" / "blacklist.txt"
PROMPT_PATH = BASE / "config" / "prompt.txt"
OUTPUT_FOLDER = BASE / "output" / "articles"
OUTPUT_FOLDER.mkdir(exist_ok=True, parents=True)
PROCESSED_FILE = OUTPUT_FOLDER / "processed.txt"

# ========== 每天抓取数量控制 ==========
MAX_ARTICLES = 5
# ======================================

GROQ_KEY = os.environ.get("GROQ_API_KEY", "").strip()
JINA_KEY = os.environ.get("JINA_API_KEY", "")

if not GROQ_KEY:
    print("FATAL: GROQ_API_KEY is empty. Please set it in repository Secrets.")
    sys.exit(1)

with open(SOURCES_PATH, "r", encoding="utf-8") as f:
    sources = json.load(f)
with open(BLACKLIST_PATH, "r", encoding="utf-8") as f:
    blacklist = [line.strip().lower() for line in f if line.strip()]
with open(PROMPT_PATH, "r", encoding="utf-8") as f:
    extract_prompt = f.read()

processed = set()
if PROCESSED_FILE.exists():
    with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
        processed = set(f.read().splitlines())

def llm_extract(full_text):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": extract_prompt},
            {"role": "user", "content": f"原文:\n{full_text[:30000]}"}
        ]
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=180)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    Groq API error: {e}")
        if hasattr(resp := None, 'text') and resp:
            print(f"    Response: {resp.text[:500]}")
        return None

def get_full_article(url):
    jina_url = f"https://r.jina.ai/{url}"
    headers = {}
    if JINA_KEY:
        headers["Authorization"] = f"Bearer {JINA_KEY}"
    try:
        res = requests.get(jina_url, headers=headers, timeout=120)
        res.raise_for_status()
        return res.text
    except Exception as e:
        print(f"    Jina fetch error: {e}")
        return None

def is_blacklisted(text):
    low = text.lower()
    return any(bad_word in low for bad_word in blacklist)

# 主程序
print("=" * 50)
print(f"开始抓取新闻，目标数量：{MAX_ARTICLES} 条")
print("=" * 50)

all_results = []
article_count = 0

for category, rss_list in sources.items():
    if article_count >= MAX_ARTICLES:
        break
    for feed_url in rss_list:
        if article_count >= MAX_ARTICLES:
            break
        print(f"\n正在抓取 [{category}]：{feed_url}")
        try:
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                print(f"  警告：该RSS源没有返回任何条目")
                continue
            for entry in feed.entries[:10]:
                if article_count >= MAX_ARTICLES:
                    break
                link = entry.get("link", "")
                if not link or link in processed:
                    continue
                title = entry.get("title", "Untitled")
                if is_blacklisted(title):
                    print(f"  跳过(黑名单)：{title}")
                    processed.add(link)
                    continue
                print(f"  正在处理：{title}")
                try:
                    full_text = get_full_article(link)
                    if not full_text or len(full_text.strip()) < 100:
                        print(f"    跳过：正文为空或过短")
                        processed.add(link)
                        continue
                    extracted_content = llm_extract(full_text)
                    if not extracted_content:
                        print(f"    跳过：AI萃取失败")
                        processed.add(link)
                        continue
                    article_markdown = f"""# {title}
领域：{category}
原文链接：{link}

{extracted_content}
"""
                    all_results.append((title, article_markdown, link))
                    article_count += 1
                    print(f"  ✅ 完成第 {article_count}/{MAX_ARTICLES} 条")
                    time.sleep(2)
                except Exception as e:
                    print(f"  ❌ 处理失败：{e}")
                    processed.add(link)
                    continue
        except Exception as e:
            print(f"  ❌ RSS源读取失败：{e}")
            continue

# 保存稿件
for idx, (title, md, link) in enumerate(all_results):
    safe_name = re.sub(r'[^\w]','_',title)[:60] + ".md"
    out_file = OUTPUT_FOLDER / safe_name
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(md)
    processed.add(link)

with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
    for _,_,link in all_results:
        f.write(link + "\n")

print(f"\n{'=' * 50}")
print(f"全部完成！成功生成 {article_count} 篇新闻稿件。")
print(f"{'=' * 50}")
