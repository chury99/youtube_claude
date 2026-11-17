#!/usr/bin/env python3
"""
아이용 5초 쇼츠 "통통 별이" — AI 도구 없이 코드로 직접 그리고 작곡한다.

장면 (세로 1080x1920, 30fps, 5초)
  0.0~0.5초  하늘에서 웃는 별 캐릭터가 '뿅' 떨어짐
  0.5~3.5초  통통 튀며 놀고, 풍선이 올라가고, 무지개가 그려짐
  3.5~4.4초  크게 점프하며 한 바퀴 → 꼭대기에서 색종이 '팡' + "안녕!"
  4.4~5.0초  착지해서 활짝 웃음

필요: numpy, Pillow, ffmpeg
사용: python3 make_video.py   → 같은 폴더에 kids_star_5s.mp4 생성
"""

import math
import random
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent
W, H, FPS, DUR = 1080, 1920, 30, 5.0
S = 2  # 2배 크기로 그린 뒤 줄여서 테두리를 부드럽게
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
SR = 48000

GROUND = 1610          # 별이 발 딛는 높이
STAR_R = 230
IMPACTS = [0.5, 1.1, 1.7, 2.3, 2.9, 3.5]   # 바닥에 닿는 순간 (통통 소리 타이밍)
BIG_JUMP = (3.5, 4.4)                      # 큰 점프 시작/착지
BURST_T = 3.95                             # 색종이 + 글자 등장


def p(*v):
    """1080 기준 좌표 → 실제 그리는 캔버스 좌표"""
    return [x * S for x in v]


def ease_out_back(x):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def clamp01(x):
    return max(0.0, min(1.0, x))


# ───────────────────────── 움직임 계산 ─────────────────────────

def star_state(t):
    """별의 발 위치(y), 가로/세로 늘어남, 회전 각도"""
    if t < IMPACTS[0]:
        feet = -300 + (GROUND + 300) * (t / IMPACTS[0]) ** 2
    elif t < BIG_JUMP[0]:
        k = min(int((t - IMPACTS[0]) / 0.6), len(IMPACTS) - 2)
        u = (t - IMPACTS[k]) / 0.6
        feet = GROUND - 380 * 4 * u * (1 - u)
    elif t < BIG_JUMP[1]:
        u = (t - BIG_JUMP[0]) / (BIG_JUMP[1] - BIG_JUMP[0])
        feet = GROUND - 760 * 4 * u * (1 - u)
    else:
        feet = GROUND

    # 바닥에 닿을 때 찌그러짐(스쿼시)
    squash = 0.0
    for ti in IMPACTS + [BIG_JUMP[1]]:
        d = t - ti
        if -0.04 <= d <= 0.14:
            squash = max(squash, math.sin(math.pi * (d + 0.04) / 0.18))
    sy, sx = 1 - 0.24 * squash, 1 + 0.18 * squash
    if t > BIG_JUMP[1] + 0.2:  # 착지 후 숨쉬기
        b = math.sin((t - BIG_JUMP[1]) * 9) * 0.03
        sy, sx = 1 + b, 1 - b

    rot = 0.0
    if BIG_JUMP[0] <= t < BIG_JUMP[1]:
        u = (t - BIG_JUMP[0]) / (BIG_JUMP[1] - BIG_JUMP[0])
        rot = 360 * (1 - (1 - u) ** 2)
    return feet, sx, sy, rot


# ───────────────────────── 그리기 ─────────────────────────

def make_sky():
    top, bottom = np.array([110, 190, 255]), np.array([205, 238, 255])
    g = np.linspace(0, 1, H * S)[:, None]
    col = (top * (1 - g) + bottom * g).astype(np.uint8)
    arr = np.repeat(col[:, None, :], W * S, axis=1)
    return Image.fromarray(arr, "RGB")


def draw_cloud(d, x, y, s):
    for dx, dy, r in [(-90, 10, 60), (-30, -30, 80), (50, -10, 70), (110, 15, 50), (10, 25, 70)]:
        d.ellipse(p(x + (dx - r) * s, y + (dy - r) * s, x + (dx + r) * s, y + (dy + r) * s),
                  fill=(255, 255, 255))


