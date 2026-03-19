"""
SEA Game Pulse — RSS 수집 스크립트 v2
- 썸네일 이미지 추출
- GamerBraves / GameK / Online Station 피드 수정
- DeepL API로 제목 + snippet 한국어 번역
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import feedparser
import requests

# ── 소스 목록 ──────────────────────────────────────────────────
SOURCES = [
    {
        "id": "gamerbraves",
        "name": "GamerBraves",
        "region": "sea",
        "flag": "🌏",
        "regionLabel": "SEA Wide",
        "rss": "https://www.gamerbraves.com/feed/",          # trailing slash + www 추가
        "rss_fallback": "https://gamerbraves.com/?feed=rss2",
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
        "id": "gamek",
        "name": "GameK",
        "region": "vn",
        "flag": "🇻🇳",
        "regionLabel": "Vietnam",
        "rss": "https://gamek.vn/rss.chn",
        "rss_fallback": "https://gamek.vn/feed",             # 대체 URL
    },
    {
        "id": "onlinestation",
        "name": "Online Station",
        "region": "th",
        "flag": "🇹🇭",
        "regionLabel": "Thailand",
        "rss": "https://www.online-station.net/?feed=rss2",  # 대체 URL
        "rss_fallback": "https://www.online-station.net/feed/",
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
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "")


# ── 유틸리티 ───────────────────────────────────────────────────

def strip_html(text: str) -> str:
    """HTML 태그 제거 후 공백 정리"""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return " ".join(clean.split()).strip()


def fmt_date(parsed_time) -> str:
    """feedparser의 time_struct를 날짜 문자열로 변환"""
    if not parsed_time:
        return ""
    try:
        dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
        return dt.strftime("%b %d, %Y")
    except Exception:
        return ""


def extract_thumbnail(entry) -> str:
    """RSS 엔트리에서 썸네일 이미지 URL 추출 (우선순위 순)"""
    # 1. media:content
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            url = m.get("url", "")
            if url and any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                return url
        # 확장자 없어도 일단 첫 번째 반환
        if entry.media_content[0].get("url"):
            return entry.media_content[0]["url"]

    # 2. media:thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get("url", "")
        if url:
            return url

    # 3. enclosure (type이 image/*인 것)
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("url", "")

    # 4. links 중 이미지 타입
    if hasattr(entry, "links") and entry.links:
        for link in entry.links:
            if link.get("type", "").startswith("image/"):
                return link.get("href", "")

    # 5. summary/content 내 첫 번째 <img src="..."> 추출
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


# ── DeepL 번역 ─────────────────────────────────────────────────

def translate_texts(texts: list[str]) -> list[str]:
    """DeepL API로 텍스트 목록을 한국어로 번역"""
    if not DEEPL_API_KEY:
        print("  ⚠ DEEPL_API_KEY 없음 — 번역 건너뜀")
        return texts

    # DeepL API Free 엔드포인트 (유료는 api.deepl.com)
    endpoint = "https://api-free.deepl.com/v2/translate"

    # 빈 문자열 제외하고 번역할 텍스트만 추출
    non_empty = [(i, t) for i, t in enumerate(texts) if t.strip()]
    if not non_empty:
        return texts

    results = list(texts)  # 복사본

    try:
        payload = {
            "auth_key": DEEPL_API_KEY,
            "text": [t for _, t in non_empty],
            "target_lang": "KO",
        }
        resp = requests.post(endpoint, data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        translations = [t["text"] for t in data["translations"]]

        for (orig_idx, _), translated in zip(non_empty, translations):
            results[orig_idx] = translated

        return results

    except Exception as e:
        print(f"  ⚠ DeepL 번역 실패: {e} — 원문 유지")
        return texts


# ── RSS 수집 ───────────────────────────────────────────────────

def fetch_feed(source: dict) -> list[dict]:
    """RSS 피드를 가져와 기사 목록 반환 (fallback URL 포함)"""
    urls_to_try = [source["rss"]]
    if "rss_fallback" in source:
        urls_to_try.append(source["rss_fallback"])

    for url in urls_to_try:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)

            if not feed.entries:
                print(f"  ⚠ {source['name']} ({url}): 엔트리 없음, 다음 URL 시도")
                continue

            articles = []
            for entry in feed.entries[:ARTICLES_PER_SOURCE]:
                thumbnail = extract_thumbnail(entry)
                snippet_raw = ""
                if hasattr(entry, "summary"):
                    snippet_raw = strip_html(entry.summary)[:200]
                elif hasattr(entry, "content") and entry.content:
                    snippet_raw = strip_html(entry.content[0].get("value", ""))[:200]

                articles.append({
                    "title":     entry.get("title", "(No title)").strip(),
                    "link":      entry.get("link", "#"),
                    "date":      fmt_date(getattr(entry, "published_parsed", None)),
                    "snippet":   snippet_raw,
                    "thumbnail": thumbnail,
                    # 번역본은 아래에서 채움
                    "title_ko":   "",
                    "snippet_ko": "",
                })

            print(f"  ✅ {source['name']}: {len(articles)}개 기사 수집 (URL: {url})")
            return articles

        except Exception as e:
            print(f"  ❌ {source['name']} ({url}) 실패: {e}")

    print(f"  ❌ {source['name']}: 모든 URL 실패")
    return []


def translate_source_articles(articles: list[dict]) -> list[dict]:
    """기사 목록의 제목 + snippet을 DeepL로 한국어 번역"""
    if not articles or not DEEPL_API_KEY:
        return articles

    titles  = [a["title"]   for a in articles]
    snippets = [a["snippet"] for a in articles]

    # 제목 + snippet 한 번에 번역 (API 호출 최소화)
    all_texts = titles + snippets
    translated = translate_texts(all_texts)

    n = len(articles)
    for i, article in enumerate(articles):
        article["title_ko"]   = translated[i]
        article["snippet_ko"] = translated[n + i]

    return articles


# ── 메인 ───────────────────────────────────────────────────────

def main():
    print(f"\n[SEA Game Pulse v2] RSS 수집 시작 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    if DEEPL_API_KEY:
        print(f"  🌐 DeepL API 키 확인됨 — 번역 활성화\n")
    else:
        print(f"  ⚠ DeepL API 키 없음 — 번역 비활성화\n")

    output = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "translated": bool(DEEPL_API_KEY),
        "sources": [],
    }

    for source in SOURCES:
        articles = fetch_feed(source)

        if articles and DEEPL_API_KEY:
            print(f"  🌐 {source['name']} 번역 중...")
            articles = translate_source_articles(articles)
            time.sleep(0.3)  # API 레이트 리밋 방지

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
    output_path = "docs/data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(s["articles"]) for s in output["sources"])
    print(f"\n✅ 완료: 총 {total}개 기사 → {output_path} 저장\n")


if __name__ == "__main__":
    main()
