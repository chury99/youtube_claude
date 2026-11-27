#!/usr/bin/env python3
"""
완성 영상을 유튜브에 업로드한다 (YouTube Data API v3, OAuth). 표준 라이브러리만 사용한다.
안전을 위해 공개 상태는 private(비공개) 또는 unlisted(일부 공개)만 허용한다.
전체 공개는 사용자가 YouTube Studio에서 확인한 뒤 직접 바꾼다.

필요한 파일 (config/, 깃에 올리지 않음):
    config/youtube_oauth_client.json  Google Cloud에서 받은 OAuth 클라이언트(데스크톱 앱) JSON
    config/youtube_token.json         --auth 한 번 실행하면 자동 생성 (갱신 토큰 저장)
키와 토큰 값은 화면에 출력하지 않는다.

사용 예:
    python3 scripts/youtube_upload.py --auth                         # 처음 한 번: 브라우저 로그인 후 토큰 저장
    python3 scripts/youtube_upload.py --check                        # 설정·토큰 상태만 확인 (업로드 안 함)
    python3 scripts/youtube_upload.py 5_videos/shorts/X/X.mp4 --meta 5_videos/shorts/X/upload.json
    python3 scripts/youtube_upload.py 5_videos/shorts/X/X.mp4 --meta 5_videos/shorts/X/upload.json --dry-run
    python3 scripts/youtube_upload.py --playlist-sync                # 이미 올린 영상을 재생목록에 한 번에 넣기 (빠진 것만)

재생목록 (youtube.force-ssl 권한 필요, 없으면 건너뛰고 업로드는 그대로 성공):
    업로드가 끝나면 영상 경로로 종류를 정해 재생목록에 자동으로 넣는다.
    5_videos/longform/... → 롱폼 재생목록, 5_videos/shorts/... → 쇼츠 재생목록 (--playlist로 바꾸거나 none으로 끔)
    재생목록이 없으면 처음 한 번 공개 재생목록으로 만들고 ID를 config/youtube_playlists.json에 저장해 다시 쓴다.
    넣은 뒤 설명(번역 포함) 맨 위에 재생목록 페이지 링크(playlist?list=<재생목록>)를 넣는다.

upload.json 형식:
{
  "title": "제목 (100자 이하)",
  "description": "설명 (5000자 이하, 해시태그 포함 가능)",
  "tags": ["태그1", "태그2"],
  "categoryId": "24",
  "defaultLanguage": "en",
  "defaultAudioLanguage": "zxx",        # 선택: 오디오 언어 (zxx = 말소리 없음, 거부되면 자동으로 en)
  "localizations": {                    # 선택: 언어별 제목·설명 번역
    "es": {"title": "…", "description": "…"}
  },
  "madeForKids": false,
  "containsSyntheticMedia": true,
  "privacyStatus": "private",
  "thumbnail": "thumbnail.jpg"          # 선택: upload.json 기준 경로, JPG/PNG 2MB 이하 (실패해도 업로드는 유지)
}
결과는 upload.json 옆에 upload_result.json으로 저장한다. 이미 있으면 중복 업로드를 막는다 (--force로 무시).
"""

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 저장소 루트
CLIENT_FILE = ROOT / "config" / "youtube_oauth_client.json"
TOKEN_FILE = ROOT / "config" / "youtube_token.json"
SCOPE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
SCOPE_READ = "https://www.googleapis.com/auth/youtube.readonly"
SCOPE_ANALYTICS = "https://www.googleapis.com/auth/yt-analytics.readonly"
SCOPE_MANAGE = "https://www.googleapis.com/auth/youtube.force-ssl"
# 업로드 + 채널 읽기 + 분석 읽기 + 관리(재생목록 만들기·영상 넣기에 사용)
SCOPE = " ".join([SCOPE_UPLOAD, SCOPE_READ, SCOPE_ANALYTICS, SCOPE_MANAGE])
PLAYLIST_FILE = ROOT / "config" / "youtube_playlists.json"
API = "https://www.googleapis.com/youtube/v3/"
# 재생목록 이름·설명 (사용자 기준 2026-11-26: 롱폼·쇼츠 분리, 공개 재생목록)
PLAYLISTS = {
    "longform": {"title": "Knitted Stories for Kids | Full Episodes",
                 "description": "Full knitted animal stories for toddlers and preschoolers — longer episodes "
                                "and weekly compilations. Gentle, cozy, made with AI (Google Veo)."},
    "shorts": {"title": "Knitted Stories for Kids | Shorts",
               "description": "Short knitted animal moments for toddlers and preschoolers. "
                              "Gentle, cozy, made with AI (Google Veo)."},
}
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
              "?uploadType=resumable&part=snippet,status")