def draw_twinkle(d, x, y, r, color):
    pts = []
    for k in range(8):
        a = math.pi / 4 * k
        rad = r if k % 2 == 0 else r * 0.25
        pts.append((x + rad * math.cos(a), y + rad * math.sin(a)))
    d.polygon([v * S for pt in pts for v in pt], fill=color)


def draw_rainbow(d, t):
    prog = clamp01((t - 2.3) / 1.0)
    if prog <= 0:
        return
    colors = [(255, 90, 90), (255, 160, 70), (255, 220, 80), (110, 210, 110),
              (90, 170, 255), (120, 110, 230), (190, 120, 230)]
    cx, cy, outer, band = 540, 1640, 640, 42
    end = 180 + 180 * (1 - (1 - prog) ** 3)
    for i, c in enumerate(colors):
        r = outer - i * band
        d.arc(p(cx - r, cy - r, cx + r, cy + r), 180, end, fill=c, width=band * S + 2)


def draw_hill(d):
    d.ellipse(p(-500, 1590, 1580, 2900), fill=(120, 205, 110))
    d.ellipse(p(-300, 1640, 1380, 2900), fill=(140, 220, 125))
    for x, y, c in [(120, 1780, (255, 120, 160)), (300, 1860, (255, 230, 90)),
                    (820, 1800, (255, 255, 255)), (960, 1890, (255, 140, 90)),
                    (560, 1900, (190, 140, 255))]:
        for k in range(5):
            a = 2 * math.pi * k / 5
            px, py = x + 22 * math.cos(a), y + 22 * math.sin(a)
            d.ellipse(p(px - 16, py - 16, px + 16, py + 16), fill=c)
        d.ellipse(p(x - 12, y - 12, x + 12, y + 12), fill=(255, 200, 40))


BALLOONS = [  # x, 출발 시간, 색
    (150, 0.8, (255, 80, 100)), (930, 1.0, (70, 160, 255)), (330, 1.3, (255, 200, 50)),
    (760, 1.5, (120, 210, 90)), (560, 1.9, (200, 110, 240)), (60, 2.4, (255, 140, 60)),
    (1010, 2.6, (255, 110, 190)),
]


def draw_balloons(d, t):
    for i, (bx, t0, c) in enumerate(BALLOONS):
        if t < t0:
            continue
        y = 2150 - (t - t0) * 520
        x = bx + 18 * math.sin(t * 2.5 + i)
        if y < -400:
            continue
        rw, rh = 72, 88
        pts = []
        for k in range(12):
            yy = y + rh + 6 + k * 22
            pts += [x + 10 * math.sin(k * 0.9 + t * 6 + i), yy]
        d.line([v * S for v in pts], fill=(90, 90, 110), width=3 * S)
        d.polygon(p(x, y + rh - 4, x - 12, y + rh + 14, x + 12, y + rh + 14), fill=c)
        d.ellipse(p(x - rw, y - rh, x + rw, y + rh), fill=c)
        d.ellipse(p(x - 40, y - 60, x - 16, y - 20), fill=(255, 255, 255))


def tf(cx, cy, sx, sy, rot, lx, ly):
    """별 몸 기준 좌표 → 화면 좌표 (늘어남 + 회전 반영)"""
    lx, ly = lx * sx, ly * sy
    a = math.radians(rot)
    return cx + lx * math.cos(a) - ly * math.sin(a), cy + lx * math.sin(a) + ly * math.cos(a)


