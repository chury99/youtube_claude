#!/usr/bin/env python3
"""
AI로 만든 유튜브 인기 영상 수집기

YouTube Data API v3로 키워드별 영상을 조회수 순으로 검색하고,
조회수·구독자 수·아웃라이어 비율 등을 CSV로 저장한다.
표준 라이브러리만 사용하므로 별도 설치가 필요 없다.

사용 예:
    python3 youtube_ai_trends.py
    python3 youtube_ai_trends.py --days 30 --region KR --lang ko
    python3 youtube_ai_trends.py -k "AI 애니메이션" "Veo 3" --max 50 --shorts-only
"""

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_BASE = "https://www.googleapis.com/youtube/v3"
SCRIPT_DIR = Path(__file__).resolve().parent
KEY_FILE = SCRIPT_DIR / "config" / "google_api_keys.json"

DEFAULT_KEYWORDS = [
    "AI generated video",
    "AI animation",
    "AI short film",
    "Sora AI",
    "Veo 3",
    "Kling AI",
    "AI 애니메이션",
    "AI 영상",
]

# Shorts 판별 기준(초). 유튜브 Shorts 최대 길이가 3분이다.
SHORTS_MAX_SECONDS = 180


def load_api_key():
    """config/google_api_keys.json 파일의 youtube_api_key 값을 읽는다."""
    if not KEY_FILE.exists():
        return None
    try:
        data = json.loads(KEY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"❌ {KEY_FILE} 파일 형식이 잘못되었습니다 (줄 {e.lineno}): {e.msg}")
    key = str(data.get("youtube_api_key", "")).strip()
    if not key or key.startswith("여기에"):
        return None
    return key


