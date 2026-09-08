import feedparser, requests, json, os, re, time, sys, datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
SOURCES_PATH = BASE / "config" / "sources.json"
BLACKLIST_PATH = BASE / "config" / "blacklist.txt"
PROMPT_PATH = BASE / "config" / "prompt.txt"
OUTPUT_FOLDER = BASE / "output" / "articles"
OUTPUT_FOLDER.mkdir(exist_ok=True, parents=True)
PROCESSED_FILE = OUTPUT_FOLDER / "processed.txt"

# ===== 美食视频抓取相关路径 =====
FOOD_OUTPUT_FOLDER = BASE / "output" / "food"
FOOD_OUTPUT_FOLDER.mkdir(exist_ok=True, parents=True)
FOOD_INDEX_FILE = FOOD_OUTPUT_FOLDER / "food_index.json"
FOOD_HISTORY_FILE = FOOD_OUTPUT_FOLDER / "food_history.json"
FOOD_BLACKLIST_FILE = FOOD_OUTPUT_FOLDER / "food_blacklist.json"
FOOD_PROMPT_PATH = BASE / "config" / "prompt_food.txt"
MAX_FOOD_VIDEOS = 4
FOOD_TIME_WINDOW_HOURS = 48
FOOD_MIN_DURATION_SECONDS = 60

MAX_ARTICLES = 4
SOURCE_TYPE = os.environ.get("SOURCE_TYPE", "gzh")

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

if SOURCE_TYPE == "gzh":
    source_file = "sources_gzh.json"
elif SOURCE_TYPE == "tt":
    source_file = "sources_tt.json"
else:
    source_file = "sources_food.json"
SOURCES_PATH = BASE / "config" / source_file
print(f"抓取类型: {SOURCE_TYPE}, 使用源文件: {source_file}")
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
    max_retries = 2
    for attempt in range(max_retries):
        payload = {
            "model": ACTIVE_MODEL,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": extract_prompt},
                {"role": "user", "content": f"原文:\n{full_text[:10000]}"}
            ]
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=180)
            if resp.status_code == 429:
                wait_time = 10 + attempt * 5
                print(f"    Groq 限流，等待 {wait_time}秒后重试 ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
                continue
            if resp.status_code != 200:
                print(f"    Groq HTTP {resp.status_code}: {resp.text[:300]}")
                return None
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"    Groq API error: {e}")
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return None
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


# ===== 美食视频抓取辅助函数 =====

