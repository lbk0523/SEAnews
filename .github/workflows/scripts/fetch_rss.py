"""
SEA Game Pulse — RSS 수집 스크립트
GitHub Actions에서 매일 실행되어 docs/data.json을 갱신합니다.
"""

import json
import os
from datetime import datetime, timezone

import feedparser
import requests

SOURCES = [
    {"id": "gamerbraves",   "name": "GamerBraves",   "region": "sea", "flag": "🌏", "regionLabel": "SEA Wide",            "rss": "https://gamerbraves.com/feed"},
    {"id": "lowyat",        "name": "Lowyat.net",     "region": "sea", "flag": "🌏", "regionLabel": "SEA Wide / Malaysia", "rss": "https://lowyat.net/feed"},
    {"id": "gamingph",      "name": "GamingPH",       "region": "ph",  "flag": "🇵🇭", "regionLabel": "Philippines",         "rss": "https://www.gamingph.com/feed"},
    {"id": "gamek",         "name": "GameK",          "region": "vn",  "flag": "🇻🇳", "regionLabel": "Vietnam",             "rss": "https://gamek.vn/rss.chn"},
    {"id": "onlinestation", "name": "Online Station", "region": "th",  "flag": "🇹🇭", "regionLabel": "Thailand",            "rss": "https://www.online-station.net/feed"},
    {"id": "gamebrott",     "name": "Gamebrott",      "region": "id",  "flag": "🇮🇩", "regionLabel": "Indonesia",           "rss": "https://gamebrott.com/feed"},
    {"id": "kakuchopurei",  "name": "Kakuchopurei",   "region": "my",  "flag": "🇲🇾", "regionLabel": "Malaysia",            "rss": "https://kakuchopurei.com/feed"},
]

ARTICLES_PER_SOURCE = 3
HEADERS = {"User-Agent": "Mozilla/5.0 (SEAGamePulse RSS Reader)"}


def fetch_feed(source: dict) -> list[dict]:
    """RSS 피드를 가져와 기사 목록을 반환합니다."""
    try:
        response = requests.get(source["rss"], headers=HEADERS, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        articles = []
        for entry in feed.entries[:ARTICLES_PER_SOURCE]:
            # 날짜 파싱
            pub_date = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                pub_date = dt.strftime("%b %d, %Y")

            # 요약 텍스트 추출 (HTML 태그 제거)
            snippet = ""
            if hasattr(entry, "summary"):
                import re
                snippet = re.sub(r"<[^>]+>", "", entry.summary)
                snippet = " ".join(snippet.split())[:200]

            articles.append({
                "title":   entry.get("title", "(No title)").strip(),
                "link":    entry.get("link", "#"),
                "date":    pub_date,
                "snippet": snippet,
            })

        print(f"  ✅ {source['name']}: {len(articles)}개 기사 수집")
        return articles

    except Exception as e:
        print(f"  ❌ {source['name']} 실패: {e}")
        return []


def main():
    print(f"\n[SEA Game Pulse] RSS 수집 시작 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    output = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sources": [],
    }

    for source in SOURCES:
        articles = fetch_feed(source)
        output["sources"].append({
            "id":          source["id"],
            "name":        source["name"],
            "region":      source["region"],
            "flag":        source["flag"],
            "regionLabel": source["regionLabel"],
            "url":         source["rss"].replace("/feed", "").replace("/rss.chn", ""),
            "articles":    articles,
            "error":       len(articles) == 0,
        })

    # docs/ 폴더가 없으면 생성
    os.makedirs("docs", exist_ok=True)

    output_path = "docs/data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(s["articles"]) for s in output["sources"])
    print(f"\n✅ 완료: 총 {total}개 기사 → {output_path} 저장\n")


if __name__ == "__main__":
    main()
