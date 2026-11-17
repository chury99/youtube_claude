#!/usr/bin/env python3
"""
내 유튜브 채널 현황과 분석 데이터를 읽어 JSON으로 저장한다 (읽기 전용). 표준 라이브러리만 사용한다.
YouTube Data API v3(채널·영상 목록) + YouTube Analytics API v2(조회수, 시청 시간, 유입 경로 등).

로그인 토큰은 youtube_upload.py와 같은 config/youtube_token.json을 쓴다.
읽기 권한(youtube.readonly, yt-analytics.readonly)이 없으면 먼저 다시 로그인한다:
    python3 scripts/youtube_upload.py --auth

사용 예:
    python3 scripts/youtube_analytics.py                 # 최근 28일
    python3 scripts/youtube_analytics.py --days 90
    python3 scripts/youtube_analytics.py --out 6_reports/20261117_채널분석/channel_data.json

저장 위치 기본값: 6_reports/<YYYYMMDD>_채널분석/channel_data.json
각 분석 항목은 실패해도 전체가 멈추지 않고, 그 항목에 오류 메시지를 남긴다.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import youtube_upload as yu  # noqa: E402  (토큰·OAuth 공용)

ROOT = yu.ROOT
DATA_API = "https://www.googleapis.com/youtube/v3/"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
LAG_DAYS = 3  # 분석 데이터 집계 지연


def get(url, params, token):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
            msg = err.get("message", "") if isinstance(err, dict) else str(err)
        except Exception:
            msg = ""
        return {"_error": f"HTTP {e.code}: {msg}"}


def data(path, params, token):
    return get(DATA_API + path, params, token)


def report(token, start, end, metrics, dimensions=None, sort=None, max_results=None, filters=None):
    params = {"ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": metrics}
    if dimensions:
        params["dimensions"] = dimensions
    if sort:
        params["sort"] = sort
    if max_results:
        params["maxResults"] = max_results
    if filters:
        params["filters"] = filters
    res = get(ANALYTICS_API, params, token)
    if "_error" in res:
        return {"error": res["_error"], "metrics": metrics, "dimensions": dimensions}
    cols = [h["name"] for h in res.get("columnHeaders", [])]
    return {"columns": cols, "rows": [dict(zip(cols, r)) for r in res.get("rows", [])]}


def iso_duration_seconds(d):
    # PT1M5S → 65
    import re
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return None
    dd, h, mi, s = (int(x or 0) for x in m.groups())
    return dd * 86400 + h * 3600 + mi * 60 + s


def collect(days):
    need = {yu.SCOPE_READ, yu.SCOPE_ANALYTICS}
    if not need <= yu.granted_scopes():
        yu.fail("채널 분석 권한이 없습니다. 터미널에서 `python3 scripts/youtube_upload.py --auth`를 다시 실행해 주세요.\n"
                "   (읽기 전용 권한 youtube.readonly, yt-analytics.readonly가 추가됩니다)")
    token = yu.access_token()
    # Analytics는 2~3일 늦게 집계되므로 끝 날짜를 오늘-LAG일로 두고, 양끝 포함 정확히 days일로 맞춘다
    end = date.today() - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=days - 1)
    s, e = start.isoformat(), end.isoformat()
    out = {"generated": date.today().isoformat(),
           "period": {"start": s, "end": e, "days": days, "lag_days": LAG_DAYS}}

    # 채널
    ch = data("channels", {"part": "snippet,statistics,contentDetails,status", "mine": "true"}, token)
    if "_error" in ch or not ch.get("items"):
        yu.fail(f"채널 정보를 읽지 못했습니다: {ch.get('_error', '채널 없음')}")
    c = ch["items"][0]
    stats = c.get("statistics", {})
    out["channel"] = {
        "id": c["id"],
        "title": c["snippet"].get("title"),
        "created": c["snippet"].get("publishedAt"),
        "country": c["snippet"].get("country"),
        "subscribers": int(stats.get("subscriberCount", 0)),
        "hidden_subscribers": stats.get("hiddenSubscriberCount"),
        "total_views": int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
        "made_for_kids_channel": c.get("status", {}).get("madeForKids"),
    }
    uploads = c["contentDetails"]["relatedPlaylists"]["uploads"]

    # 영상 목록 (최대 200개)
    ids, page = [], None
    while len(ids) < 200:
        p = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
        if page:
            p["pageToken"] = page
        pl = data("playlistItems", p, token)
        if "_error" in pl:
            out["videos_error"] = pl["_error"]
            break
        ids += [it["contentDetails"]["videoId"] for it in pl.get("items", [])]
        page = pl.get("nextPageToken")
        if not page:
            break

    videos = []
    for i in range(0, len(ids), 50):
        vs = data("videos", {"part": "snippet,statistics,status,contentDetails",
                             "id": ",".join(ids[i:i + 50])}, token)
        for v in vs.get("items", []):
            st, sn, vs_ = v.get("status", {}), v.get("snippet", {}), v.get("statistics", {})
            videos.append({
                "id": v["id"],
                "title": sn.get("title"),
                "published": sn.get("publishedAt"),
                "duration_s": iso_duration_seconds(v.get("contentDetails", {}).get("duration")),
                "privacy": st.get("privacyStatus"),
                "upload_status": st.get("uploadStatus"),
                "made_for_kids": st.get("madeForKids"),
                "contains_synthetic_media": st.get("containsSyntheticMedia"),
                "views": int(vs_.get("viewCount", 0)),
                "likes": int(vs_.get("likeCount", 0)) if "likeCount" in vs_ else None,
                "comments": int(vs_.get("commentCount", 0)) if "commentCount" in vs_ else None,
                "category": sn.get("categoryId"),
                "tags": len(sn.get("tags", [])),
            })
    out["videos"] = videos

    # 분석 리포트 (기간 내)
    core = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,shares,subscribersGained,subscribersLost"
    out["analytics"] = {
        "totals": report(token, s, e, core),
        "daily": report(token, s, e, "views,estimatedMinutesWatched,subscribersGained,subscribersLost", "day", "day"),
        "by_video": report(token, s, e, core, "video", "-views", 50),
        "traffic_source": report(token, s, e, "views,estimatedMinutesWatched", "insightTrafficSourceType", "-views"),
        "content_type": report(token, s, e, "views,estimatedMinutesWatched,averageViewDuration", "creatorContentType", "-views"),
        "country": report(token, s, e, "views,estimatedMinutesWatched", "country", "-views", 10),
        "age_gender": report(token, s, e, "viewerPercentage", "ageGroup,gender"),
        "device": report(token, s, e, "views", "deviceType", "-views"),
        "subscribed_status": report(token, s, e, "views,averageViewDuration", "subscribedStatus"),
    }
    # 쇼츠 피드에서 넘기지 않고 본 조회(engagedViews)는 지원되는 경우에만
    ev = report(token, s, e, "views,engagedViews", "video", "-views", 50)
    out["analytics"]["engaged_views_by_video"] = ev
    # 실제로 숫자가 있는 마지막 날짜 (조회수 또는 시청 시간이 0보다 큰 날)
    days_with_data = [r["day"] for r in out["analytics"]["daily"].get("rows", [])
                      if (r.get("views") or 0) > 0 or (r.get("estimatedMinutesWatched") or 0) > 0]
    out["period"]["last_day_with_data"] = max(days_with_data) if days_with_data else None
    return out


def summary(d):
    c = d["channel"]
    kids = {True: "예", False: "아니요", None: "설정 안 함"}.get(c["made_for_kids_channel"], c["made_for_kids_channel"])
    print(f"채널: {c['title']} · 구독자 {c['subscribers']:,} · 총 조회수 {c['total_views']:,} · 영상 {c['video_count']}개"
          f" · 채널 아동용 기본값 {kids}")
    pr = d["period"]
    print(f"기간: {pr['start']} ~ {pr['end']} ({pr['days']}일, 집계 지연 {pr['lag_days']}일 제외)"
          f" · 숫자가 있는 마지막 날: {pr.get('last_day_with_data') or '없음'}")
    t = d["analytics"]["totals"]
    if t.get("rows"):
        r = t["rows"][0]
        print(f"기간 합계: 조회수 {int(r.get('views', 0)):,} · 시청 {int(r.get('estimatedMinutesWatched', 0)):,}분"
              f" · 평균 시청 {r.get('averageViewDuration')}초 · 평균 시청률 {r.get('averageViewPercentage')}%"
              f" · 구독 +{r.get('subscribersGained')} / -{r.get('subscribersLost')}")
    elif t.get("error"):
        print(f"기간 합계: 오류 {t['error']}")
    print(f"\n영상 {len(d['videos'])}개 (최근 업로드 순)")
    for v in d["videos"][:20]:
        mk = {True: "예", False: "아니요"}.get(v["made_for_kids"], "?")
        print(f"  {(v['published'] or '')[:10]} | {v['privacy']:<8} | 아동용 {mk:<3} | {v['duration_s']}초"
              f" | 조회 {v['views']:>6,} | {v['title'][:40]}")
    errs = [k for k, v in d["analytics"].items() if isinstance(v, dict) and v.get("error")]
    if errs:
        print(f"\nℹ️ 읽지 못한 분석 항목: {', '.join(errs)} (데이터가 없거나 지원되지 않는 항목)")


def main():
    ap = argparse.ArgumentParser(description="내 채널 현황·분석 데이터를 JSON으로 저장 (읽기 전용)")
    ap.add_argument("--days", type=int, default=28, help="분석 기간(일), 기본 28")
    ap.add_argument("--out", help="저장할 JSON 경로 (기본: 6_reports/<날짜>_채널분석/channel_data.json)")
    a = ap.parse_args()

    d = collect(a.days)
    if a.out:
        out = Path(a.out)
    else:
        # 같은 날 다시 실행해도 덮어쓰지 않는다: channel_data.json → channel_data_2.json …
        folder = ROOT / "6_reports" / f"{date.today():%Y%m%d}_채널분석"
        out, n = folder / "channel_data.json", 2
        while out.exists():
            out, n = folder / f"channel_data_{n}.json", n + 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    summary(d)
    print(f"\n✅ 저장: {out.relative_to(ROOT) if out.is_absolute() and ROOT in out.parents else out}")


if __name__ == "__main__":
    main()
