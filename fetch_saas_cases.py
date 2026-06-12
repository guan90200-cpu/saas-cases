# -*- coding: utf-8 -*-
"""
fetch_saas_cases.py — 抓取「賺錢訂閱型 SaaS / 工作流」案例 → 產生 cases.js
來源：Hacker News (Algolia API) + Reddit (.json endpoint)，全部免費、不用 API key。
確定性寫檔：模型不參與，跑完 cases.js 一定存在。
用法：python fetch_saas_cases.py
"""
import json, re, sys, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path(__file__).parent / "cases.js"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

def get_json(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  [retry {i+1}] {url[:80]} -> {e}")
            time.sleep(2 * (i + 1))
    return None

# ---------- 關鍵字規則（全部確定性，不經模型） ----------
RELEVANT = re.compile(
    r"\b(mrr|arr|saas|subscription|recurring|revenue|paying customer|automation|"
    r"workflow|n8n|zapier|make\.com|micro.?saas|side project|indie|bootstrapp|"
    r"launched|monetiz|stripe)\b", re.I)

MRR_PAT = re.compile(
    r"(\$\s?\d[\d,\.]*\s?[kKmM]?\s*(?:/\s*(?:mo|month)|MRR|ARR)"
    r"|\d[\d,\.]*\s?[kKmM]?\s*(?:MRR|ARR)"
    r"|\$\s?\d[\d,\.]*\s?[kKmM]?\s+(?:per month|a month|monthly))")

def extract_mrr(text):
    m = MRR_PAT.search(text or "")
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None

def categorize(text):
    t = (text or "").lower()
    if re.search(r"\b(acquired|sold my|sold our|exit|flipp)\b", t): return "出售變現"
    if re.search(r"\b(n8n|zapier|make\.com|automation|workflow|agent)\b", t): return "工作流自動化"
    if MRR_PAT.search(t) or re.search(r"\b(revenue|paying customer)\b", t): return "營收實戰"
    if re.search(r"\b(ai|gpt|llm|claude|gemini)\b", t): return "AI SaaS"
    return "SaaS 經營"

def make_case(title, summary, url, source, points, comments, ts):
    blob = f"{title} {summary}"
    return {
        "title": title.strip(),
        "summary": re.sub(r"\s+", " ", (summary or ""))[:300],
        "url": url,
        "source": source,
        "category": categorize(blob),
        "mrr": extract_mrr(blob),
        "points": int(points or 0),
        "comments": int(comments or 0),
        "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
    }

# ---------- 來源 1：Hacker News Algolia ----------
def fetch_hn():
    queries = ['MRR', 'SaaS revenue', 'Show HN subscription', 'workflow automation', 'micro SaaS']
    cases = []
    for q in queries:
        url = ("https://hn.algolia.com/api/v1/search?query=" + urllib.parse.quote(q)
               + "&tags=story&numericFilters=points>20&hitsPerPage=30")
        data = get_json(url)
        if not data: continue
        for h in data.get("hits", []):
            title = h.get("title") or ""
            text = h.get("story_text") or ""
            if not RELEVANT.search(f"{title} {text}"): continue
            link = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
            cases.append(make_case(title, text, link, "HackerNews",
                                   h.get("points"), h.get("num_comments"), h.get("created_at_i", 0)))
        print(f"  HN「{q}」: 累計 {len(cases)} 筆")
        time.sleep(1)
    return cases

# ---------- 來源 2：Reddit（JSON API 擋腳本，改走 RSS） ----------
ATOM = "{http://www.w3.org/2005/Atom}"

def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
           .replace("&quot;", '"').replace("&#39;", "'").replace("&#32;", " "))
    return re.sub(r"\s+", " ", s).strip()