UPLOAD_URL_LOC = UPLOAD_URL + ",localizations"
THUMB_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId="
CHUNK = 8 * 1024 * 1024
ALLOWED_PRIVACY = ("private", "unlisted")


def fail(msg):
    sys.exit(f"❌ {msg}")


# ---------- OAuth ----------

def load_client():
    if not CLIENT_FILE.exists():
        fail(f"{CLIENT_FILE.relative_to(ROOT)} 파일이 없습니다. docs/youtube_upload_setup.md를 따라 OAuth 클라이언트 JSON을 넣어 주세요.")
    try:
        data = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"{CLIENT_FILE.name} 형식이 잘못되었습니다 (줄 {e.lineno}).")
    info = data.get("installed") or data.get("web")
    if not info or not info.get("client_id") or not info.get("client_secret"):
        fail(f"{CLIENT_FILE.name}에 client_id/client_secret이 없습니다. '데스크톱 앱' 유형으로 만든 JSON인지 확인하세요.")
    if info["client_id"].startswith("여기에") or info["client_secret"].startswith("여기에"):
        fail(f"{CLIENT_FILE.name}이 예시 값 그대로입니다. Google Cloud에서 받은 JSON으로 바꿔 주세요.")
    if "installed" not in data:
        fail("OAuth 클라이언트 유형이 '데스크톱 앱'이 아닙니다. Google Cloud에서 '데스크톱 앱'으로 다시 만들어 주세요.")
    return info["client_id"], info["client_secret"]


def post_form(url, fields):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)
        except Exception:
            err = {}
        return {"_error": e.code, "error": err.get("error"), "error_description": err.get("error_description")}


