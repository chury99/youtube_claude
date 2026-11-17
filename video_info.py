#!/usr/bin/env python3
"""
유튜브 영상 1개의 상세 정보(제목, 설명, 태그, 길이, 통계, 썸네일)를 출력한다.
API 키는 config/google_api_keys.json에서 읽고 화면에 출력하지 않는다.

사용 예:
    python3 video_info.py https://www.youtube.com/shorts/a4tHx-tr5_g
    python3 video_info.py a4tHx-tr5_g --thumbnail results/thumb.jpg
"""

import argparse
import json
import re
import sys
import urllib.request

from youtube_ai_trends import api_get, format_duration, load_api_key, parse_duration


def extract_id(text):
    m = re.search(r"(?:v=|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    sys.exit(f"❌ 영상 ID를 찾을 수 없습니다: {text}")


def main():
    p = argparse.ArgumentParser(description="유튜브 영상 상세 정보를 JSON으로 출력합니다. (1 유닛)")
    p.add_argument("video", help="영상 URL 또는 11자리 ID")
    p.add_argument("--thumbnail", help="썸네일 이미지를 저장할 경로 (선택)")
    args = p.parse_args()

    api_key = load_api_key()
    if not api_key:
        sys.exit("❌ API 키가 없습니다. config/google_api_keys.json을 확인하세요.")

    vid = extract_id(args.video)
    data = api_get("videos", {"part": "snippet,statistics,contentDetails,topicDetails", "id": vid}, api_key)
    if not data.get("items"):
        sys.exit(f"❌ 영상을 찾을 수 없습니다 (삭제·비공개): {vid}")
    v = data["items"][0]
    sn, st = v["snippet"], v.get("statistics", {})
    seconds = parse_duration(v["contentDetails"].get("duration"))
    thumbs = sn.get("thumbnails", {})
    thumb_url = next((thumbs[k]["url"] for k in ("maxres", "standard", "high", "medium", "default")
                      if k in thumbs), None)

    info = {
        "id": vid,
        "title": sn.get("title"),
        "channel": sn.get("channelTitle"),
        "published": sn.get("publishedAt", "")[:10],
        "duration": format_duration(seconds),
        "duration_seconds": seconds,
        "views": int(st.get("viewCount", 0)),
        "likes": int(st["likeCount"]) if "likeCount" in st else None,
        "comments": int(st["commentCount"]) if "commentCount" in st else None,
        "tags": sn.get("tags", []),
        "category_id": sn.get("categoryId"),
        "language": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"),
        "topics": v.get("topicDetails", {}).get("topicCategories", []),
        "thumbnail_url": thumb_url,
        "description": sn.get("description", ""),
    }

    if args.thumbnail and thumb_url:
        with urllib.request.urlopen(thumb_url, timeout=30) as resp, open(args.thumbnail, "wb") as f:
            f.write(resp.read())
        info["thumbnail_saved"] = args.thumbnail

    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
