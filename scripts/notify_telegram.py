#!/usr/bin/env python3
"""
텔레그램으로 알림 메시지나 파일(완성 영상 등)을 보낸다. 표준 라이브러리만 사용한다.
봇 토큰과 채팅 ID는 config/telegram_keys.json에서 읽고 화면에 출력하지 않는다.
설정 파일이 없으면 알림을 건너뛰고 정상 종료한다 (작업 흐름이 멈추지 않도록).

사용 예:
    python3 scripts/notify_telegram.py "🎬 영상 제작 완료"
    python3 scripts/notify_telegram.py "완성 영상입니다" --file 5_videos/xxx/xxx.mp4
    python3 scripts/notify_telegram.py --get-chat-id      # 봇에게 메시지를 보낸 뒤 채팅 ID 확인
"""

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "telegram_keys.json"
MAX_TEXT = 4000            # 텔레그램 메시지 최대 4096자
MAX_UPLOAD = 50 * 1024**2  # 봇이 보낼 수 있는 파일 최대 50MB


def is_placeholder(v):
    return not v or v.startswith("여기에")


def load_config():
    if not CONFIG.exists():
        return None, None
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"❌ {CONFIG} 파일 형식이 잘못되었습니다 (줄 {e.lineno}): {e.msg}")
    token = str(data.get("bot_token", "")).strip()
    chat_id = str(data.get("chat_id", "")).strip()
    return (None if is_placeholder(token) else token), (None if is_placeholder(chat_id) else chat_id)


def call(token, method, fields, file_field=None, file_path=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if file_path:
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
            + file_path.read_bytes() + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(url, data=b"".join(parts),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode())
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            desc = json.load(e).get("description", "")
        except Exception:
            desc = ""
        hint = " (봇 토큰을 확인하세요)" if e.code in (401, 404) else ""
        hint = hint or (" (채팅 ID를 확인하고, 봇에게 먼저 메시지를 보냈는지 확인하세요)" if e.code in (400, 403) else "")
        sys.exit(f"❌ 텔레그램 오류 ({e.code}): {desc}{hint}")
    except urllib.error.URLError as e:
        sys.exit(f"❌ 네트워크 오류: {e.reason}")


def get_chat_id(token):
    data = call(token, "getUpdates", {})
    chats = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name", "")
    if not chats:
        sys.exit("ℹ️  받은 메시지가 없습니다. 텔레그램에서 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
    print("채팅 ID 목록 (config/telegram_keys.json의 chat_id에 입력):")
    for cid, name in chats.items():
        print(f"  {cid}  ({name})")


def main():
    p = argparse.ArgumentParser(description="텔레그램으로 알림을 보냅니다.")
    p.add_argument("message", nargs="?", default="", help="보낼 메시지")
    p.add_argument("--file", help="함께 보낼 파일 (mp4는 영상으로, 그 외는 문서로)")
    p.add_argument("--get-chat-id", action="store_true", help="봇에게 온 메시지로 채팅 ID 확인")
    args = p.parse_args()

    token, chat_id = load_config()
    if args.get_chat_id:
        if not token:
            sys.exit("❌ config/telegram_keys.json에 bot_token을 먼저 입력하세요.")
        return get_chat_id(token)

    if not token or not chat_id:
        print("ℹ️  텔레그램 설정(config/telegram_keys.json)이 없어 알림을 건너뜁니다.")
        return
    if not args.message and not args.file:
        sys.exit("❌ 보낼 메시지나 파일을 지정하세요.")

    text = args.message
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n…(생략)"

    if args.file:
        path = Path(args.file)
        if not path.exists():
            sys.exit(f"❌ 파일이 없습니다: {path}")
        if path.stat().st_size > MAX_UPLOAD:
            print("⚠️  파일이 50MB를 넘어 메시지만 보냅니다.")
            call(token, "sendMessage", {"chat_id": chat_id, "text": f"{text}\n(파일이 커서 첨부하지 못함: {path.name})"})
        else:
            is_video = path.suffix.lower() in (".mp4", ".mov")
            fields = {"chat_id": chat_id, "caption": text[:1000]}
            if is_video:
                fields["supports_streaming"] = "true"
            call(token, "sendVideo" if is_video else "sendDocument", fields,
                 "video" if is_video else "document", path)
            if len(text) > 1000:  # 캡션은 1024자까지라 나머지는 메시지로
                call(token, "sendMessage", {"chat_id": chat_id, "text": text})
    else:
        call(token, "sendMessage", {"chat_id": chat_id, "text": text})
    print("✅ 텔레그램 알림을 보냈습니다.")


if __name__ == "__main__":
    main()
