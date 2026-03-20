"""
SEA Game Pulse — RSS 수집 스크립트 ver2
변경사항:
- DeepL 번역 제거
- 기사 본문 크롤링 추가 (BeautifulSoup)
- Gemini AI 한국어 요약 추가
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
    # SEA Wide
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
    # Philippines
    {
        "id": "gamingph",
        "name": "GamingPH",
        "region": "ph",
        "flag": "🇵🇭",
        "regionLabel": "Philippines",
        "rss": "https://www.gamingph.com/feed",
    },
    # Vietnam
    {
        "id": "gamelade",
        "name": "Gamelade",
        "region": "vn",
        "flag": "🇻🇳",
        "regionLabel": "Vietnam",
        "rss": "https://gamelade.vn/feed",
    },
    # Thailand
    {
        "id": "droidsans",
        "name": "Droidsans",
        "region": "th",
        "flag": "🇹🇭",
        "regionLabel": "Thailand",
        "rss": "https://droidsans.com/feed",
        "rss_fallback": "https://droidsans.com/?feed=rss2",
    },
    # Indonesia
    {
        "id": "gamebrott",
        "name": "Gamebrott",
        "region": "id",
        "flag": "🇮🇩",
        "regionLabel": "Indonesia",
        "rss": "https://gamebrott.com/feed",
    },
    # Malaysia
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
    # 1. media:content
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            url = m.get("url", "")
            if url and any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                return url
        if entry.media_content[0].get("url"):
            return entry.media_content[0]["url"]

    # 2. media:thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get("url", "")
        if url:
            return url

    # 3. enclosure
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("url", "")

    # 4. links
    if hasattr(entry, "links") and entry.links:
        for link in entry.links:
            if link.get("type", "").startswith("image/"):
                return link.get("href", "")

    # 5. <img> in summary/content
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


# ── 기사 본문 크롤링 ────────────────────────────────────────────

# 사이트별 본문 영역 CSS 선택자
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

# 본문에서 제거할 노이즈 태그
NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside",
              "figure", "figcaption", "iframe", "noscript", ".sharedaddy",
              ".related-posts", ".comment", "#comments"]


def crawl_article(url: str, source_id: str) -> str:
    """기사 URL에서 본문 텍스트를 추출합니다."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 노이즈 제거
        for tag in soup(["script", "style", "nav", "footer", "aside",
                         "figure", "figcaption", "iframe", "noscript"]):
            tag.decompose()

        # 사이트별 선택자로 본문 탐색
        selectors = CONTENT_SELECTORS.get(source_id, ["article", ".entry-content", ".post-content"])
        content_el = None
        for selector in selectors:
            content_el = soup.select_one(selector)
            if content_el:
                break

        # 선택자 실패 시 <main> 또는 <body> 폴백
        if not content_el:
            content_el = soup.find("main") or soup.find("body")

        if not content_el:
            return ""

        # 텍스트 추출 및 정리
        text = content_el.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()

        # 최대 3,000자로 제한 (Gemini 토큰 절약)
        return text[:3000]

    except Exception as e:
        print(f"    ⚠ 본문 크롤링 실패 ({url}): {e}")
        return ""


# ── Gemini AI 요약 ──────────────────────────────────────────────

SUMMARY_PROMPT = """You are a news summarizer. Read the article below and output ONLY a Korean summary.

STRICT OUTPUT FORMAT — follow exactly:
- Output exactly 3 lines
- Each line is one key point in Korean (1 sentence)
- No bullet points, no numbers, no labels, no explanation
- No preamble like "이 기사는..." or "요약:"
- Game names, brand names, proper nouns must stay in original language

Article title: {title}

Article body:
{body}

Output (3 lines of Korean only):"""


def summarize_with_gemini(title: str, body: str) -> str:
    """Gemini API로 기사를 한국어 3포인트로 요약합니다."""
    if not GEMINI_API_KEY:
        return ""

    if not body.strip():
        return ""

    prompt = SUMMARY_PROMPT.format(title=title, body=body)

    try:
        resp = requests.post(
            GEMINI_ENDPOINT,
            headers={"Content-Type": "application/json"},
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 512,
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        summary = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return summary

    except Exception as e:
        print(f"    ⚠ Gemini 요약 실패: {e}")
        return ""


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
                print(f"  ⚠ {source['name']} ({url}): 엔트리 없음, 다음 URL 시도")
                continue

            articles = []
            for entry in feed.entries[:ARTICLES_PER_SOURCE]:
                articles.append({
                    "title":    entry.get("title", "(No title)").strip(),
                    "link":     entry.get("link", "#"),
                    "date":     fmt_date(getattr(entry, "published_parsed", None)),
                    "thumbnail": extract_thumbnail(entry),
                    "summary_ko": "",  # Gemini 요약 결과
                })

            print(f"  ✅ {source['name']}: {len(articles)}개 기사 수집")
            return articles

        except Exception as e:
            print(f"  ❌ {source['name']} ({url}) 실패: {e}")

    print(f"  ❌ {source['name']}: 모든 URL 실패")
    return []


def process_articles(articles: list, source_id: str) -> list:
    """기사 본문 크롤링 + Gemini 요약을 순차 처리합니다."""
    for i, article in enumerate(articles):
        print(f"    [{i+1}/{len(articles)}] {article['title'][:40]}...")

        # 본문 크롤링
        body = crawl_article(article["link"], source_id)
        if body:
            print(f"      📄 본문 {len(body)}자 추출")
        else:
            print(f"      ⚠ 본문 추출 실패 — 요약 건너뜀")
            continue

        # Gemini 요약
        summary = summarize_with_gemini(article["title"], body)
        if summary:
            article["summary_ko"] = summary
            print(f"      ✅ Gemini 요약 완료")
        else:
            print(f"      ⚠ Gemini 요약 실패")

        # API 레이트 리밋 방지 (분당 15회 제한)
        time.sleep(4)

    return articles


# ── 메인 ───────────────────────────────────────────────────────

def main():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n[SEA Game Pulse ver2] RSS 수집 시작 — {now_str}\n")

    if GEMINI_API_KEY:
        print("  🤖 Gemini API 키 확인됨 — AI 요약 활성화\n")
    else:
        print("  ⚠ GEMINI_API_KEY 없음 — 요약 비활성화\n")

    output = {
        "updated_at": now_str,
        "ai_summary": bool(GEMINI_API_KEY),
        "sources": [],
    }

    for source in SOURCES:
        print(f"\n▶ {source['name']} 처리 중...")
        articles = fetch_feed(source)

        if articles and GEMINI_API_KEY:
            articles = process_articles(articles, source["id"])

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
    print(f"\n✅ 완료: 총 {total}개 기사 → docs/data.json 저장\n")


if __name__ == "__main__":
    main()