def draw_star(d, t):
    feet, sx, sy, rot = star_state(t)
    R = STAR_R
    cy = feet - 0.809 * R * sy
    cx = 540

    # 그림자: 높이 올라갈수록 작고 옅어짐
    h = clamp01((GROUND - feet) / 800)
    sw = 170 * (1 - 0.6 * h)
    d.ellipse(p(cx - sw, GROUND - 22 * (1 - 0.6 * h), cx + sw, GROUND + 22 * (1 - 0.6 * h)),
              fill=(95, 170, 90))

    pts = []
    for k in range(10):
        a = math.radians(-90 + 36 * k)
        rad = R if k % 2 == 0 else R * 0.5
        pts.append(tf(cx, cy, sx, sy, rot, rad * math.cos(a), rad * math.sin(a)))
    flat = [v * S for pt in pts for v in pt]
    closed = flat + flat[:2]
    d.line(closed, fill=(240, 140, 30), width=70 * S, joint="curve")   # 주황 테두리
    d.polygon(flat, fill=(240, 140, 30))
    d.line(closed, fill=(255, 215, 60), width=46 * S, joint="curve")   # 노란 몸통 (둥근 모서리)
    d.polygon(flat, fill=(255, 215, 60))

    def at(lx, ly):
        return tf(cx, cy, sx, sy, rot, lx, ly)

    # 볼터치
    for side in (-1, 1):
        bx, by = at(side * 0.42 * R, 0.16 * R)
        d.ellipse(p(bx - 30, by - 18, bx + 30, by + 18), fill=(255, 150, 130))

    # 눈
    blink = any(abs(t - bt) < 0.07 for bt in (1.4, 3.15))
    happy = t >= BIG_JUMP[1]
    for side in (-1, 1):
        ex, ey = at(side * 0.22 * R, -0.04 * R)
        if happy:  # ^ ^ 웃는 눈
            d.arc(p(ex - 26, ey - 18, ex + 26, ey + 26), 200, 340, fill=(60, 40, 30), width=9 * S)
        elif blink:
            d.line(p(ex - 24, ey, ex + 24, ey), fill=(60, 40, 30), width=9 * S)
        else:
            d.ellipse(p(ex - 24, ey - 32, ex + 24, ey + 32), fill=(60, 40, 30))
            d.ellipse(p(ex - 12, ey - 22, ex + 4, ey - 6), fill=(255, 255, 255))

    # 입
    mx, my = at(0, 0.2 * R)
    if t >= BIG_JUMP[0]:  # 신나서 입을 크게 벌림
        d.pieslice(p(mx - 42, my - 34, mx + 42, my + 44), 0, 180, fill=(200, 60, 60))
        d.ellipse(p(mx - 20, my + 14, mx + 20, my + 40), fill=(255, 120, 130))
    else:
        d.arc(p(mx - 34, my - 26, mx + 34, my + 22), 20, 160, fill=(60, 40, 30), width=8 * S)


random.seed(7)
CONFETTI = [dict(a=random.uniform(0, 2 * math.pi), v=random.uniform(500, 1500),
                 spin=random.uniform(-12, 12), w=random.uniform(16, 30),
                 c=random.choice([(255, 80, 100), (70, 160, 255), (255, 210, 50),
                                  (120, 210, 90), (200, 110, 240), (255, 140, 60)]))
            for _ in range(140)]


def draw_confetti(d, t):
    if t < BURST_T:
        return
    dt = t - BURST_T
    ox, oy = 540, GROUND - 760 - 0.809 * STAR_R
    for q in CONFETTI:
        x = ox + math.cos(q["a"]) * q["v"] * dt
        y = oy + math.sin(q["a"]) * q["v"] * dt + 900 * dt * dt
        ang = q["spin"] * dt + q["a"]
        hw, hh = q["w"] / 2, q["w"] / 4
        corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        pts = [(x + cx * math.cos(ang) - cy * math.sin(ang),
                y + cx * math.sin(ang) + cy * math.cos(ang)) for cx, cy in corners]
        d.polygon([v * S for pt in pts for v in pt], fill=q["c"])


def draw_text(d, t, font_big, font_small):
    if t < BURST_T + 0.05:
        return
    u = clamp01((t - BURST_T - 0.05) / 0.35)
    sc = max(ease_out_back(u), 0.01)
    for text, font, y, base in [("안녕!", font_big, 360, 230), ("Hello!", font_small, 560, 120)]:
        f = font.font_variant(size=int(base * sc * S))
        d.text((540 * S, y * S), text, font=f, anchor="mm", fill=(255, 100, 140),
               stroke_width=int(14 * sc * S), stroke_fill=(255, 255, 255))


def render_frame(t, sky, fonts):
    img = sky.copy()
    d = ImageDraw.Draw(img)
    for i, (x, y) in enumerate([(160, 240), (900, 520), (420, 760), (980, 160), (90, 960)]):
        r = 26 + 14 * math.sin(t * 6 + i * 1.7)
        draw_twinkle(d, x, y, r, (255, 250, 200))
    draw_cloud(d, 200 + t * 40, 420, 1.1)
    draw_cloud(d, 850 - t * 30, 880, 0.9)
    draw_cloud(d, 600 + t * 25, 1180, 0.7)
    draw_rainbow(d, t)
    draw_hill(d)
    draw_balloons(d, t)
    draw_star(d, t)
    draw_confetti(d, t)
    draw_text(d, t, *fonts)
    return img.resize((W, H), Image.LANCZOS)