def fetch_reddit():
    subs = ["SaaS", "indiehackers", "SideProject", "EntrepreneurRideAlong"]
    cases = []
    for sub in subs:
        url = f"https://www.reddit.com/r/{sub}/top/.rss?t=week&limit=50"
        root = None
        for attempt in range(4):  # Reddit RSS 對同 IP 限流很緊，429 就指數退避
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=20) as r:
                    root = ET.fromstring(r.read())
                break
            except Exception as e:
                print(f"  r/{sub}: [retry {attempt+1}] {e}")
                time.sleep(15 * (attempt + 1))
        if root is None:
            continue
        n0 = len(cases)
        for entry in root.iter(ATOM + "entry"):
            title = (entry.findtext(ATOM + "title") or "").strip()
            content = strip_html(entry.findtext(ATOM + "content") or "")
            # 摘要裡的「submitted by /u/xxx [link] [comments]」尾巴去掉
            content = re.sub(r"submitted by\s+/u/\S+.*$", "", content).strip()
            link_el = entry.find(ATOM + "link")
            link = link_el.get("href") if link_el is not None else ""
            updated = entry.findtext(ATOM + "updated") or "1970-01-01T00:00:00+00:00"
            ts = datetime.fromisoformat(updated).timestamp()
            if not RELEVANT.search(f"{title} {content}"): continue
            cases.append(make_case(title, content, link, f"r/{sub}", 0, 0, ts))
        print(f"  r/{sub}: +{len(cases)-n0} 筆")
        time.sleep(10)
    return cases

# ---------- 封面圖層：抓原文連結的 og:image（含快取，失敗也快取避免重打） ----------
OG_CACHE = Path(__file__).parent / "og_cache.json"  # 已 .gitignore
SKIP_OG_DOMAINS = ("news.ycombinator.com", "reddit.com", "www.reddit.com")  # 通用圖/擋爬蟲
OG_PAT = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::src)?["\'][^>]+content=["\']([^"\']+)'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)', re.I)

def fetch_og_image(url):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        if any(host.endswith(d) for d in SKIP_OG_DOMAINS):
            return None
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=10) as r:
            if "text/html" not in (r.headers.get("Content-Type") or ""):
                return None
            html = r.read(120_000).decode("utf-8", "ignore")
        m = OG_PAT.search(html)
        if not m:
            return None
        img = (m.group(1) or m.group(2) or "").strip()
        if img.startswith("//"): img = "https:" + img
        if not img.startswith("http"): img = urllib.parse.urljoin(url, img)
        return img
    except Exception:
        return None

def attach_cover_images(cases):
    from concurrent.futures import ThreadPoolExecutor
    cache = json.loads(OG_CACHE.read_text(encoding="utf-8")) if OG_CACHE.exists() else {}
    todo = [c for c in cases if c["url"] not in cache]
    print(f"封面圖：{len(cases)-len(todo)} 筆走快取，{len(todo)} 筆待查")
    if todo:
        with ThreadPoolExecutor(max_workers=10) as ex:
            for c, img in zip(todo, ex.map(lambda c: fetch_og_image(c["url"]), todo)):
                cache[c["url"]] = img  # 失敗存 null，明天不重打
        OG_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    n = 0
    for c in cases:
        if cache.get(c["url"]):
            c["img"] = cache[c["url"]]; n += 1
    print(f"  共 {n}/{len(cases)} 筆有封面圖")
    return cases

# ---------- 翻譯層：Gemini 把 title/summary 翻成繁中（含快取，只翻新案例） ----------
KEYFILE = Path.home() / ".gemini_key.json"   # repo 外，絕不 commit
CACHE = Path(__file__).parent / "translations.json"  # 已 .gitignore
RETRY_CODES = {429, 500, 502, 503, 529}
BACKOFF = [5, 15, 40, 60]

def load_gemini_cfg():
    """優先讀本機 keyfile；沒有就從 WSL 的 Hermes config 抽一次並存起來。"""
    if KEYFILE.exists():
        d = json.loads(KEYFILE.read_text(encoding="utf-8"))
        return d["url"], d["key"], d["model"]
    import subprocess
    cfg = subprocess.run(["wsl", "-e", "bash", "-lc", "cat ~/.hermes/config.yaml"],
                         capture_output=True, text=True, timeout=30).stdout
    m = re.search(r"name:\s*gemini-cloud(.*?)(?:\n-\s|\Z)", cfg, re.S)
    if not m:
        raise RuntimeError("WSL config.yaml 找不到 gemini-cloud provider")
    blk = m.group(1)
    url = re.search(r"base_url:\s*(\S+)", blk).group(1).rstrip("/") + "/chat/completions"
    key = re.search(r"api_key:\s*(\S+)", blk).group(1)
    model = re.search(r"model:\s*(\S+)", blk).group(1)
    KEYFILE.write_text(json.dumps({"url": url, "key": key, "model": model}), encoding="utf-8")
    return url, key, model