def api_get(endpoint, params, api_key):
    """YouTube API GET 요청. 오류 시 원인을 알기 쉽게 출력하고 종료한다."""
    query = urllib.parse.urlencode({**params, "key": api_key})
    url = f"{API_BASE}/{endpoint}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)["error"]
            reason = err.get("errors", [{}])[0].get("reason", "")
            message = err.get("message", "")
        except Exception:
            reason, message = "", str(e)
        if reason == "quotaExceeded":
            sys.exit("❌ 오늘 API 할당량을 모두 썼습니다. 내일(태평양 시간 자정) 초기화됩니다.")
        if reason in ("keyInvalid", "badRequest") and "key" in message.lower():
            sys.exit("❌ API 키가 올바르지 않습니다. config/google_api_keys.json의 youtube_api_key를 확인하세요.")
        sys.exit(f"❌ API 오류 ({e.code} {reason}): {message}")
    except urllib.error.URLError as e:
        sys.exit(f"❌ 네트워크 오류: {e.reason}")


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def parse_duration(iso):
    """ISO 8601 길이(PT1H2M3S)를 초로 변환한다."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def format_duration(seconds):
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def search_videos(keyword, args, api_key):
    """키워드로 조회수 순 검색. 50개씩 페이지를 넘기며 최대 args.max개까지 모은다.
    search.list는 호출 1회당 100 유닛이 든다."""
    published_after = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "part": "id",
        "q": keyword,
        "type": "video",
        "order": "viewCount",
        "publishedAfter": published_after,
        "maxResults": 50,
    }
    if args.region:
        params["regionCode"] = args.region
    if args.lang:
        params["relevanceLanguage"] = args.lang
    if args.shorts_only:
        params["videoDuration"] = "short"  # 4분 미만, 이후 3분 이하로 다시 거른다

    ids, page_token = [], None
    while len(ids) < args.max:
        if page_token:
            params["pageToken"] = page_token
        data = api_get("search", params, api_key)
        ids += [it["id"]["videoId"] for it in data.get("items", [])]
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids[: args.max]


def fetch_video_details(video_ids, api_key):
    """영상 상세 정보(조회수, 길이 등). 50개당 1 유닛."""
    details = {}
    for batch in chunks(video_ids, 50):
        data = api_get(
            "videos",
            {"part": "snippet,statistics,contentDetails", "id": ",".join(batch)},
            api_key,
        )
        for it in data.get("items", []):
            details[it["id"]] = it
    return details


def fetch_channel_subscribers(channel_ids, api_key):
    """채널 구독자 수. 50개당 1 유닛. 구독자 수를 숨긴 채널은 None."""
    subs = {}
    for batch in chunks(channel_ids, 50):
        data = api_get("channels", {"part": "statistics", "id": ",".join(batch)}, api_key)
        for it in data.get("items", []):
            st = it.get("statistics", {})
            subs[it["id"]] = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0))
    return subs


def build_rows(keyword_hits, details, subs, shorts_only):
    now = datetime.now(timezone.utc)
    rows = []
    for vid, keywords in keyword_hits.items():
        v = details.get(vid)
        if not v:
            continue  # 삭제·비공개 영상
        sn, st = v["snippet"], v.get("statistics", {})
        seconds = parse_duration(v["contentDetails"].get("duration"))
        is_short = 0 < seconds <= SHORTS_MAX_SECONDS
        if shorts_only and not is_short:
            continue

        views = int(st.get("viewCount", 0))
        likes = int(st["likeCount"]) if "likeCount" in st else None
        comments = int(st["commentCount"]) if "commentCount" in st else None
        published = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        days_live = max((now - published).total_seconds() / 86400, 1)
        sub_count = subs.get(sn["channelId"])

        rows.append({
            "title": sn["title"],
            "channel": sn["channelTitle"],
            "views": views,
            "subscribers": sub_count if sub_count is not None else "",
            # 조회수 ÷ 구독자: 1보다 훨씬 크면 채널 덕이 아니라 포맷이 먹힌 영상
            "outlier_ratio": round(views / sub_count, 2) if sub_count else "",
            "views_per_day": round(views / days_live),
            "likes": likes if likes is not None else "",
            "comments": comments if comments is not None else "",
            "like_rate_%": round(likes / views * 100, 2) if likes is not None and views else "",
            "duration": format_duration(seconds),
            "is_short": "Y" if is_short else "N",
            "published": published.strftime("%Y-%m-%d"),
            "matched_keywords": " | ".join(keywords),
            "url": f"https://www.youtube.com/watch?v={vid}" if not is_short
                   else f"https://www.youtube.com/shorts/{vid}",
        })
    return rows


def main():
    p = argparse.ArgumentParser(description="AI로 만든 유튜브 인기 영상을 수집해 CSV로 저장합니다.")
    p.add_argument("-k", "--keywords", nargs="+", default=DEFAULT_KEYWORDS,
                   help="검색 키워드 목록 (기본: AI 관련 키워드 8개)")
    p.add_argument("--days", type=int, default=90, help="최근 며칠 이내 업로드 (기본 90)")
    p.add_argument("--max", type=int, default=50,
                   help="키워드당 최대 영상 수 (기본 50, 50개마다 100 유닛)")
    p.add_argument("--region", default=None, help="국가 코드, 예: KR, US")
    p.add_argument("--lang", default=None, help="언어 코드, 예: ko, en")
    p.add_argument("--shorts-only", action="store_true", help="Shorts(3분 이하)만 수집")
    p.add_argument("--sort", default="views",
                   choices=["views", "outlier_ratio", "views_per_day"],
                   help="CSV 정렬 기준 (기본 views)")
    p.add_argument("-o", "--output", default=None, help="저장할 CSV 경로 (기본: results/ 폴더)")
    args = p.parse_args()

    api_key = load_api_key()
    if not api_key:
        sys.exit(
            "❌ API 키가 없습니다.\n"
            "   1) config/google_api_keys.json.example 파일을 config/google_api_keys.json으로 복사하고\n"
            "   2) youtube_api_key 값에 발급받은 키를 입력하세요.\n"
            "   발급 방법은 README.md를 참고하세요."
        )

    pages_per_kw = -(-args.max // 50)
    print(f"🔎 키워드 {len(args.keywords)}개 · 최근 {args.days}일 · 키워드당 최대 {args.max}개")
    print(f"   예상 사용량: 약 {len(args.keywords) * pages_per_kw * 100 + 10} 유닛 (하루 무료 10,000)\n")

    keyword_hits = {}  # video_id -> [매칭된 키워드들]
    for kw in args.keywords:
        ids = search_videos(kw, args, api_key)
        print(f"  • {kw}: {len(ids)}개")
        for vid in ids:
            keyword_hits.setdefault(vid, []).append(kw)

    if not keyword_hits:
        sys.exit("검색 결과가 없습니다. 키워드나 기간(--days)을 바꿔 보세요.")

    details = fetch_video_details(list(keyword_hits), api_key)
    channel_ids = list({v["snippet"]["channelId"] for v in details.values()})
    subs = fetch_channel_subscribers(channel_ids, api_key)

    rows = build_rows(keyword_hits, details, subs, args.shorts_only)
    rows.sort(key=lambda r: r[args.sort] if r[args.sort] != "" else -1, reverse=True)

    if args.output:
        out = Path(args.output)
    else:
        out = SCRIPT_DIR / "results" / f"ai_videos_{datetime.now():%Y%m%d_%H%M}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: 엑셀에서 한글이 깨지지 않도록 BOM 포함
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["title"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ 영상 {len(rows)}개 저장: {out}\n")
    print(f"🏆 상위 10개 ({args.sort} 기준)")
    for i, r in enumerate(rows[:10], 1):
        ratio = f" · 아웃라이어 {r['outlier_ratio']}x" if r["outlier_ratio"] != "" else ""
        print(f"{i:2}. {r['views']:>12,}회{ratio}  {r['title'][:50]}")
        print(f"    {r['channel']} · {r['published']} · {r['url']}")


if __name__ == "__main__":
    main()
