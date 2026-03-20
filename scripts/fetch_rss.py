"""
SEA Game Pulse — RSS 수집 스크립트 ver2.2
최적화:
- 단계 2: 중복 요약 방지 캐시 (이미 요약된 기사는 API 호출 건너뜀)
- 단계 3: 본문 크롤링 실패 시 RSS snippet으로 폴백
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

# ── 소스 목록 ──────────────────────────────────────────────────
SOURCES = [
    {
        "id": "back2gaming",
        "name": "Back2Gaming",
        "region": "sea",
        "flag": "🌏",
        "regionLabel": "SEA Wide",
        "rss": "https://back2gaming.com/feed",
        "rss_fallback": "https://back2gaming.com/?feed=rss2",
    },
    {
        "id": "geekculture",
        "name": "Geek Culture",
        "region": "sea",
        "flag": "🌏",
        "regionLabel": "SEA Wide",
        "rss": "https://geekculture.co/games/feed",
        "rss_fallback": "https://geekculture.co/feed",
    },
    {
        "id": "gamingonphone",
        "name": "GamingonPhone",
        "region": "sea",
        "flag": "🌏",
        "regionLabel": "SEA Wide",
        "rss": "https://gamingonphone.com/feed",
    },
    {
        "id": "lowyat",
        "name": "Lowyat.net",
        "region": "sea",
        "flag": "🌏",
        "regionLabel": "SEA Wide / Malaysia",
        "rss": "https://lowyat.net/feed",
    },
    {
        "id": "gamingph",
        "name": "GamingPH",
        "region": "ph",
        "flag": "🇵🇭",
        "regionLabel": "Philippines",
        "rss": "https://www.gamingph.com/feed",
    },
    {
        "id": "gamelade",
        "name": "Gamelade",
        "region": "vn",
        "flag": "🇻🇳",
        "regionLabel": "Vietnam",
        "rss": "https://gamelade.vn/feed",
    },
    {
        "id": "droidsans",
        "name": "Droidsans",
        "region": "th",
        "flag": "🇹🇭",
        "regionLabel": "Thailand",
        "rss": "https://droidsans.com/feed",
        "rss_fallback": "https://droidsans.com/?feed=rss2",
    },
    {
        "id": "gamebrott",
        "name": "Gamebrott",
        "region": "id",
        "flag": "🇮🇩",
        "regionLabel": "Indonesia",
        "rss": "https://gamebrott.com/feed",
    },
    {
        "id": "kakuchopurei",
        "name": "Kakuchopurei",
        "region": "my",
        "flag": "🇲🇾",
        "regionLabel": "Malaysia",
        "rss": "https://kakuchopurei.com/feed",
    },
]

ARTICLES_PER_SOURCE = 3
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash-lite:generateContent"
)

CONTENT_SELECTORS = {
    "back2gaming":   ["article", ".entry-content", ".post-content"],
    "geekculture":   ["article", ".entry-content", ".post-content"],
    "gamingonphone": ["article", ".entry-content", ".article-content"],
    "lowyat":        [".entry-content", "article", ".post-body"],
    "gamingph":      ["article", ".entry-content", ".post-content"],
    "gamelade":      ["article", ".article-content", ".entry-content"],
    "droidsans":     ["article", ".entry-content", ".post-content"],
    "gamebrott":     ["article", ".entry-content", ".post-content"],
    "kakuchopurei":  ["article", ".entry-content", ".post-content"],
}


# ── 유틸리티 ───────────────────────────────────────────────────

def strip_html(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return " ".join(clean.split()).strip()


def fmt_date(parsed_time) -> str:
    if not parsed_time:
        return ""
    try:
        dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
        return dt.strftime("%b %d, %Y")
    except Exception:
        return ""


def extract_thumbnail(entry) -> str:
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            url = m.get("url", "")
            if url and any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                return url
        if entry.media_content[0].get("url"):
            return entry.media_content[0]["url"]
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get("url", "")
        if url:
            return url
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("url", "")
    if hasattr(entry, "links") and entry.links:
        for link in entry.links:
            if link.get("type", "").startswith("image/"):
                return link.get("href", "")
    for field in ["summary", "content"]:
        text = ""
        if field == "content" and hasattr(entry, "content") and entry.content:
            text = entry.content[0].get("value", "")
        elif hasattr(entry, field):
            text = getattr(entry, field, "")
        if text:
            match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', text, re.IGNORECASE)
            if match:
                url = match.group(1)
                if url.startswith("http"):
                    return url
    return ""


# ── 단계 2: 캐시 로드 ──────────────────────────────────────────

def load_summary_cache() -> dict:
    """기존 data.json에서 요약이 완료된 기사의 링크→요약 맵을 로드합니다."""
    cache = {}
    try:
        with open("docs/data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for source in data.get("sources", []):
            for article in source.get("articles", []):
                link = article.get("link", "")
                summary = article.get("summary_ko", "")
                if link and summary:
                    cache[link] = summary
        print(f"  📦 캐시 로드: {len(cache)}개 기사 요약 재사용 가능\n")
    except FileNotFoundError:
        print("  📦 캐시 없음 (첫 실행)\n")
    except Exception as e:
        print(f"  ⚠ 캐시 로드 실패: {e}\n")
    return cache


# ── 단계 3: 본문 크롤링 + snippet 폴백 ────────────────────────

def crawl_article(url: str, source_id: str, snippet: str = "") -> str:
    """기사 본문 크롤링. 실패 시 RSS snippet으로 폴백합니다."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside",
                         "figure", "figcaption", "iframe", "noscript"]):
            tag.decompose()
        selectors = CONTENT_SELECTORS.get(source_id, ["article", ".entry-content"])
        content_el = None
        for selector in selectors:
            content_el = soup.select_one(selector)
            if content_el:
                break
        if not content_el:
            content_el = soup.find("main") or soup.find("body")
        if not content_el:
            raise ValueError("본문 영역 미발견")

        text = content_el.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) < 100:
            raise ValueError(f"본문 너무 짧음 ({len(text)}자)")

        return text[:2000]

    except Exception as e:
        # 단계 3: RSS snippet 폴백
        if snippet and len(snippet) > 50:
            print(f"    ⚠ 크롤링 실패 → RSS snippet 폴백 ({len(snippet)}자)")
            return snippet
        print(f"    ⚠ 크롤링 실패, snippet도 없음: {e}")
        return ""