def save_token(tok):
    TOKEN_FILE.write_text(json.dumps(tok, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass


def run_auth():
    client_id, client_secret = load_client()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                result.update({k: v[0] for k, v in q.items()})
                ok = "code" in q and q.get("state", [""])[0] == state
                body = ("인증 완료. 이 창을 닫고 터미널로 돌아가세요." if ok
                        else "인증 실패. 터미널 메시지를 확인하세요.")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"<meta charset='utf-8'><h2>{body}</h2>".encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
    })
    print("브라우저에서 영상을 올릴 채널의 Google 계정으로 로그인하고 권한을 허용해 주세요.")
    print("브라우저가 안 열리면 아래 주소를 직접 여세요:\n" + url)
    webbrowser.open(url)

    t = threading.Thread(target=lambda: [server.handle_request() for _ in range(20) if not result])
    t.daemon = True
    t.start()
    t.join(timeout=300)
    server.server_close()

    if not result:
        fail("5분 안에 인증이 끝나지 않았습니다. 다시 실행해 주세요.")
    if "error" in result:
        fail(f"인증이 거부되었습니다: {result['error']}")
    if result.get("state") != state:
        fail("state 값이 맞지 않습니다. 다시 실행해 주세요.")

    tok = post_form(TOKEN_URL, {
        "code": result["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    if "_error" in tok or "refresh_token" not in tok:
        fail(f"토큰 발급 실패: {tok.get('error')} {tok.get('error_description') or ''}")
    save_token({"refresh_token": tok["refresh_token"], "scope": tok.get("scope", SCOPE),
                "created": time.strftime("%Y-%m-%d %H:%M:%S")})
    print(f"✅ 인증 완료. 토큰을 {TOKEN_FILE.relative_to(ROOT)}에 저장했습니다 (값은 출력하지 않음).")


def granted_scopes():
    """저장된 토큰에 허용된 권한 목록 (값은 출력하지 않음)."""
    if not TOKEN_FILE.exists():
        return set()
    return set(json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("scope", "").split())


def access_token():
    client_id, client_secret = load_client()
    if not TOKEN_FILE.exists():
        fail("업로드 토큰이 없습니다. 먼저 `python3 scripts/youtube_upload.py --auth`를 실행해 주세요.")
    refresh = json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("refresh_token")
    if not refresh:
        fail(f"{TOKEN_FILE.name}에 refresh_token이 없습니다. --auth를 다시 실행해 주세요.")
    tok = post_form(TOKEN_URL, {"client_id": client_id, "client_secret": client_secret,
                                "refresh_token": refresh, "grant_type": "refresh_token"})
    if "_error" in tok:
        if tok.get("error") == "invalid_grant":
            fail("토큰이 만료되었거나 취소되었습니다. `python3 scripts/youtube_upload.py --auth`를 다시 실행해 주세요.\n"
                 "   (OAuth 동의 화면이 '테스트' 상태면 토큰이 7일 뒤 만료됩니다. '프로덕션'으로 바꾸면 해결됩니다.)")
        fail(f"토큰 갱신 실패: {tok.get('error')} {tok.get('error_description') or ''}")
    return tok["access_token"]


# ---------- 메타데이터 ----------

def build_body(meta):
    title = str(meta.get("title", "")).strip()
    desc = str(meta.get("description", ""))
    tags = [str(t).strip().lstrip("#") for t in meta.get("tags", []) if str(t).strip()]
    privacy = meta.get("privacyStatus", "private")

    problems = []
    if not title:
        problems.append("title이 비어 있습니다.")
    if len(title) > 100:
        problems.append(f"title이 {len(title)}자입니다 (100자 이하).")
    if "<" in title or ">" in title or "<" in desc or ">" in desc:
        problems.append("title/description에 < > 문자는 쓸 수 없습니다.")
    if len(desc.encode("utf-8")) > 5000:
        problems.append("description이 5000바이트를 넘습니다.")
    tag_len = sum(len(t) + (2 if " " in t else 0) for t in tags) + max(len(tags) - 1, 0)
    if tag_len > 500:
        problems.append(f"tags 전체 길이가 {tag_len}자입니다 (500자 이하).")
    if privacy not in ALLOWED_PRIVACY:
        problems.append(f"privacyStatus는 {ALLOWED_PRIVACY} 중 하나여야 합니다. 전체 공개는 YouTube Studio에서 직접 바꿔 주세요.")
    default_lang = meta.get("defaultLanguage")
    locs = meta.get("localizations") or {}
    if not isinstance(locs, dict):
        problems.append("localizations는 {\"언어코드\": {\"title\": ..., \"description\": ...}} 형식이어야 합니다.")
        locs = {}
    if locs and not default_lang:
        problems.append("localizations를 쓰려면 defaultLanguage가 있어야 합니다.")
    clean_locs = {}
    for lang, loc in locs.items():
        if lang == default_lang:
            problems.append(f"localizations에 기본 언어({lang})는 넣지 않습니다.")
            continue
        if not isinstance(loc, dict):
            problems.append(f"localizations.{lang} 형식이 잘못됐습니다.")
            continue
        lt, ld = str(loc.get("title", "")).strip(), str(loc.get("description", ""))
        if not lt:
            problems.append(f"localizations.{lang}.title이 비어 있습니다.")
        if len(lt) > 100:
            problems.append(f"localizations.{lang}.title이 {len(lt)}자입니다 (100자 이하).")
        if any(c in lt + ld for c in "<>"):
            problems.append(f"localizations.{lang}에 < > 문자는 쓸 수 없습니다.")
        if len(ld.encode("utf-8")) > 5000:
            problems.append(f"localizations.{lang}.description이 5000바이트를 넘습니다.")
        clean_locs[lang] = {"title": lt, "description": ld}
    for key in ("madeForKids", "containsSyntheticMedia"):
        if not isinstance(meta.get(key), bool):
            problems.append(f"{key}를 true/false로 꼭 정해 주세요.")
    if problems:
        fail("upload.json 확인 필요:\n   - " + "\n   - ".join(problems))

    snippet = {"title": title, "description": desc, "tags": tags,
               "categoryId": str(meta.get("categoryId", "24"))}
    if default_lang:
        snippet["defaultLanguage"] = default_lang
        snippet["defaultAudioLanguage"] = meta.get("defaultAudioLanguage") or default_lang
    status = {"privacyStatus": privacy,
              "selfDeclaredMadeForKids": meta["madeForKids"],
              "containsSyntheticMedia": meta["containsSyntheticMedia"],
              "embeddable": True}
    body = {"snippet": snippet, "status": status}
    if clean_locs:
        body["localizations"] = clean_locs
    return body


# ---------- 업로드 ----------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """재개 업로드의 308(일부 받음) 응답을 리다이렉트로 따라가지 않게 한다."""
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def api_error(e):
    try:
        err = json.load(e).get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        return f"HTTP {e.code} {reason}: {err.get('message', '')}"
    except Exception:
        return f"HTTP {e.code}"


def start_session(body, token, size):
    url = UPLOAD_URL_LOC if body.get("localizations") else UPLOAD_URL
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": "video/*",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.headers["Location"]


def upload(video, body, token, notes):
    """notes: 대체 처리(오디오 언어 변경, 번역 제외)를 기록할 리스트. body는 실제 보낸 값으로 바뀐다."""
    size = video.stat().st_size
    session = None
    for _ in range(3):
        try:
            session = start_session(body, token, size)
            break
        except urllib.error.HTTPError as e:
            msg = api_error(e)
            if "quotaExceeded" in msg or "uploadLimitExceeded" in msg:
                fail(f"오늘 업로드 한도를 넘었습니다. 내일 다시 시도해 주세요. ({msg})")
            low = msg.lower()
            sn = body["snippet"]
            if (e.code == 400 and "language" in low and sn.get("defaultAudioLanguage")
                    and sn["defaultAudioLanguage"] != sn.get("defaultLanguage")):
                notes.append(f"오디오 언어 {sn['defaultAudioLanguage']}가 거부되어 {sn.get('defaultLanguage')}로 바꿔 올림 ({msg})")
                sn["defaultAudioLanguage"] = sn.get("defaultLanguage")
                continue
            if e.code in (400, 403) and body.get("localizations"):
                notes.append(f"번역(localizations)이 거부되어 빼고 올림: {', '.join(body['localizations'])} ({msg}). Studio > 언어에서 직접 추가 가능")
                body.pop("localizations")
                continue
            fail(f"업로드 시작 실패: {msg}")
    if not session:
        fail("업로드를 시작하지 못했습니다.")

    sent, retries = 0, 0
    with video.open("rb") as f:
        while sent < size:
            f.seek(sent)
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            put = urllib.request.Request(session, data=chunk, method="PUT", headers={
                "Authorization": f"Bearer {token}",
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {sent}-{end}/{size}",
            })
            try:
                with OPENER.open(put, timeout=300) as r:
                    return json.load(r)  # 200/201 = 업로드 완료
            except urllib.error.HTTPError as e:
                if e.code == 308:  # 일부 받음 → 이어서 보냄
                    rng = e.headers.get("Range")
                    sent = int(rng.split("-")[1]) + 1 if rng else 0
                    retries = 0
                    print(f"   업로드 중… {sent * 100 // size}%")
                    continue
                if e.code in (500, 502, 503, 504) and retries < 5:
                    retries += 1
                    time.sleep(2 ** retries)
                    continue
                fail(f"업로드 실패: {api_error(e)}")
            except (urllib.error.URLError, TimeoutError) as e:
                if retries < 5:
                    retries += 1
                    time.sleep(2 ** retries)
                    # 서버가 받은 위치 확인
                    probe = urllib.request.Request(session, data=b"", method="PUT", headers={
                        "Authorization": f"Bearer {token}", "Content-Range": f"bytes */{size}"})
                    try:
                        with OPENER.open(probe, timeout=60) as r:
                            return json.load(r)
                    except urllib.error.HTTPError as pe:
                        if pe.code == 308:
                            rng = pe.headers.get("Range")
                            sent = int(rng.split("-")[1]) + 1 if rng else 0
                    except Exception:
                        pass
                    continue
                fail(f"네트워크 오류로 업로드 실패: {e}")
    fail("업로드가 완료 응답 없이 끝났습니다.")


def set_thumbnail(vid, path, token):
    """썸네일을 올린다. 실패해도 업로드는 그대로 두고 이유만 돌려준다."""
    ctype = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    req = urllib.request.Request(THUMB_URL + urllib.parse.quote(vid), data=path.read_bytes(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            json.load(r)
        return {"set": True, "file": str(path)}
    except urllib.error.HTTPError as e:
        return {"set": False, "file": str(path), "reason": api_error(e)}
    except (urllib.error.URLError, TimeoutError) as e:
        return {"set": False, "file": str(path), "reason": str(e)}


def verify_settings(vid, body, token):
    """업로드 후 영상 설정을 다시 읽어 보낸 값과 비교한다 (youtube.readonly 권한 필요)."""
    if SCOPE_READ not in granted_scopes():
        return {"checked": False, "reason": "읽기 권한 없음 (--auth 다시 실행하면 확인 가능)"}
    url = ("https://www.googleapis.com/youtube/v3/videos?part=status,snippet,localizations&id="
           + urllib.parse.quote(vid))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            items = json.load(r).get("items", [])
    except urllib.error.HTTPError as e:
        return {"checked": False, "reason": api_error(e)}
    if not items:
        return {"checked": False, "reason": "영상 정보를 아직 읽을 수 없음 (처리 중일 수 있음)"}
    st, sn = items[0].get("status", {}), items[0].get("snippet", {})
    got = {"madeForKids": st.get("madeForKids"),
           "containsSyntheticMedia": st.get("containsSyntheticMedia"),
           "categoryId": sn.get("categoryId"),
           "privacyStatus": st.get("privacyStatus"),
           "defaultLanguage": sn.get("defaultLanguage"),
           "defaultAudioLanguage": sn.get("defaultAudioLanguage"),
           "localizations": sorted((items[0].get("localizations") or {}).keys())}
    warnings = []
    if got["madeForKids"] != body["status"]["selfDeclaredMadeForKids"]:
        warnings.append(f"아동용 값이 다릅니다 (보냄 {body['status']['selfDeclaredMadeForKids']}, 읽음 {got['madeForKids']}). Studio에서 확인하세요.")
    if got["containsSyntheticMedia"] != body["status"]["containsSyntheticMedia"]:
        warnings.append(f"AI 합성 공개 값이 확인되지 않습니다 (보냄 {body['status']['containsSyntheticMedia']}, 읽음 {got['containsSyntheticMedia']}). "
                        "Studio > 세부정보 > '변경되었거나 합성된 콘텐츠'를 직접 확인하세요.")
    if got["categoryId"] != body["snippet"]["categoryId"]:
        warnings.append(f"카테고리가 다릅니다 (보냄 {body['snippet']['categoryId']}, 읽음 {got['categoryId']}).")
    want_aud = body["snippet"].get("defaultAudioLanguage")
    if want_aud and got["defaultAudioLanguage"] != want_aud:
        warnings.append(f"오디오 언어가 다릅니다 (보냄 {want_aud}, 읽음 {got['defaultAudioLanguage']}).")
    missing = sorted(set(body.get("localizations", {})) - set(got["localizations"]))
    if missing:
        warnings.append(f"번역이 확인되지 않습니다: {', '.join(missing)}. Studio > 언어에서 확인하세요.")
    return {"checked": True, "read_back": got, "warnings": warnings}


# ---------- 재생목록 ----------

def api_json(method, path, token, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json; charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def video_kind(video):
    """영상 경로로 재생목록 종류를 정한다: 5_videos/longform → longform, 5_videos/shorts → shorts."""
    parts = Path(video).resolve().parts
    for k in PLAYLISTS:
        if "5_videos" in parts and k in parts:
            return k
    return None


def load_playlists():
    return json.loads(PLAYLIST_FILE.read_text(encoding="utf-8")) if PLAYLIST_FILE.exists() else {}


def ensure_playlist(kind, token, recreate=False):
    """재생목록 ID를 돌려준다. 없으면 공개 재생목록을 만들고 ID를 저장한다."""
    saved = load_playlists()
    if saved.get(kind, {}).get("id") and not recreate:
        return saved[kind]["id"]
    info = PLAYLISTS[kind]
    res = api_json("POST", "playlists?part=snippet,status", token, {
        "snippet": {"title": info["title"], "description": info["description"], "defaultLanguage": "en"},
        "status": {"privacyStatus": "public"}})
    saved[kind] = {"id": res["id"], "title": info["title"], "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    PLAYLIST_FILE.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   재생목록을 새로 만들었습니다: {info['title']} (https://www.youtube.com/playlist?list={res['id']})")
    return res["id"]


def playlist_video_ids(pid, token):
    ids, page = set(), ""
    while True:
        res = api_json("GET", f"playlistItems?part=contentDetails&maxResults=50&playlistId={pid}"
                              + (f"&pageToken={page}" if page else ""), token)
        ids |= {i["contentDetails"]["videoId"] for i in res.get("items", [])}
        page = res.get("nextPageToken")
        if not page:
            return ids


def add_to_playlist(vid, kind, token):
    """영상을 종류에 맞는 재생목록에 넣는다. 실패해도 업로드는 그대로 두고 이유만 돌려준다."""
    if SCOPE_MANAGE not in granted_scopes():
        return {"added": False, "kind": kind,
                "reason": "재생목록 권한 없음 (`python3 scripts/youtube_upload.py --auth`를 다시 실행하면 자동으로 넣음)"}
    for attempt in range(2):
        try:
            pid = ensure_playlist(kind, token, recreate=attempt > 0)
            api_json("POST", "playlistItems?part=snippet", token, {"snippet": {
                "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}})
            return {"added": True, "kind": kind, "playlist_id": pid,
                    "playlist_url": f"https://www.youtube.com/playlist?list={pid}"}
        except urllib.error.HTTPError as e:
            msg = api_error(e)
            if e.code == 404 and "playlistNotFound" in msg and attempt == 0:
                time.sleep(5)  # 방금 만든 재생목록이 아직 안 보일 수 있어 잠시 기다렸다가
                try:           # 같은 재생목록으로 한 번 더 넣어 보고, 그래도 없으면 새로 만든다
                    api_json("POST", "playlistItems?part=snippet", token, {"snippet": {
                        "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}})
                    return {"added": True, "kind": kind, "playlist_id": pid,
                            "playlist_url": f"https://www.youtube.com/playlist?list={pid}"}
                except urllib.error.HTTPError:
                    continue
            return {"added": False, "kind": kind, "reason": msg}
        except (urllib.error.URLError, TimeoutError) as e:
            return {"added": False, "kind": kind, "reason": str(e)}
    return {"added": False, "kind": kind, "reason": "재생목록을 찾을 수 없음"}


# 설명란 맨 위에 넣는 재생목록 링크 문구 (사용자 기준 2026-11-26: 다 보면 다음 영상이 이어지게)
# 영상 주소(watch?v=…&list=…)는 누르면 같은 영상만 다시 나와서, 재생목록 페이지 주소를 쓴다 (2026-11-26 사용자 확인)
LINK_TEXT = {"longform": "▶ Watch all episodes in order:", "shorts": "▶ Watch more knitted Shorts in a row:"}


def replace_link_line(desc, line):
    """설명 맨 위의 기존 재생목록 링크 줄(LINK_TEXT로 시작)을 새 줄로 바꾸거나, 없으면 맨 위에 넣는다."""
    first, sep, rest = desc.partition("\n")
    if any(first.startswith(x) for x in LINK_TEXT.values()):
        return line + sep + rest
    return line + "\n\n" + desc


def add_playlist_link(vid, pid, kind, token):
    """영상 설명(번역 포함) 맨 위에 재생목록 페이지 링크를 넣는다. 옛 링크 줄은 바꾸고, 이미 같으면 건너뛴다."""
    url = f"https://www.youtube.com/playlist?list={pid}"
    line = f"{LINK_TEXT[kind]} {url}"
    try:
        items = api_json("GET", f"videos?part=snippet,localizations&id={vid}", token).get("items", [])
        if not items:
            return {"linked": False, "reason": "영상 정보를 읽을 수 없음 (처리 중일 수 있음)"}
        sn, locs = items[0]["snippet"], items[0].get("localizations") or {}
        if sn.get("description", "").startswith(line):
            return {"linked": True, "url": url, "note": "이미 있음"}
        keep = ("title", "description", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")
        body = {"id": vid, "snippet": {k: sn[k] for k in keep if k in sn}}
        body["snippet"]["description"] = replace_link_line(sn.get("description", ""), line)[:5000]
        parts = "snippet"
        if locs:
            body["localizations"] = {lang: {"title": v.get("title", ""),
                                            "description": replace_link_line(v.get("description", ""), line)[:5000]}
                                     for lang, v in locs.items()}
            parts += ",localizations"
        api_json("PUT", f"videos?part={parts}", token, body)
        return {"linked": True, "url": url}
    except urllib.error.HTTPError as e:
        return {"linked": False, "reason": api_error(e)}
    except (urllib.error.URLError, TimeoutError) as e:
        return {"linked": False, "reason": str(e)}


def playlist_sync():
    """5_videos/longform·shorts의 upload_result.json을 읽어 재생목록에 빠진 영상만 올린 순서대로 넣는다."""
    if SCOPE_MANAGE not in granted_scopes():
        fail("재생목록 권한이 없습니다. `python3 scripts/youtube_upload.py --auth`를 다시 실행해 주세요.")
    token = access_token()
    for kind in PLAYLISTS:
        results = []
        for rp in (ROOT / "5_videos" / kind).glob("*/upload_result.json"):
            r = json.loads(rp.read_text(encoding="utf-8"))
            if r.get("video_id"):
                results.append((r.get("uploaded_at", ""), rp, r))
        results.sort(key=lambda x: x[0])
        existed = bool(load_playlists().get(kind, {}).get("id"))
        pid = ensure_playlist(kind, token)
        have = set()
        if existed:  # 방금 만든 재생목록은 잠시 읽히지 않으므로(404) 비어 있는 것으로 본다
            try:
                have = playlist_video_ids(pid, token)
            except urllib.error.HTTPError as e:
                fail(f"재생목록 읽기 실패: {api_error(e)} (config/youtube_playlists.json의 ID 확인)")
        added = skipped = failed = linked = 0
        for _, rp, r in results:
            vid = r["video_id"]
            if vid in have:
                skipped += 1
            else:
                res = add_to_playlist(vid, kind, token)
                if not res["added"]:
                    failed += 1
                    print(f"   ⚠️ {rp.parent.name}: {res['reason']}")
                    continue
                added += 1
                r["playlist"] = res
            pl = r.setdefault("playlist", {"added": True, "kind": kind, "playlist_id": pid,
                                           "playlist_url": f"https://www.youtube.com/playlist?list={pid}"})
            prev = pl.get("description_link") or {}
            if not prev.get("linked") or "playlist?list=" not in prev.get("url", ""):
                pl["description_link"] = add_playlist_link(vid, pid, kind, token)
                if pl["description_link"]["linked"]:
                    linked += 1
                else:
                    print(f"   ⚠️ {rp.parent.name} 설명 링크 실패: {pl['description_link']['reason']}")
            rp.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ {PLAYLISTS[kind]['title']}: 새로 넣음 {added} · 이미 있음 {skipped} · 실패 {failed}"
              f" · 설명 링크 추가 {linked}  https://www.youtube.com/playlist?list={pid}")


def main():
    ap = argparse.ArgumentParser(description="완성 영상을 유튜브에 비공개(또는 일부 공개)로 업로드")
    ap.add_argument("video", nargs="?", help="업로드할 영상 파일")
    ap.add_argument("--meta", help="업로드 정보 JSON (upload.json)")
    ap.add_argument("--auth", action="store_true", help="처음 한 번: 브라우저 로그인으로 토큰 저장")
    ap.add_argument("--check", action="store_true", help="설정과 토큰만 확인")
    ap.add_argument("--dry-run", action="store_true", help="업로드하지 않고 보낼 내용만 검사")
    ap.add_argument("--force", action="store_true", help="이미 올린 기록이 있어도 다시 업로드")
    ap.add_argument("--playlist", choices=list(PLAYLISTS) + ["none"],
                    help="넣을 재생목록 (기본: 영상 경로로 자동, none이면 넣지 않음)")
    ap.add_argument("--playlist-sync", action="store_true",
                    help="이미 올린 영상(5_videos/longform·shorts)을 재생목록에 한 번에 넣기")
    a = ap.parse_args()

    if a.auth:
        return run_auth()
    if a.playlist_sync:
        return playlist_sync()
    if a.check:
        load_client()
        access_token()
        print("✅ 업로드 설정 정상 (클라이언트 JSON, 토큰 갱신 확인)")
        g = granted_scopes()
        if {SCOPE_READ, SCOPE_ANALYTICS} <= g:
            print("✅ 채널 분석 권한 있음 (youtube.readonly, yt-analytics.readonly)")
        else:
            print("ℹ️ 채널 분석 권한 없음: 분석을 쓰려면 `python3 scripts/youtube_upload.py --auth`를 다시 실행해 주세요.")
        if SCOPE_MANAGE in g:
            print("✅ 재생목록 권한 있음 (youtube.force-ssl)")
        else:
            print("ℹ️ 재생목록 권한 없음: 업로드는 되지만 재생목록에 넣지 않습니다. "
                  "`python3 scripts/youtube_upload.py --auth`를 다시 실행해 주세요.")
        return

    if not a.video or not a.meta:
        ap.error("영상 파일과 --meta를 함께 지정하세요.")
    video, meta_path = Path(a.video), Path(a.meta)
    if not video.is_file():
        fail(f"영상 파일이 없습니다: {video}")
    if not meta_path.is_file():
        fail(f"업로드 정보 파일이 없습니다: {meta_path}")
    result_path = meta_path.with_name("upload_result.json")
    if result_path.exists() and not a.force:
        prev = json.loads(result_path.read_text(encoding="utf-8"))
        fail(f"이미 업로드한 기록이 있습니다: {prev.get('url')}\n   다시 올리려면 --force를 붙이세요 (중복 영상이 생깁니다).")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    body = build_body(meta)
    thumb = None
    if meta.get("thumbnail"):
        thumb = (meta_path.parent / meta["thumbnail"]).resolve()
        if not thumb.is_file():
            fail(f"썸네일 파일이 없습니다: {thumb}")
        if thumb.suffix.lower() not in (".jpg", ".jpeg", ".png") or thumb.stat().st_size > 2 * 1024**2:
            fail("썸네일은 JPG/PNG, 2MB 이하여야 합니다.")
    size_mb = video.stat().st_size / 1024**2
    print(f"영상: {video} ({size_mb:.1f}MB)")
    print(f"제목: {body['snippet']['title']}")
    print(f"공개 상태: {body['status']['privacyStatus']} · 아동용: {body['status']['selfDeclaredMadeForKids']}"
          f" · AI 합성 공개: {body['status']['containsSyntheticMedia']} · 태그 {len(body['snippet']['tags'])}개")
    kind = None if a.playlist == "none" else (a.playlist or video_kind(video))
    print(f"재생목록: {PLAYLISTS[kind]['title'] if kind else '넣지 않음'}")
    print(f"언어: 기본 {body['snippet'].get('defaultLanguage')} · 오디오 {body['snippet'].get('defaultAudioLanguage')}"
          f" · 번역 {', '.join(body.get('localizations', {})) or '없음'}"
          f" · 썸네일 {thumb.name if thumb else '없음(자동)'}")
    if a.dry_run:
        return print("✅ dry-run: 형식 검사 통과 (업로드하지 않음)")

    token = access_token()
    notes = []
    res = upload(video, body, token, notes)
    vid = res.get("id")
    status = res.get("status", {})
    out = {
        "video_id": vid,
        "url": f"https://youtu.be/{vid}",
        "studio_url": f"https://studio.youtube.com/video/{vid}/edit",
        "note": "아래 *_at_upload 값은 업로드 직후 상태다. 지금 상태는 Studio나 scripts/youtube_analytics.py로 확인한다.",
        "privacy_at_upload": status.get("privacyStatus"),
        "upload_status_at_upload": status.get("uploadStatus"),
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file": str(video),
        "sent": {"madeForKids": body["status"]["selfDeclaredMadeForKids"],
                 "containsSyntheticMedia": body["status"]["containsSyntheticMedia"],
                 "categoryId": body["snippet"]["categoryId"],
                 "defaultLanguage": body["snippet"].get("defaultLanguage"),
                 "defaultAudioLanguage": body["snippet"].get("defaultAudioLanguage"),
                 "localizations": sorted(body.get("localizations", {}))},
        "fallbacks": notes,
    }
    if thumb:
        out["thumbnail"] = set_thumbnail(vid, thumb, token)
    out["verified"] = verify_settings(vid, body, token)
    if kind:
        out["playlist"] = add_to_playlist(vid, kind, token)
        if out["playlist"]["added"]:
            out["playlist"]["description_link"] = add_playlist_link(vid, out["playlist"]["playlist_id"], kind, token)
    result_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 업로드 완료 ({out['privacy_at_upload']})")
    for n in notes:
        print(f"   ⚠️ {n}")
    if thumb:
        t = out["thumbnail"]
        print("   썸네일 적용됨" if t["set"] else f"   ⚠️ 썸네일 실패: {t['reason']} (Studio에서 직접 올릴 수 있음)")
    print(f"   영상: {out['url']}")
    print(f"   스튜디오: {out['studio_url']}")
    v = out["verified"]
    if v.get("checked"):
        for w in v["warnings"]:
            print(f"   ⚠️ {w}")
        if not v["warnings"]:
            print("   설정 확인: 아동용·AI 합성 공개·카테고리·언어·번역이 보낸 값과 같습니다.")
    else:
        print(f"   ℹ️ 설정 다시 읽기를 건너뜀: {v.get('reason')}")
    if kind:
        pl = out["playlist"]
        print(f"   재생목록에 넣음: {pl['playlist_url']}" if pl["added"] else f"   ⚠️ 재생목록 넣기 건너뜀: {pl['reason']}")
        dl = pl.get("description_link")
        if dl:
            print(f"   설명란 이어 보기 링크: {dl['url']}" if dl["linked"] else f"   ⚠️ 설명 링크 실패: {dl['reason']}")
    print(f"   기록: {result_path}")


if __name__ == "__main__":
    main()