def load_json_file(path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def extract_youtube_video_id(url):
    match = re.search(r'(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})', url)
    return match.group(1) if match else None

def get_youtube_video_info(video_id):
    """获取视频时长(秒)和观看次数，返回 (duration, view_count)"""
    duration = None
    view_count = None
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return duration, view_count
        text = resp.text
        m = re.search(r'"lengthSeconds":"(\d+)"', text)
        if m:
            duration = int(m.group(1))
        m = re.search(r'"viewCount":"(\d+)"', text)
        if m:
            view_count = int(m.group(1))
    except Exception as e:
        print(f"    视频信息获取失败: {e}")
    return duration, view_count

def format_duration(seconds):
    if seconds is None:
        return "时长待确认"
    mins, secs = divmod(seconds, 60)
    if mins >= 60:
        hours, mins = divmod(mins, 60)
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"

def llm_food_analyze(title, channel_name, description):
    """调用Groq分析美食视频，返回结构化JSON dict或None"""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    with open(FOOD_PROMPT_PATH, "r", encoding="utf-8") as f:
        food_prompt = f.read()
    user_content = f"视频标题：{title}\n频道名称：{channel_name}\n视频简介：{description[:500] if description else '无'}"
    max_retries = 2
    for attempt in range(max_retries):
        payload = {
            "model": ACTIVE_MODEL,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": food_prompt},
                {"role": "user", "content": user_content}
            ]
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            if resp.status_code == 429:
                wait_time = 10 + attempt * 5
                print(f"    Groq限流，等待{wait_time}秒后重试")
                time.sleep(wait_time)
                continue
            if resp.status_code != 200:
                print(f"    Groq HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            content = resp.json()["choices"][0]["message"]["content"]
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r'^```(?:json)?\s*', '', content)
                content = re.sub(r'\s*```$', '', content)
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return None
        except Exception as e:
            print(f"    Groq API error: {e}")
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return None
    return None

def is_similar_title(title1, title2):
    """简单判断两个标题是否高度相似（批次题材去重）"""
    words1 = set(re.findall(r'[a-zA-Z]+', title1.lower()))
    words2 = set(re.findall(r'[a-zA-Z]+', title2.lower()))
    if not words1 or not words2:
        return False
    common = words1 & words2
    return len(common) / min(len(words1), len(words2)) > 0.6

def cleanup_old_food():
    """删除3天前的美食素材索引记录（保留history和blacklist）"""
    cutoff = time.time() - 3 * 24 * 3600
    index = load_json_file(FOOD_INDEX_FILE, [])
    original_len = len(index)
    cleaned = []
    for item in index:
        try:
            ft = item.get("fetched_at", "")
            if ft:
                t = time.mktime(time.strptime(ft, "%Y-%m-%dT%H:%M:%S+08:00"))
                if t < cutoff:
                    continue
            cleaned.append(item)
        except Exception:
            cleaned.append(item)
    if len(cleaned) < original_len:
        save_json_file(FOOD_INDEX_FILE, cleaned)
        print(f"  🗑️ 清理了 {original_len - len(cleaned)} 条3天前的美食素材")

def process_food():
    """美食视频抓取主流程"""
    print("=" * 50)
    print(f"🍳 开始抓取海外美食视频，目标数量：{MAX_FOOD_VIDEOS} 条")
    print("=" * 50)

    sources_path = BASE / "config" / "sources_food.json"
    if not sources_path.exists():
        print("FATAL: config/sources_food.json 不存在")
        return
    with open(sources_path, "r", encoding="utf-8") as f:
        sources = json.load(f)

    history = load_json_file(FOOD_HISTORY_FILE, [])
    blacklist = load_json_file(FOOD_BLACKLIST_FILE, [])
    history_set = set(history)
    blacklist_set = set(blacklist)

    cleanup_old_food()

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff_time = now - datetime.timedelta(hours=FOOD_TIME_WINDOW_HOURS)

    results = []
    accepted_titles = []
    video_count = 0

    for category, rss_list in sources.items():
        if video_count >= MAX_FOOD_VIDEOS:
            break
        for feed_url in rss_list:
            if video_count >= MAX_FOOD_VIDEOS:
                break
            print(f"\n正在抓取 [{category}]：{feed_url}")
            try:
                feed = feedparser.parse(feed_url)
                entries = feed.entries
                if not entries:
                    print(f"  警告：该RSS源没有返回任何条目")
                    continue
                print(f"  获取到 {len(entries)} 条条目")

                for entry in entries[:15]:
                    if video_count >= MAX_FOOD_VIDEOS:
                        break

                    link = entry.get("link", "")
                    video_id = extract_youtube_video_id(link)
                    if not video_id:
                        continue

                    # 全局ID去重
                    if video_id in history_set:
                        continue

                    title = entry.get("title", "Untitled")
                    channel_name = entry.get("author", "Unknown")

                    # 解析发布时间
                    pub_date = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        pub_date = datetime.datetime(*entry.updated_parsed[:6], tzinfo=datetime.timezone.utc)

                    # 时间过滤：48小时以内
                    if pub_date and pub_date < cutoff_time:
                        continue

                    # 获取频道ID
                    channel_id = ""
                    if hasattr(entry, 'yt_channelid'):
                        channel_id = entry.yt_channelid
                    elif hasattr(feed.feed, 'yt_channelid'):
                        channel_id = feed.feed.yt_channelid

                    # 黑名单过滤（博主ID）
                    if channel_id and channel_id in blacklist_set:
                        print(f"  跳过(黑名单博主)：{channel_name} - {title}")
                        history_set.add(video_id)
                        continue

                    # 获取视频时长和播放量
                    print(f"  正在处理：{title}")
                    duration, view_count = get_youtube_video_info(video_id)

                    # 时长过滤：≥60秒
                    if duration is not None and duration < FOOD_MIN_DURATION_SECONDS:
                        print(f"    跳过(时长不足{duration}秒)：{title}")
                        history_set.add(video_id)
                        continue

                    # 大博主过滤：单条播放量>100万
                    if view_count is not None and view_count > 1000000:
                        print(f"    跳过(播放量{view_count}过高)：{title}")
                        history_set.add(video_id)
                        continue

                    # 获取视频简介
                    description = ""
                    if hasattr(entry, 'summary'):
                        description = entry.summary
                    elif hasattr(entry, 'description'):
                        description = entry.description
                    description = re.sub(r'<[^>]+>', '', description)

                    # Groq分析（国内账号判断+生成中文物料）
                    analysis = llm_food_analyze(title, channel_name, description)
                    if not analysis:
                        print(f"    跳过：AI分析失败")
                        history_set.add(video_id)
                        continue

                    # 国内账号过滤
                    if analysis.get("is_domestic", False):
                        print(f"    跳过(国内账号/题材)：{title}")
                        history_set.add(video_id)
                        continue

                    # 头部大博主过滤（AI判断）
                    if analysis.get("is_big_creator", False):
                        print(f"    跳过(头部大博主)：{title}")
                        history_set.add(video_id)
                        continue

                    # 批次题材去重
                    is_dup = False
                    for at in accepted_titles:
                        if is_similar_title(title, at):
                            is_dup = True
                            break
                    if is_dup:
                        print(f"    跳过(批次题材重复)：{title}")
                        history_set.add(video_id)
                        continue

                    accepted_titles.append(title)

                    # 构建美食素材条目
                    food_item = {
                        "video_id": video_id,
                        "video_url": f"https://www.youtube.com/watch?v={video_id}",
                        "title": title,
                        "channel_name": channel_name,
                        "channel_id": channel_id,
                        "published_at": pub_date.strftime("%Y-%m-%dT%H:%M:%S+00:00") if pub_date else "",
                        "duration_seconds": duration,
                        "duration_display": format_duration(duration),
                        "view_count": view_count,
                        "category": analysis.get("category", "other"),
                        "tt_title": analysis.get("tt_title", title),
                        "tt_description": analysis.get("tt_description", ""),
                        "tt_tags": analysis.get("tt_tags", "#海外美食 #美食教程"),
                        "cover_prompt": analysis.get("cover_prompt", ""),
                        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime()),
                        "source_type": "food"
                    }
                    results.append(food_item)
                    video_count += 1
                    print(f"  ✅ 完成第 {video_count}/{MAX_FOOD_VIDEOS} 条 (时长:{food_item['duration_display']})")
                    time.sleep(2)

            except Exception as e:
                print(f"  ❌ RSS源读取失败：{e}")
                continue

    # 保存结果到food_index.json（合并已有）
    existing_index = load_json_file(FOOD_INDEX_FILE, [])
    existing_ids = {item["video_id"] for item in existing_index if "video_id" in item}
    for item in results:
        if item["video_id"] not in existing_ids:
            existing_index.append(item)
    existing_index.sort(key=lambda x: x.get("fetched_at", ""), reverse=True)
    save_json_file(FOOD_INDEX_FILE, existing_index)
    print(f"\n美食素材索引已保存，共 {len(existing_index)} 条")

    # 更新去重历史
    for item in results:
        history_set.add(item["video_id"])
    save_json_file(FOOD_HISTORY_FILE, list(history_set))
    print(f"去重历史已更新，共 {len(history_set)} 条")

    print(f"\n{'=' * 50}")
    print(f"🍳 美食视频抓取完成！成功获取 {video_count} 条素材。")
    print(f"{'=' * 50}")


