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
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    js = ("const UPDATED=" + json.dumps(updated)
          + ";\nconst CASES=" + json.dumps(deduped, ensure_ascii=False, indent=1) + ";\n")
    OUT.write_text(js, encoding="utf-8")
    with_mrr = sum(1 for c in deduped if c["mrr"])
    print(f"\n完成：{len(deduped)} 個案例（{with_mrr} 個含營收數字）→ {OUT}")

if __name__ == "__main__":
    main()