# ── Gemini 배치 요약 ────────────────────────────────────────────

BATCH_PROMPT = """You are a news summarizer. Below are {count} game-related articles.
For EACH article, output exactly 3 lines of Korean summary.
Separate each article's summary with "---" on its own line.

STRICT OUTPUT FORMAT:
- Article 1: 3 lines of Korean, then "---"
- Article 2: 3 lines of Korean, then "---"
- (and so on)
- No bullet points, no numbers, no labels
- Game names, brand names, proper nouns stay in original language
- Each line is one key point (1 sentence)

{articles}

Output ({count} summaries separated by "---"):"""


def summarize_batch_with_gemini(articles: list) -> list:
    """매체의 기사 목록을 한 번의 API 호출로 배치 요약합니다."""
    if not GEMINI_API_KEY:
        return [""] * len(articles)

    valid = [(i, a) for i, a in enumerate(articles) if a.get("body", "").strip()]
    if not valid:
        return [""] * len(articles)

    articles_text = ""
    for idx, (_, art) in enumerate(valid, 1):
        articles_text += f"[Article {idx}]\nTitle: {art['title']}\nBody: {art['body']}\n\n"

    prompt = BATCH_PROMPT.format(count=len(valid), articles=articles_text)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                GEMINI_ENDPOINT,
                headers={"Content-Type": "application/json"},
                params={"key": GEMINI_API_KEY},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 1024,
                    },
                },
                timeout=60,
            )
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            parts = [p.strip() for p in raw.split("---") if p.strip()]

            results = [""] * len(articles)
            for j, (orig_idx, _) in enumerate(valid):
                if j < len(parts):
                    results[orig_idx] = parts[j]

            print(f"  ✅ Gemini 배치 요약 완료 ({len(valid)}개 기사, 1회 API 호출)")
            return results

        except Exception as e:
            status = getattr(getattr(e, 'response', None), 'status_code', 0)
            if status in (429, 503) and attempt < max_retries - 1:
                wait = 20 * (attempt + 1)
                print(f"  ⏳ {status} 오류, {wait}초 후 재시도 ({attempt + 1}/{max_retries - 1})...")
                time.sleep(wait)
            else:
                print(f"  ⚠ Gemini 배치 요약 실패: {e}")
                return [""] * len(articles)

    return [""] * len(articles)


