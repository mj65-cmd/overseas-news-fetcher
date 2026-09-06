import feedparser, requests, json, os, re, time, sys
from pathlib import Path

BASE = Path(__file__).parent.parent
SOURCES_PATH = BASE / "config" / "sources.json"
BLACKLIST_PATH = BASE / "config" / "blacklist.txt"
PROMPT_PATH = BASE / "config" / "prompt.txt"
OUTPUT_FOLDER = BASE / "output" / "articles"
OUTPUT_FOLDER.mkdir(exist_ok=True, parents=True)
PROCESSED_FILE = OUTPUT_FOLDER / "processed.txt"

MAX_ARTICLES = 5

GROQ_KEY = os.environ.get("GROQ_API_KEY", "").strip()
JINA_KEY = os.environ.get("JINA_API_KEY", "")

if not GROQ_KEY:
    print("FATAL: GROQ_API_KEY is empty.")
    sys.exit(1)

# 按优先级排序的模型候选（从 Groq 可用列表中自动匹配）
MODEL_PRIORITY = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "groq/compound",
    "groq/compound-mini",
    "canopylabs/orpheus-v1-english",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "mixtral-8x7b-32768",
]
ACTIVE_MODEL = None

def detect_model():
    global ACTIVE_MODEL
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            timeout=30
        )
        if resp.status_code == 200:
            available = [m["id"] for m in resp.json().get("data", [])]
            print(f"Groq available models ({len(available)}):")
            for m in available:
                print(f"  - {m}")
            # 按优先级匹配
            for candidate in MODEL_PRIORITY:
                if candidate in available:
                    ACTIVE_MODEL = candidate
                    print(f"\nSelected model: {ACTIVE_MODEL}")
                    return
            # 都没匹配到，选第一个非 guard/safeguard 的通用模型
            for m in available:
                low = m.lower()
                if "guard" not in low and "safeguard" not in low and "prompt-guard" not in low and "arabic" not in low and "saudi" not in low:
                    ACTIVE_MODEL = m
                    print(f"\nFallback selected model: {ACTIVE_MODEL}")
                    return
        else:
            print(f"Model list query failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"Model detection error: {e}")
    if not ACTIVE_MODEL:
        ACTIVE_MODEL = "openai/gpt-oss-120b"
        print(f"Hardcoded fallback model: {ACTIVE_MODEL}")

detect_model()

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
        "model": ACTIVE_MODEL,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": extract_prompt},
            {"role": "user", "content": f"原文:\n{full_text[:25000]}"}
        ]
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=180)
        if resp.status_code != 200:
            print(f"    Groq HTTP {resp.status_code}: {resp.text[:400]}")
            return None
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    Groq API error: {e}")
        return None

def get_full_article(url):
    jina_url = f"https://r.jina.ai/{url}"
    headers = {}
    if JINA_KEY:
        headers["Authorization"] = f"Bearer {JINA_KEY}"
    try:
        res = requests.get(jina_url, headers=headers, timeout=60)
        if res.status_code != 200:
            print(f"    Jina HTTP {res.status_code}")
            return None
        return res.text
    except Exception as e:
        print(f"    Jina fetch error: {e}")
        return None

def is_blacklisted(text):
    low = text.lower()
    return any(bad_word in low for bad_word in blacklist)

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
            entries = feed.entries
            if not entries:
                print(f"  警告：该RSS源没有返回任何条目")
                continue
            print(f"  获取到 {len(entries)} 条条目")
            for entry in entries[:10]:
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
                    print(f"    正文长度: {len(full_text)} 字符")
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
                    if "【跳过】" not in article_markdown:
                        article_count += 1
                        print(f"  ✅ 完成第 {article_count}/{MAX_ARTICLES} 条")
                    else:
                        print(f"  ⏭️  跳过（无实操价值）")
                    time.sleep(2)
                except Exception as e:
                    print(f"  ❌ 处理失败：{e}")
                    processed.add(link)
                    continue
        except Exception as e:
            print(f"  ❌ RSS源读取失败：{e}")
            continue

for idx, (title, md, link) in enumerate(all_results):
    if "【跳过】" in md:
        print(f"  跳过保存（无实操价值）: {title}")
        processed.add(link)
        continue
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