def call_gemini(url, key, model, prompt):
    body = json.dumps({"model": model, "temperature": 0.2, "max_tokens": 8192,
                       "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    last_err = None
    for attempt in range(len(BACKOFF) + 1):
        try:
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in RETRY_CODES and attempt < len(BACKOFF):
                time.sleep(BACKOFF[attempt]); continue
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
            if attempt < len(BACKOFF):
                time.sleep(BACKOFF[attempt]); continue
            break
    raise RuntimeError(last_err)

def translate_cases(cases):
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = [c for c in cases if c["url"] not in cache]
    print(f"翻譯：{len(cases)-len(todo)} 筆走快取，{len(todo)} 筆新案例待翻")
    if todo:
        try:
            url, key, model = load_gemini_cfg()
        except Exception as e:
            print(f"  取 Gemini key 失敗（{e}），本次保留英文")
            todo = []
        def translate_batch(batch, depth=0):
            """一批翻譯；JSON 壞掉就對半切重試，切到 1 筆還失敗才放棄。"""
            items = [{"i": j, "t": c["title"], "s": c["summary"][:200]} for j, c in enumerate(batch)]
            prompt = ("把下列 SaaS 案例的 t(標題) 和 s(摘要) 翻成自然的繁體中文（台灣用語）。"
                      "產品名、人名、專有名詞、金額數字保留原文。"
                      "只回傳 JSON array，格式 [{\"i\":0,\"t\":\"...\",\"s\":\"...\"}]，不要任何其他文字。\n\n"
                      + json.dumps(items, ensure_ascii=False))
            try:
                resp = call_gemini(url, key, model, prompt)
                resp = re.sub(r"^```(?:json)?|```$", "", resp.strip(), flags=re.M).strip()
                for row in json.loads(resp):
                    c = batch[row["i"]]
                    cache[c["url"]] = {"t": row["t"], "s": row["s"]}
                return len(batch)
            except Exception as e:
                if len(batch) > 1:
                    print(f"  {'  '*depth}批({len(batch)}筆)壞 JSON，對半切重試")
                    time.sleep(2)
                    mid = len(batch) // 2
                    return translate_batch(batch[:mid], depth+1) + translate_batch(batch[mid:], depth+1)
                print(f"  {'  '*depth}單筆放棄（{e}）：{batch[0]['title'][:50]}")
                return 0
            finally:
                time.sleep(2)

        done = 0
        for i in range(0, len(todo), 20):
            done += translate_batch(todo[i:i+20])
            print(f"  進度 {min(i+20,len(todo))}/{len(todo)}（成功 {done}）")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in cases:
        if c["url"] in cache:
            c["title_zh"] = cache[c["url"]]["t"]
            c["summary_zh"] = cache[c["url"]]["s"]
    return cases

def main():
    print("抓取 Hacker News ...")
    cases = fetch_hn()
    print("抓取 Reddit ...")
    cases += fetch_reddit()

    # 去重（同 URL / 同標題只留熱度最高的）
    seen, deduped = {}, []
    for c in sorted(cases, key=lambda x: -x["points"]):
        key = c["url"].rstrip("/").lower()
        tkey = c["title"].lower()
        if key in seen or tkey in seen: continue
        seen[key] = seen[tkey] = True
        deduped.append(c)

    deduped.sort(key=lambda x: -x["points"])
    deduped = attach_cover_images(deduped)
    deduped = translate_cases(deduped)
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    js = ("const UPDATED=" + json.dumps(updated)
          + ";\nconst CASES=" + json.dumps(deduped, ensure_ascii=False, indent=1) + ";\n")
    OUT.write_text(js, encoding="utf-8")
    with_mrr = sum(1 for c in deduped if c["mrr"])
    print(f"\n完成：{len(deduped)} 個案例（{with_mrr} 個含營收數字）→ {OUT}")

if __name__ == "__main__":
    main()
