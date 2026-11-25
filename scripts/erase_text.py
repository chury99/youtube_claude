#!/usr/bin/env python3
"""AI가 보드·카드·종이에 잘못 그려 넣은 글자를 지운다 (블러 대신).

상자 안에서 '밝은 종이 위의 가늘고 어두운 획'만 골라 마스크를 만들고,
그 자리를 바로 옆 종이 색으로 메운다(OpenCV 인페인팅). 종이의 그늘·질감은 그대로 남고,
상자 자국이 생기지 않는다. 캐릭터(털·눈·옷)는 종이처럼 밝고 무채색이 아니라서 건드리지 않는다.

사용:
  .venv/bin/python scripts/erase_text.py <입력.mp4> <상자.json> <출력.mp4> [--preview <폴더>]

상자.json: [[시작초, 끝초, x0, y0, x1, y1], ...]   (좌표는 영상 픽셀 기준)
출력은 소리 없는 영상(입력과 같은 크기·fps, crf 12)이다. 소리는 원래 파일에서 가져다 쓴다.
--preview를 주면 상자마다 가운데 시각의 전/후 비교 그림을 저장한다(검수용).

필요: opencv-python-headless (.venv에 설치되어 있음)
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

# 글자 획 찾기 기준
STROKE_KERNEL = 15      # 이보다 가는 어두운 선을 글자 획으로 본다(픽셀). 흐린(초점 밖) 글자까지 잡게 넉넉히
STROKE_DARK = 12        # 주변보다 이만큼 이상 어두워야 획 (흐린 글자는 대비가 낮음)
PAPER_V = 150           # 획 주변(종이)의 밝기 하한(0~255)
PAPER_S = 70            # 획 주변(종이)의 채도 상한(0~255) — 털·옷처럼 색 있는 곳은 제외
INK_S = 60              # 획 자체가 무채색(검정·회색 글씨)이거나
INK_V = 110             # 아주 어두워야 지운다 — 나무 막대·털처럼 색 있는 가는 것은 남김
GROW = 2                # 마스크를 이만큼 넓혀 글자 테두리 번짐까지 지움


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return s["width"], s["height"], float(num) / float(den)


def text_mask(img, x0, y0, x1, y1):
    """상자 안 글자 획 마스크(상자 밖은 0)."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    roi = img[y0:y1, x0:x1]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (STROKE_KERNEL, STROKE_KERNEL))
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    stroke = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k) > STROKE_DARK
    # 획을 메운(closing) 그림 = 획 주변 바탕. 바탕이 밝고 무채색인 곳(종이)만 남긴다.
    bg = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, k)
    hsv = cv2.cvtColor(bg, cv2.COLOR_BGR2HSV)
    paper = (hsv[..., 2] >= PAPER_V) & (hsv[..., 1] <= PAPER_S)
    hsv_px = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    ink = (hsv_px[..., 1] <= INK_S) | (hsv_px[..., 2] <= INK_V)
    m = (stroke & paper & ink).astype(np.uint8) * 255
    if GROW:
        m = cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=GROW)
    full = np.zeros((h, w), np.uint8)
    full[y0:y1, x0:x1] = m
    return full


def erase_frame(img, boxes):
    mask = np.zeros(img.shape[:2], np.uint8)
    for (x0, y0, x1, y1) in boxes:
        mask |= text_mask(img, x0, y0, x1, y1)
    if not mask.any():
        return img
    return cv2.inpaint(img, mask, 5, cv2.INPAINT_TELEA)


def main():
    args = sys.argv[1:]
    preview = None
    if "--preview" in args:
        i = args.index("--preview")
        preview = Path(args[i + 1])
        del args[i:i + 2]
    src, boxes_json, dst = Path(args[0]), Path(args[1]), Path(args[2])
    boxes = [tuple(b) for b in json.loads(boxes_json.read_text(encoding="utf-8"))]
    W, H, fps = probe(src)

    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo",
                            "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-", "-an",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "12",
                            "-pix_fmt", "yuv420p", str(dst)], stdin=subprocess.PIPE)
    want = {}
    if preview:
        preview.mkdir(parents=True, exist_ok=True)
        for j, b in enumerate(boxes):
            want[int(round((b[0] + b[1]) / 2 * fps))] = j
    n, touched = 0, 0
    size = W * H * 3
    while True:
        buf = dec.stdout.read(size)
        if len(buf) < size:
            break
        img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        t = n / fps
        active = [b[2:] for b in boxes if b[0] <= t < b[1]]
        out = erase_frame(img, active) if active else img
        if active:
            touched += 1
        if n in want:
            j = want[n]
            x0, y0, x1, y1 = boxes[j][2:]
            pad = 60
            ys, ye = max(0, y0 - pad), min(H, y1 + pad)
            xs, xe = max(0, x0 - pad), min(W, x1 + pad)
            pair = np.hstack([img[ys:ye, xs:xe], np.full((ye - ys, 8, 3), 255, np.uint8),
                              out[ys:ye, xs:xe]])
            cv2.imwrite(str(preview / f"box{j:02d}_{t:05.2f}s.png"), pair)
        enc.stdin.write(np.ascontiguousarray(out).tobytes())
        n += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    print(f"지움: {touched}/{n} 프레임, 상자 {len(boxes)}개 → {dst}")


if __name__ == "__main__":
    main()