# ───────────────────────── 소리 ─────────────────────────

def note_freq(name):
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    return 440 * 2 ** ((names[name[0]] + (int(name[1:]) - 4) * 12) / 12)


def add(buf, start, sig):
    i = int(start * SR)
    j = min(len(buf), i + len(sig))
    if i < j:
        buf[i:j] += sig[: j - i]


def xylophone(f, dur=0.5, vol=0.25):
    t = np.arange(int(dur * SR)) / SR
    env = np.exp(-t * 7) * np.minimum(t * 400, 1)
    return vol * env * (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 4 * t) * np.exp(-t * 20))


def boing(dur=0.22, f0=180, f1=520, vol=0.35):
    t = np.arange(int(dur * SR)) / SR
    f = f0 + (f1 - f0) * (t / dur) ** 0.5 + 25 * np.sin(2 * np.pi * 30 * t)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return vol * np.sin(phase) * np.exp(-t * 9) * np.minimum(t * 300, 1)


def slide_whistle(dur, f0=400, f1=1400, vol=0.18):
    t = np.arange(int(dur * SR)) / SR
    f = f0 * (f1 / f0) ** (t / dur) * (1 + 0.02 * np.sin(2 * np.pi * 6 * t))
    phase = 2 * np.pi * np.cumsum(f) / SR
    return vol * np.sin(phase) * np.minimum(t * 50, 1) * np.minimum((dur - t) * 30, 1)


def pop(vol=0.4):
    t = np.arange(int(0.12 * SR)) / SR
    rng = np.random.default_rng(1)
    return vol * rng.uniform(-1, 1, len(t)) * np.exp(-t * 45)


def make_audio(path):
    n = int(DUR * SR)
    buf = np.zeros(n)
    melody = ["C5", "E5", "G5", "E5", "F5", "A5", "G5", "E5",
              "C5", "E5", "G5", "C6", "B5", "G5"]
    for i, nm in enumerate(melody):
        add(buf, i * 0.3, xylophone(note_freq(nm), vol=0.16))
    for i, nm in enumerate(["C3", "G3", "F3", "C3", "C3", "G3", "G3"]):
        add(buf, i * 0.6, xylophone(note_freq(nm), dur=0.6, vol=0.14))
    for ti in IMPACTS[:-1]:
        add(buf, ti, boing())
    add(buf, BIG_JUMP[0], slide_whistle(BURST_T - BIG_JUMP[0]))
    add(buf, BURST_T, pop())
    for k, nm in enumerate(["C6", "E6", "G6", "C7", "E7", "G7"]):   # 반짝반짝
        add(buf, BURST_T + k * 0.05, xylophone(note_freq(nm), dur=0.4, vol=0.12))
    add(buf, BIG_JUMP[1], boing(f0=140, f1=380, vol=0.3))
    for nm in ["C4", "E5", "G5", "C6"]:                               # 마무리 화음
        add(buf, BIG_JUMP[1] + 0.05, xylophone(note_freq(nm), dur=0.55, vol=0.13))
    buf *= np.minimum(1, (DUR - np.arange(n) / SR) / 0.15)            # 끝 0.15초 페이드
    buf = np.clip(buf / max(1.0, np.abs(buf).max() / 0.9), -1, 1)
    pcm = (buf * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())


# ───────────────────────── 합치기 ─────────────────────────

def main():
    wav = OUT_DIR / "audio.wav"
    out = OUT_DIR / "kids_star_5s.mp4"
    make_audio(wav)
    sky = make_sky()
    fonts = (ImageFont.truetype(FONT, 230 * S, index=6), ImageFont.truetype(FONT, 120 * S, index=6))
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav), "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total = int(DUR * FPS)
    for f in range(total):
        proc.stdin.write(render_frame(f / FPS, sky, fonts).tobytes())
        if f % 30 == 0:
            print(f"  {f}/{total} 프레임")
    proc.stdin.close()
    proc.wait()
    wav.unlink()
    print(f"✅ 완성: {out}")


if __name__ == "__main__":
    main()