def cleanup_old_articles():
    """删除3天前的旧文章"""
    cutoff = time.time() - 3 * 24 * 3600
    deleted = 0
    for f in OUTPUT_FOLDER.glob("*.md"):
        if f.name == "processed.txt":
            continue
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
            print(f"  🗑️  删除旧文章: {f.name}")
    if deleted > 0:
        print(f"  共删除 {deleted} 篇3天前的旧文章")

cleanup_old_articles()

# food类型走独立的美食视频抓取流程
if SOURCE_TYPE == "food":
    process_food()
    sys.exit(0)

print("=" * 50)
print(f"开始抓取新闻，目标数量：{MAX_ARTICLES} 条")
print("=" * 50)

all_results = []
article_count = 0
article_meta = []  # 记录每篇文章的真实生成时间和中文标题

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
                        # 提取中文标题（文章里的第二个# 行）
                        chinese_title = title
                        for line in article_markdown.split('\n'):
                            if line.startswith('# ') and line != f'# {title}':
                                chinese_title = line.lstrip('# ').strip()
                                break
                        article_meta.append({
                            "orig_title": title,
                            "chinese_title": chinese_title,
                            "link": link,
                            "source_type": SOURCE_TYPE,
                            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())
                        })
                        print(f"  ✅ 完成第 {article_count}/{MAX_ARTICLES} 条")
                    else:
                        print(f"  ⏭️  跳过（无实操价值）")
                    time.sleep(3)
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

# 生成索引文件（包含中文标题和真实生成时间）
index = []
for meta in article_meta:
    safe_name = re.sub(r'[^\w]','_',meta["orig_title"])[:60] + ".md"
    f_path = OUTPUT_FOLDER / safe_name
    if f_path.exists():
        index.append({
            "name": safe_name,
            "title": meta["chinese_title"],
            "size": f_path.stat().st_size,
            "created_at": meta["generated_at"],
            "source_type": meta["source_type"]
        })

# 加上之前已有的文章（从文件mtime读取）
existing_names = {item["name"] for item in index}
for f in OUTPUT_FOLDER.glob("*.md"):
    if f.name == "processed.txt" or f.name in existing_names:
        continue
    try:
        with open(f, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
            chinese_title = ""
            for line in lines[:5]:
                if line.startswith('# ') and not line.startswith('# http'):
                    chinese_title = line.lstrip('# ').strip()
                    if chinese_title and not chinese_title.startswith('http'):
                        break
        if not chinese_title:
            chinese_title = f.name.replace(".md","").replace("_"," ")
        index.append({
            "name": f.name,
            "title": chinese_title,
            "size": f.stat().st_size,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime(f.stat().st_mtime)),
            "source_type": "unknown"
        })
    except:
        pass

index.sort(key=lambda x: x["created_at"], reverse=True)
with open(OUTPUT_FOLDER / "index.json", "w", encoding="utf-8") as f:
    json.dump(index, f, ensure_ascii=False, indent=2)
print(f"索引文件已生成，共 {len(index)} 篇")

print(f"\n{'=' * 50}")
print(f"全部完成！成功生成 {article_count} 篇新闻稿件。")
print(f"{'=' * 50}")