# ── RSS 수집 ───────────────────────────────────────────────────

def fetch_feed(source: dict) -> list:
    urls_to_try = [source["rss"]]
    if "rss_fallback" in source:
        urls_to_try.append(source["rss_fallback"])

    for url in urls_to_try:
        try:
            resp = requests.get(
                url,
                headers={**HEADERS, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
                timeout=15,
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)

            if not feed.entries:
                print(f"  ⚠ {source['name']} ({url}): 엔트리 없음")
                continue

            articles = []
            for entry in feed.entries[:ARTICLES_PER_SOURCE]:
                # RSS snippet 추출 (단계 3 폴백용)
                snippet = ""
                if hasattr(entry, "summary"):
                    snippet = strip_html(entry.summary)[:500]
                elif hasattr(entry, "content") and entry.content:
                    snippet = strip_html(entry.content[0].get("value", ""))[:500]

                articles.append({
                    "title":      entry.get("title", "(No title)").strip(),
                    "link":       entry.get("link", "#"),
                    "date":       fmt_date(getattr(entry, "published_parsed", None)),
                    "thumbnail":  extract_thumbnail(entry),
                    "snippet":    snippet,   # 크롤링 폴백용
                    "body":       "",
                    "summary_ko": "",
                })

            print(f"  ✅ {source['name']}: {len(articles)}개 기사 수집")
            return articles

        except Exception as e:
            print(f"  ❌ {source['name']} ({url}) 실패: {e}")

    print(f"  ❌ {source['name']}: 모든 URL 실패")
    return []


# ── 메인 ───────────────────────────────────────────────────────

def main():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n[SEA Game Pulse ver2.2] RSS 수집 시작 — {now_str}")
    print(f"  📌 최적화: 캐시(중복 방지) + snippet 폴백\n")

    if GEMINI_API_KEY:
        print("  🤖 Gemini API 키 확인됨 — AI 요약 활성화")
    else:
        print("  ⚠ GEMINI_API_KEY 없음 — 요약 비활성화")

    # 단계 2: 기존 요약 캐시 로드
    summary_cache = load_summary_cache()

    output = {
        "updated_at": now_str,
        "ai_summary": bool(GEMINI_API_KEY),
        "sources": [],
    }

    total_cached = 0
    total_new = 0

    for source in SOURCES:
        print(f"▶ {source['name']} 처리 중...")
        articles = fetch_feed(source)

        if articles:
            # 단계 2: 캐시 확인 — 이미 요약된 기사는 건너뜀
            for article in articles:
                cached_summary = summary_cache.get(article["link"], "")
                if cached_summary:
                    article["summary_ko"] = cached_summary
                    article["_cached"] = True
                    total_cached += 1
                else:
                    article["_cached"] = False

            new_articles = [a for a in articles if not a["_cached"]]
            cached_articles = [a for a in articles if a["_cached"]]

            print(f"  📦 캐시 재사용: {len(cached_articles)}개 / 신규 요약 필요: {len(new_articles)}개")

            if new_articles and GEMINI_API_KEY:
                # 신규 기사만 본문 크롤링
                for i, article in enumerate(new_articles):
                    body = crawl_article(article["link"], source["id"], article.get("snippet", ""))
                    article["body"] = body
                    status = f"{len(body)}자" if body else "실패"
                    print(f"  [{i+1}/{len(new_articles)}] 본문 {status}")

                # 신규 기사만 배치 요약
                summaries = summarize_batch_with_gemini(new_articles)
                for i, summary in enumerate(summaries):
                    new_articles[i]["summary_ko"] = summary
                    if summary:
                        total_new += 1

                time.sleep(5)

            # 임시 필드 정리
            for article in articles:
                article.pop("body", None)
                article.pop("snippet", None)
                article.pop("_cached", None)

        output["sources"].append({
            "id":          source["id"],
            "name":        source["name"],
            "region":      source["region"],
            "flag":        source["flag"],
            "regionLabel": source["regionLabel"],
            "articles":    articles,
            "error":       len(articles) == 0,
        })

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(s["articles"]) for s in output["sources"])
    print(f"\n✅ 완료: 총 {total}개 기사 (캐시 {total_cached}개 재사용 / 신규 {total_new}개 요약)")
    print(f"   → docs/data.json 저장\n")


if __name__ == "__main__":
    main()
