#!/usr/bin/env python3
"""
꿀벌 한 마리가 평생 만드는 꿀 = 티스푼 1/12  (30초 세로 모션 그래픽 쇼츠)

- 그림: skia-python (안티에일리어싱 벡터, 나눔명조 Regular/Bold/ExtraBold)
- 소리: numpy로 직접 합성한 120 BPM 음악 + 효과음 (외부 음원 없음)
- 실행: .venv/bin/python videos/20261116_1550_en0GuyhieQk/make_video.py
        --preview 1.0 3.5 ...  (지정한 초의 프레임만 PNG로 저장)
"""

import math
import re
import subprocess
import sys
import wave
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import skia

NAME = "20261116_1550_en0GuyhieQk"
OUT_DIR = Path(__file__).resolve().parent
W, H, FPS, DUR = 1080, 1920, 30, 30.0
SR = 44100

# ───────────────────────── 팔레트 ─────────────────────────


def hexc(h, a=1.0):
    h = h.lstrip("#")
    return skia.ColorSetARGB(int(round(a * 255)), int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


BG = "#C98B3A"
TINT = "#F1DEBF"
CREAM = "#FAF9F5"
INK = "#141413"
HONEY = "#EBA937"
DEEP = "#8E5A17"
NEUTRAL = "#D1CDC2"
MUTED = "#5A4A54"
DOT = "#E6CC9E"
COMB = "#B97E33"

CARD = skia.Rect(80, 320, 1000, 1262)
CARD_C = (540, 791)

# ───────────────────────── 이징 ─────────────────────────


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def prog(t, t0, d):
    return clamp((t - t0) / d)


def e_out_expo(x):
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def e_out_cubic(x):
    return 1 - (1 - x) ** 3


def e_in_cubic(x):
    return x ** 3


def e_inout_cubic(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def e_in_expo(x):
    return 0.0 if x <= 0 else 2 ** (10 * x - 10)


def e_out_back(x, s=1.70):
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def e_in_back(x, s=1.70):
    return (s + 1) * x ** 3 - s * x ** 2


def lerp(a, b, x):
    return a + (b - a) * x


# ───────────────────────── 글자 ─────────────────────────

_TF = {}
_FONT = {}


def typeface(w):
    if w not in _TF:
        _TF[w] = skia.Typeface("Nanum Myeongjo", skia.FontStyle(w, 5, skia.FontStyle.kUpright_Slant))
    return _TF[w]


def font(w, size):
    k = (w, size)
    if k not in _FONT:
        f = skia.Font(typeface(w), size)
        f.setSubpixel(True)
        f.setEdging(skia.Font.Edging.kAntiAlias)
        _FONT[k] = f
    return _FONT[k]


R, B, XB = 400, 700, 800


def seg(text, w, size, color=INK, track=None):
    if track is None:
        track = -0.02 if (w == XB and size >= 100) else -0.01
    return (text, w, size, color, track)


def seg_width(s):
    text, w, size, _, track = s
    f = font(w, size)
    ws = f.getWidths(f.textToGlyphs(text))
    return sum(ws) + track * size * (len(ws) - 1)


def segs_width(segs):
    return sum(seg_width(s) for s in segs)


def draw_segs(c, segs, x, y, alpha=1.0):
    for s in segs:
        text, w, size, color, track = s
        f = font(w, size)
        ws = f.getWidths(f.textToGlyphs(text))
        xs, cx = [], x
        for gw in ws:
            xs.append(cx)
            cx += gw + track * size
        blob = skia.TextBlob.MakeFromPosTextH(text, xs, 0, f)
        p = skia.Paint(AntiAlias=True, Color=hexc(color, alpha))
        c.drawTextBlob(blob, 0, y, p)
        x = cx - track * size
    return x


def fit_size(segs_fn, size, maxw=800):
    """segs_fn(size) → segs. 폭이 maxw를 넘으면 크기를 줄인다."""
    while segs_width(segs_fn(size)) > maxw and size > 20:
        size -= 2
    return size


def reveal(c, segs, x, y, t, t0, dur=0.4, dy=60, out_t0=None, out_d=0.3, alpha=1.0):
    """줄 단위 마스크 리빌 (클립 고정, 글자가 아래에서 위로)."""
    p = prog(t, t0, dur)
    if p <= 0:
        return
    size = max(s[2] for s in segs)
    wdt = segs_width(segs)
    off = dy * (1 - e_out_expo(p))
    if out_t0 is not None and t > out_t0:
        off -= (size * 1.3 + 40) * e_in_expo(prog(t, out_t0, out_d))
    c.save()
    c.clipRect(skia.Rect(x - 14, y - size * 1.0 - 10, x + wdt + 14, y + size * 0.28 + 10))
    draw_segs(c, segs, x, y + off, alpha)
    c.restore()


def wipe_lr(c, segs, x, y, t, t0, dur=0.4, alpha=1.0):
    p = prog(t, t0, dur)
    if p <= 0:
        return
    size = max(s[2] for s in segs)
    wdt = segs_width(segs)
    c.save()
    c.clipRect(skia.Rect(x - 14, y - size * 1.05, x - 14 + (wdt + 28) * e_out_expo(p), y + size * 0.3))
    draw_segs(c, segs, x, y, alpha)
    c.restore()


def punch_text(c, segs, x, y, t, t0, dur=0.3, s0=1.2, s=1.7, alpha=1.0, fade=0.08):
    p = prog(t, t0, dur)
    if t < t0:
        return
    size = max(sg[2] for sg in segs)
    wdt = segs_width(segs)
    sc = lerp(s0, 1.0, e_out_back(p, s))
    a = alpha * clamp((t - t0) / fade)
    c.save()
    cx, cy = x + wdt / 2, y - size * 0.36
    c.translate(cx, cy)
    c.scale(sc, sc)
    c.translate(-cx, -cy)
    draw_segs(c, segs, x, y, a)
    c.restore()


# ───────────────────────── 도형 도우미 ─────────────────────────


def fill(color, a=1.0):
    return skia.Paint(AntiAlias=True, Color=hexc(color, a), Style=skia.Paint.kFill_Style)


def stroke(color, w, a=1.0, cap=skia.Paint.kRound_Cap):
    return skia.Paint(AntiAlias=True, Color=hexc(color, a), Style=skia.Paint.kStroke_Style,
                      StrokeWidth=w, StrokeCap=cap, StrokeJoin=skia.Paint.kRound_Join)


def oval(cx, cy, rx, ry):
    return skia.Rect(cx - rx, cy - ry, cx + rx, cy + ry)


def card_rrect(inset=0.0):
    r = CARD.makeInset(inset, inset)
    return skia.RRect.MakeRectXY(r, 36 - inset, 36 - inset)


# ───────────────────────── 배경 (벌집 무늬) ─────────────────────────

HEX_R = 74
HEX_DY = math.sqrt(3) * HEX_R          # 세로 반복 주기
HEX_SPEED = HEX_DY * 2 / DUR           # 30초에 정확히 2주기 → 루프 이음새 없음


def draw_bg(c, t):
    c.clear(hexc(BG))
    off = (t * HEX_SPEED) % HEX_DY
    path = skia.Path()
    dx = 1.5 * HEX_R
    col = 0
    x = -HEX_R
    while x < W + HEX_R:
        yoff = (HEX_DY / 2) if col % 2 else 0
        y = -HEX_DY + yoff - off
        while y < H + HEX_DY:
            for k in range(6):
                a = math.radians(60 * k)
                px, py = x + HEX_R * 0.86 * math.cos(a), y + HEX_R * 0.86 * math.sin(a)
                if k == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            path.close()
            y += HEX_DY
        x += dx
        col += 1
    c.drawPath(path, stroke(COMB, 4, 0.55))


# ───────────────────────── 티스푼 / 꿀 ─────────────────────────


def spoon_path(cx, cy, rx, ry, hx0, hx1, h0, h1):
    """볼(타원) + 끝으로 갈수록 넓어지는 손잡이를 합친 하나의 외곽선."""
    bowl = skia.Path()
    bowl.addOval(oval(cx, cy, rx, ry))
    hp = skia.Path()
    hy = cy
    hp.moveTo(hx0 - 20, hy - h0)
    hp.lineTo(hx1 - h1, hy - h1)
    hp.arcTo(skia.Rect(hx1 - 2 * h1, hy - h1, hx1, hy + h1), -90, 180, False)
    hp.lineTo(hx0 - 20, hy + h0)
    hp.close()
    return skia.Op(bowl, hp, skia.PathOp.kUnion_PathOp)


def honey_level_for_fraction(frac):
    """타원 아래쪽 활꼴 넓이 비율이 frac이 되는 높이 비율(0~2, ry 단위)."""
    lo, hi = 0.0, 2.0
    for _ in range(50):
        d = (lo + hi) / 2
        a = (math.acos(1 - d) - (1 - d) * math.sqrt(max(0.0, 2 * d - d * d))) / math.pi
        if a < frac:
            lo = d
        else:
            hi = d
    return (lo + hi) / 2


D_1_12 = honey_level_for_fraction(1 / 12)


def draw_spoon(c, cx, cy, rx, ry, hx1, h0, h1, sw, honey_d, slosh_amp, t, alpha=1.0, hl=True):
    """honey_d: 꿀 높이 (ry 단위, 0~2). 표면은 출렁임(진폭 slosh_amp)."""
    path = spoon_path(cx, cy, rx, ry, cx + rx, hx1, h0, h1)
    if alpha < 1:
        c.saveLayer(None, skia.Paint(Alphaf=alpha))
    c.drawPath(path, fill(CREAM))
    # 볼 안쪽 테두리 (깊이감)
    c.drawArc(oval(cx, cy, rx - 18, ry - 16), 200, 140, False, stroke(NEUTRAL, 4))
    if honey_d > 0.001:
        c.save()
        clip = skia.Path()
        clip.addOval(oval(cx, cy, rx - sw * 0.3, ry - sw * 0.3))
        c.clipPath(clip, doAntiAlias=True)
        level = cy + ry - honey_d * ry
        hp = skia.Path()
        n = 48
        tilt = slosh_amp * math.sin(2 * math.pi * t)
        for i in range(n + 1):
            x = cx - rx + 2 * rx * i / n
            u = (x - cx) / rx
            y = level + tilt * u + slosh_amp * 0.35 * math.sin(2 * math.pi * (u * 1.5 - t * 1.0))
            if i == 0:
                hp.moveTo(x, y)
            else:
                hp.lineTo(x, y)
        hp.lineTo(cx + rx, cy + ry + 10)
        hp.lineTo(cx - rx, cy + ry + 10)
        hp.close()
        c.drawPath(hp, fill(HONEY))
        # 표면 선
        surf = skia.Path()
        for i in range(n + 1):
            x = cx - rx + 2 * rx * i / n
            u = (x - cx) / rx
            y = level + tilt * u + slosh_amp * 0.35 * math.sin(2 * math.pi * (u * 1.5 - t * 1.0))
            if i == 0:
                surf.moveTo(x, y)
            else:
                surf.lineTo(x, y)
        c.drawPath(surf, stroke(DEEP, max(3, sw * 0.55)))
        # 하이라이트 1개
        depth = honey_d * ry
        if hl and depth > 30:
            hw = min(18, depth * 0.22)
            hlp = skia.Path()
            for i in range(13):
                u = -0.62 + 0.36 * i / 12
                x = cx + u * rx
                y = level + tilt * u + slosh_amp * 0.35 * math.sin(2 * math.pi * (u * 1.5 - t)) + hw * 1.6 + 6
                # 볼 곡면을 따라 아래로 약간 휘게
                y += (u + 0.44) ** 2 * 40
                if i == 0:
                    hlp.moveTo(x, y)
                else:
                    hlp.lineTo(x, y)
            c.drawPath(hlp, stroke(CREAM, hw, 0.55))
        c.restore()
    c.drawPath(path, stroke(INK, sw))
    if alpha < 1:
        c.restore()


S1_SPOON = dict(cx=400, cy=960, rx=150, ry=100, hx1=930, h0=15, h1=24, sw=6)
S1_HONEY_START = 1.55     # 0초(=30초) 꿀 높이 (ry 단위)
S1_HONEY_FULL = 1.86


def draw_s1_spoon(c, t, alpha=1.0, honey=None, sq=1.0):
    sp = S1_SPOON
    d = S1_HONEY_START if honey is None else honey
    c.save()
    if sq != 1.0:
        c.translate(sp["cx"], sp["cy"])
        c.scale(sq, 2 - sq)
        c.translate(-sp["cx"], -sp["cy"])
    draw_spoon(c, sp["cx"], sp["cy"], sp["rx"], sp["ry"], sp["hx1"], sp["h0"], sp["h1"], sp["sw"],
               d, 4, t, alpha)
    c.restore()


# ───────────────────────── 꿀벌 아이콘 ─────────────────────────


def draw_bee(c, x, y, sc=1.0, rot=0.0, wing=1.0, alpha=1.0, mirror=1.0):
    if sc <= 0.001 or alpha <= 0.003:
        return
    c.save()
    c.translate(x, y)
    if rot:
        c.rotate(rot)
    c.scale(sc * mirror, sc)
    if alpha < 1:
        c.saveLayer(skia.Rect(-90, -90, 90, 70), skia.Paint(Alphaf=alpha))
    # 날개 (몸통 뒤)
    for (wx, wy, ang) in ((-8, -46, -20), (16, -50, 15)):
        c.save()
        c.translate(wx, wy)
        c.rotate(ang)
        c.translate(0, 18)
        c.scale(1, wing)
        c.translate(0, -18)
        r = oval(0, 0, 27, 20)
        c.drawOval(r, fill(CREAM, 0.9))
        c.drawOval(r, stroke(INK, 4))
        c.restore()
    body = oval(0, 0, 60, 42)
    # 침
    sting = skia.Path()
    sting.moveTo(56, -7)
    sting.lineTo(70, 0)
    sting.lineTo(56, 7)
    sting.close()
    c.drawPath(sting, fill(INK))
    c.drawPath(sting, stroke(INK, 3))
    c.drawOval(body, fill(HONEY))
    c.save()
    bp = skia.Path()
    bp.addOval(body)
    c.clipPath(bp, doAntiAlias=True)
    c.drawRect(skia.Rect(-12 - 7, -50, -12 + 7, 50), fill(INK))
    c.drawRect(skia.Rect(18 - 7, -50, 18 + 7, 50), fill(INK))
    c.restore()
    c.drawOval(body, stroke(INK, 5))
    c.drawCircle(-40, -6, 6, fill(INK))
    if alpha < 1:
        c.restore()
    c.restore()


# ───────────────────────── 라벨 알약 / 재생 바 ─────────────────────────

LABELS = [
    ("01 · 수명", 3.00, 7.60),
    ("02 · 꽃", 8.00, 13.60),
    ("03 · 비행", 14.00, 19.55),
    ("04 · 정답", 20.00, 25.70),
]


def draw_labels(c, t):
    for text, t_in, t_out in LABELS:
        if t < t_in or t > t_out + 0.3:
            continue
        sc = e_out_back(prog(t, t_in, 0.25), 1.7)
        if t > t_out:
            sc *= 1 - e_in_back(prog(t, t_out, 0.25), 1.4)
        if sc <= 0.001:
            continue
        sg = [seg(text, B, 32)]
        wdt = segs_width(sg) + 56
        rr = skia.RRect.MakeRectXY(skia.Rect(80, 236, 80 + wdt, 292), 28, 28)
        c.save()
        c.translate(80, 264)
        c.scale(sc, sc)
        c.translate(-80, -264)
        c.drawRRect(rr, fill(CREAM))
        c.drawRRect(rr, stroke(INK, 4))
        draw_segs(c, sg, 108, 275)
        c.restore()


SEG_T = [0, 3, 8, 14, 20, 26, 30]
SEG_X0, SEG_W, SEG_GAP = 190, (770 - 5 * 12) / 6, 12


def knob_x(t):
    if t >= 29.4:
        return lerp(960, 190, e_inout_cubic(prog(t, 29.4, 0.6)))
    for i in range(6):
        if t < SEG_T[i + 1]:
            f = (t - SEG_T[i]) / (SEG_T[i + 1] - SEG_T[i])
            return SEG_X0 + i * (SEG_W + SEG_GAP) + f * SEG_W
    return 960


def draw_player(c, t):
    rr = skia.RRect.MakeRectXY(skia.Rect(80, 1300, 1000, 1396), 48, 48)
    c.drawRRect(rr, fill(CREAM))
    c.drawRRect(rr, stroke(INK, 5))
    tri = skia.Path()
    tri.moveTo(118, 1324)
    tri.lineTo(118, 1372)
    tri.lineTo(156, 1348)
    tri.close()
    c.drawPath(tri, fill(INK))
    c.drawPath(tri, stroke(INK, 4))
    kx = knob_x(t)
    for i in range(6):
        x0 = SEG_X0 + i * (SEG_W + SEG_GAP)
        r = skia.RRect.MakeRectXY(skia.Rect(x0, 1341, x0 + SEG_W, 1355), 7, 7)
        c.drawRRect(r, fill(NEUTRAL))
        if kx > x0:
            c.save()
            c.clipRect(skia.Rect(x0 - 1, 1330, min(kx, x0 + SEG_W) + 0.01, 1370))
            c.drawRRect(r, fill(HONEY))
            c.restore()
    c.drawCircle(kx, 1348, 20, fill(INK))
    c.drawCircle(kx, 1348, 8, fill(CREAM))


# ───────────────────────── 장면 1: 훅 (0~3초) ─────────────────────────

S1_L1 = [seg("꿀벌 한 마리가", R, 72)]
S1_L2 = [seg("평생 만드는 꿀은", XB, 96)]
S1_L3 = [seg("얼마나 될까", XB, 96)]


def s1_honey(t):
    return lerp(S1_HONEY_START, S1_HONEY_FULL, e_out_cubic(prog(t, 0.75, 0.5)))


def draw_s1(c, t):
    # 3줄 밑 하이라이트 바 (글자 뒤)
    hp = e_out_cubic(prog(t, 0.45, 0.30))
    if hp > 0:
        x1 = 140 + segs_width(S1_L3) + 8
        c.drawRRect(skia.RRect.MakeRectXY(skia.Rect(136, 690, lerp(136, x1, hp), 722), 4, 4), fill(HONEY))
    reveal(c, S1_L1, 140, 470, t, 0.00)
    reveal(c, S1_L2, 140, 590, t, 0.10)
    reveal(c, S1_L3, 140, 705, t, 0.20)
    # 스푼: 0초부터 보임 → 0.5초 클릭과 함께 살짝 눌렸다 튕김, 0.75~1.25 꿀이 가득 차오름
    sq = 1.0
    if 0.5 <= t < 1.0:
        k = prog(t, 0.5, 0.45)
        sq = 1 + 0.05 * math.sin(math.pi * k) * (1 - k) * 2.2
    draw_s1_spoon(c, t, 1.0, s1_honey(t), sq)
    # 물음표 팝 + 보빙
    if t >= 1.0:
        p = prog(t, 1.0, 0.30)
        sc = e_out_back(p, 2.2)
        rot = lerp(-12, 0, e_out_cubic(p))
        bob = 6 * math.sin(2 * math.pi * (t - 1.3)) if t > 1.3 else 0
        sg = [seg("?", XB, 260, DEEP, 0)]
        wq = segs_width(sg)
        c.save()
        c.translate(840, 1110 + bob)
        c.rotate(rot)
        c.scale(sc, sc)
        draw_segs(c, sg, -wq / 2, 260 * 0.36)
        c.restore()


# ───────────────────────── 장면 2: 수명 (3~8초) ─────────────────────────

S2_H = [seg("여름철 일벌의 수명은", R, 64)]
S2_BIG = [seg("약 ", R, 96), seg("5~6주", XB, 160)]
S2_NOTE = [seg("(계절에 따라 다름 · 늦가을에 태어난 벌은 몇 달까지)", R, 32, MUTED, 0)]
DOT_X0, DOT_DX, DOT_Y0, DOT_DY, DOT_R = 176, (904 - 176) / 6, 780, 76, 28
DASH = skia.DashPathEffect.Make([10, 8], 0)


def draw_s2(c, t):
    reveal(c, S2_H, 140, 450, t, 3.10)
    punch_text(c, S2_BIG, 140, 640, t, 3.30, 0.30, 1.20, 1.7)
    # 호흡 스케일 (6.5초~)
    br = 1 + 0.015 * (1 - math.cos(2 * math.pi * (t - 6.5))) if t > 6.5 else 1.0
    gx, gy = (DOT_X0 + 904) / 2, (DOT_Y0 + 1160) / 2
    c.save()
    c.translate(gx, gy)
    c.scale(br, br)
    c.translate(-gx, -gy)
    for k in range(6):
        for j in range(7):
            i = k * 7 + j
            x, y = DOT_X0 + j * DOT_DX, DOT_Y0 + k * DOT_DY
            s_in = e_out_back(prog(t, 3.05 + 0.006 * i, 0.22), 1.7)
            if s_in <= 0:
                continue
            tf0 = 3.50 + 0.5 * k + 0.05 * j
            pf = prog(t, tf0, 0.20)
            r = DOT_R * s_in
            ol = stroke(INK, 4)
            if k >= 4:
                ol.setPathEffect(DASH)
            c.drawCircle(x, y, r, fill(DOT))
            if pf > 0:
                e = e_out_back(pf, 2.2)
                rh = DOT_R * (0.6 + 0.4 * e)
                c.drawCircle(x, y, rh, fill(HONEY, clamp(pf / 0.25)))
                r = max(r, rh)
            c.drawCircle(x, y, r, ol)
    c.restore()
    a = e_out_cubic(prog(t, 6.5, 0.3))
    if a > 0:
        draw_segs(c, S2_NOTE, 140, 1236, a)


# ───────────────────────── 장면 3: 꽃 (8~14초) ─────────────────────────

S3_H = [seg("꿀 450g을 만들려면", R, 64)]
S3_SUB = [seg("송이의 꽃을 찾아가요", B, 60)]
S3_NOTE = [seg("(벌 무리 전체 기준 · 평균값)", R, 34, MUTED, 0)]
BAR_X = [140, 310, 480, 650, 820]
BAR_H = [160, 220, 280, 330, 360]
BASE_Y = 1200
COUNTER_SIZE = fit_size(lambda s: [seg("2,000,000", XB, s)], 150)


def bar_path(x, h, w=120, r=20):
    p = skia.Path()
    if h <= 0.5:
        return p
    rr = min(r, h, w / 2)
    p.moveTo(x, BASE_Y)
    p.lineTo(x, BASE_Y - h + rr)
    p.arcTo(skia.Rect(x, BASE_Y - h, x + 2 * rr, BASE_Y - h + 2 * rr), 180, 90, False)
    p.lineTo(x + w - rr, BASE_Y - h)
    p.arcTo(skia.Rect(x + w - 2 * rr, BASE_Y - h, x + w, BASE_Y - h + 2 * rr), 270, 90, False)
    p.lineTo(x + w, BASE_Y)
    return p


def draw_flower(c, x, y, sc, rot):
    if sc <= 0.001:
        return
    c.save()
    c.translate(x, y)
    c.rotate(rot)
    c.scale(sc, sc)
    for k in range(5):
        a = math.radians(-90 + 72 * k)
        px, py = 22 * math.cos(a), 22 * math.sin(a)
        c.drawCircle(px, py, 18, fill(HONEY))
        c.drawCircle(px, py, 18, stroke(INK, 3))
    c.drawCircle(0, 0, 14, fill(DEEP))
    c.drawCircle(0, 0, 14, stroke(INK, 3))
    c.restore()


def s3_tops():
    return [(BAR_X[i] + 60, BASE_Y - BAR_H[i]) for i in range(5)]


def poly_sample(pts, s):
    seglen = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    tot = sum(seglen)
    d = s * tot
    for i, L in enumerate(seglen):
        if d <= L or i == len(seglen) - 1:
            f = clamp(d / L) if L else 0
            return (lerp(pts[i][0], pts[i + 1][0], f), lerp(pts[i][1], pts[i + 1][1], f))
        d -= L
    return pts[-1]


GLOBE_C, GLOBE_R = (540, 920), 160


def circ_sample(s, r=GLOBE_R):
    a = 2 * math.pi * s
    return (GLOBE_C[0] + r * math.sin(a), GLOBE_C[1] - r * math.cos(a))


def draw_s3(c, t):
    out = 13.60
    reveal(c, S3_H, 140, 450, t, 8.10, out_t0=out)
    # 카운터
    if t >= 8.5:
        v = int(round(2_000_000 * e_out_expo(prog(t, 8.5, 2.0)) / 1000.0)) * 1000
        sg = [seg(f"{v:,}", XB, COUNTER_SIZE)]
        pp = prog(t, 10.5, 0.30)
        sc = lerp(1.08, 1.0, e_out_back(pp, 1.7)) if t >= 10.5 else 1.0
        size = COUNTER_SIZE
        wdt = segs_width(sg)
        off = 60 * (1 - e_out_expo(prog(t, 8.5, 0.3)))
        if t > out:
            off -= (size * 1.3 + 40) * e_in_expo(prog(t, out + 0.04, 0.3))
        c.save()
        c.clipRect(skia.Rect(100, 640 - size - 10, 980, 640 + size * 0.28 + 10))
        cx, cy = 140 + wdt / 2, 640 - size * 0.36
        c.translate(cx, cy + off)
        c.scale(sc, sc)
        c.translate(-cx, -cy)
        draw_segs(c, sg, 140, 640)
        c.restore()
    reveal(c, S3_SUB, 140, 730, t, 10.40, 0.30, out_t0=out + 0.08)
    na = e_out_cubic(prog(t, 10.8, 0.3)) * (1 - e_out_cubic(prog(t, out, 0.25)))
    if na > 0:
        draw_segs(c, S3_NOTE, 140, 790, na)
    # 기준선
    bl = e_out_expo(prog(t, 8.0, 0.5))
    shrink = e_inout_cubic(prog(t, 13.6, 0.4))
    if bl > 0 and shrink < 1:
        xa, xb = 110, 970
        xm = 540
        x0 = lerp(xm, xa, bl)
        x1 = lerp(xm, xb, bl)
        x0, x1 = lerp(x0, xm, shrink), lerp(x1, xm, shrink)
        c.drawLine(x0, BASE_Y, x1, BASE_Y, stroke(INK, 5))
    # 막대 + 꽃
    down = e_inout_cubic(prog(t, 13.6, 0.5))
    tops = s3_tops()
    for i in range(5):
        tg = 8.5 + 0.25 * i
        p = prog(t, tg, 0.45)
        if p <= 0:
            continue
        h = BAR_H[i] * e_out_back(p, 1.2) * (1 - down)
        bp = bar_path(BAR_X[i], h)
        c.drawPath(bp, fill(CREAM))
        c.drawPath(bp, stroke(INK, 5))
        # 꽃
        fsc = e_out_back(prog(t, tg + 0.45, 0.20), 2.2)
        fsc *= 1 - e_in_back(prog(t, 13.0 + 0.05 * i, 0.20), 1.7)
        amp = 4 * clamp((t - 10.6) / 0.4)
        rot = amp * math.sin(2 * math.pi * (t - 0.1 * i))
        bob = 3 * math.sin(2 * math.pi * (t * 0.5 - 0.1 * i)) * clamp((t - 10.6) / 0.4)
        draw_flower(c, tops[i][0], BASE_Y - h + bob, max(0, fsc), rot)
    # 꼭대기 점 + 꺾은선 → 원(지구 외곽선)으로 모핑
    line_p = e_inout_cubic(prog(t, 13.25, 0.35))
    m = e_inout_cubic(prog(t, 13.6, 0.5))
    if line_p > 0:
        n = 90
        pts = []
        for k in range(n + 1):
            s = k / n * line_p if m == 0 else k / n
            a = poly_sample(tops, s)
            b = circ_sample(s)
            pts.append((lerp(a[0], b[0], m), lerp(a[1], b[1], m)))
        path = skia.Path()
        path.moveTo(*pts[0])
        for p_ in pts[1:]:
            path.lineTo(*p_)
        if m >= 0.999:
            path.close()
        c.drawPath(path, stroke(INK, lerp(6, 5, m)))
    for i in range(5):
        ds = e_out_back(prog(t, 13.0 + 0.05 * i, 0.20), 1.7)
        ds *= 1 - e_in_back(prog(t, 13.85, 0.25), 1.5)
        if ds <= 0.001:
            continue
        # 폴리라인 위 매개변수
        seglen = [math.dist(tops[k], tops[k + 1]) for k in range(4)]
        sp = sum(seglen[:i]) / sum(seglen)
        a = tops[i]
        b = circ_sample(sp)
        c.drawCircle(lerp(a[0], b[0], m), lerp(a[1], b[1], m), 9 * ds, fill(INK))


# ───────────────────────── 장면 4: 비행 (14~20초) ─────────────────────────

S4_H = [seg("꿀 450g을 위해 나는 거리", R, 56)]
S4_NOTE = [seg("(벌 무리 전체 기준 · 평균값)", R, 34, MUTED, 0)]
S4_EQ = [seg("= 지구 ", XB, 72), seg("약 ", R, 72), seg("2.2바퀴", XB, 72)]
RINGS = [(190, 15.0, 1.0, 360, "io"), (215, 16.0, 1.0, 360, "io"), (240, 17.0, 0.5, 72, "oc")]


def ring_state(t):
    """각 링의 현재 각도와 벌(링 끝)의 위치."""
    sweeps = []
    tip = None
    for r, t0, d, full, ez in RINGS:
        p = prog(t, t0, d)
        e = e_inout_cubic(p) if ez == "io" else e_out_cubic(p)
        sw = full * e
        sweeps.append((r, sw))
        if t >= t0:
            tip = (r, sw)
    return sweeps, tip


def draw_globe(c, t, sc_fill, outline_r=GLOBE_R, fill_col=None, mer_a=1.0):
    cx, cy = GLOBE_C
    rf = GLOBE_R * sc_fill
    if rf > 0.5:
        c.drawCircle(cx, cy, rf, fill(CREAM) if fill_col is None else skia.Paint(AntiAlias=True, Color=fill_col))
        if mer_a > 0.01:
            c.save()
            gp = skia.Path()
            gp.addCircle(cx, cy, max(0.1, rf - 2))
            c.clipPath(gp, doAntiAlias=True)
            k = rf / GLOBE_R
            rotv = 2 * math.pi * (t - 14.0) / 6.0
            for j in range(3):
                th = rotv + j * math.pi / 3 + 0.38
                rx = abs(math.sin(th)) * GLOBE_R * k
                if rx > 1.5:
                    c.drawOval(oval(cx, cy, rx, GLOBE_R * k), stroke(NEUTRAL, 3, mer_a))
                else:
                    c.drawLine(cx, cy - rf, cx, cy + rf, stroke(NEUTRAL, 3, mer_a))
            c.drawLine(cx - rf, cy, cx + rf, cy, stroke(NEUTRAL, 3, mer_a))
            c.drawOval(oval(cx, cy - 0.5 * rf, rf * 0.866, rf * 0.06), stroke(NEUTRAL, 3, mer_a * 0.0))
            c.restore()
    c.drawCircle(cx, cy, max(outline_r, rf), stroke(INK, 5))


def draw_s4(c, t):
    reveal(c, S4_H, 140, 430, t, 14.05)
    if t >= 14.3:
        v = int(round(88_500 * e_out_expo(prog(t, 14.3, 1.7)) / 100.0)) * 100
        sg = [seg(f"{v:,}", XB, 140), seg("km", B, 80, INK, -0.01)]
        reveal(c, sg, 140, 590, t, 14.3, 0.35)
    na = e_out_cubic(prog(t, 16.0, 0.3))
    if na > 0:
        draw_segs(c, S4_NOTE, 140, 645, na)
    # 지구: 외곽선은 모핑에서 이어받고(14.1~), 면과 경선이 14.4부터 팝
    if t >= 14.1:
        gs = e_out_back(prog(t, 14.4, 0.5), 1.4)
        draw_globe(c, t, gs)
    # 궤도 링
    sweeps, tip = ring_state(t)
    cx, cy = GLOBE_C
    for r, sw in sweeps:
        if sw > 0.05:
            c.drawArc(oval(cx, cy, r, r), -90, sw, False, stroke(HONEY, 10))
    if tip is not None:
        r, sw = tip
        # 링이 바뀔 때 반지름을 부드럽게 이어 줌
        a = math.radians(sw - 90)
        bx, by = cx + r * math.cos(a), cy + r * math.sin(a)
        if t > 17.5:
            by += 4 * math.sin(2 * math.pi * (t - 17.5))
        head = math.radians(sw)              # 진행 방향 각 (시계 방향 원운동의 접선)
        fx = clamp(math.cos(head) * 4, -1, 1) if t < 17.5 else 1.0
        tilt = 22 * math.sin(head) * fx if t < 17.5 else 0
        wing = 1 - 0.3 * (0.5 + 0.5 * math.sin(2 * math.pi * t * 8))
        # 오른쪽을 보도록 좌우 반전(mirror=-1) 후 fx로 방향 전환
        draw_bee(c, bx, by, 0.42, tilt, wing, 1.0, mirror=-fx if abs(fx) > 0.02 else -0.02)
    wipe_lr(c, S4_EQ, 140, 1236, t, 17.5)


def draw_s4_mask(c, t):
    """19.5~20.0 원형 마스크 확장: 지구가 커지며 카드 전체를 TINT로 덮는다."""
    p = e_in_expo(prog(t, 19.5, 0.5))
    r = lerp(GLOBE_R, 1250, p)
    cx, cy = GLOBE_C
    k = clamp(p * 3)
    col = skia.Color4f.FromColor(hexc(CREAM))
    col2 = skia.Color4f.FromColor(hexc(TINT))
    mix = skia.Color4f(lerp(col.fR, col2.fR, k), lerp(col.fG, col2.fG, k), lerp(col.fB, col2.fB, k), 1).toColor()
    c.drawCircle(cx, cy, r, skia.Paint(AntiAlias=True, Color=mix))
    c.drawCircle(cx, cy, r, stroke(INK, 5))


# ───────────────────────── 장면 5: 반전 (20~26초) ─────────────────────────

S5_H = [seg("한 마리", B, 64), seg("가 평생 모은 꿀은", R, 64)]
S5_NOTE = [seg("(일벌 1마리 기준 · 평균값)", R, 34, MUTED, 0)]
S5_TSP = [seg("티스푼", B, 80)]
S5_FRAC = [seg("1/12", XB, 220, DEEP)]
S5_SP = dict(cx=420, cy=770, rx=210, ry=140, hx1=980, h0=18, h1=30, sw=7)
PIE_C, PIE_R = (820, 1126), 90


def draw_s5(c, t):
    reveal(c, S5_H, 140, 430, t, 20.05)
    na = e_out_cubic(prog(t, 20.2, 0.3))
    if na > 0:
        draw_segs(c, S5_NOTE, 140, 485, na)
    # 스푼
    if t >= 20.1:
        sp = S5_SP
        ps = prog(t, 20.1, 0.5)
        sc = lerp(0.6, 1.0, e_out_back(ps, 1.7))
        al = clamp(ps / 0.15)
        tilt = 3 * math.sin(2 * math.pi * e_inout_cubic(prog(t, 21.0, 1.0)))
        if t > 22.6:
            tilt += 0.8 * math.sin(2 * math.pi * (t - 22.6) / 2.0)
        ph = prog(t, 20.6, 0.4)
        d = D_1_12 * e_out_back(ph, 1.2) if t >= 20.6 else 0
        amp = 2 + 3 * math.exp(-max(0, t - 21.0) * 2) if t > 20.6 else 2
        c.save()
        c.translate(sp["cx"], sp["cy"])
        c.rotate(tilt)
        c.scale(sc, sc)
        c.translate(-sp["cx"], -sp["cy"])
        draw_spoon(c, sp["cx"], sp["cy"], sp["rx"], sp["ry"], sp["hx1"], sp["h0"], sp["h1"], sp["sw"],
                   d, amp, t, al, hl=False)
        c.restore()
    reveal(c, S5_TSP, 140, 1020, t, 22.0, 0.30)
    fl = 2 * math.sin(2 * math.pi * (t - 22.6) / 2.0) if t > 22.6 else 0
    punch_text(c, S5_FRAC, 140, 1232 + fl, t, 22.0, 0.30, 1.25, 1.7)
    # 원 그래프
    pc = e_out_back(prog(t, 22.10, 0.25), 1.7)
    if pc > 0:
        cx, cy = PIE_C
        c.save()
        c.translate(cx, cy)
        c.scale(pc, pc)
        c.drawCircle(0, 0, PIE_R, fill(CREAM))
        c.drawCircle(0, 0, PIE_R, stroke(INK, 5))
        ang = 30 * e_out_cubic(prog(t, 22.25, 0.35))
        if ang > 0.2:
            pulse = 1 + 0.03 * (1 + math.cos(2 * math.pi * (t - 23.0))) if t > 22.6 else 1.0
            pulse = lerp(1.0, pulse, clamp((t - 22.6) / 0.3))
            c.save()
            c.scale(pulse, pulse)
            wedge = skia.Path()
            wedge.moveTo(0, 0)
            wedge.arcTo(oval(0, 0, PIE_R, PIE_R), -90, ang, False)
            wedge.close()
            c.drawPath(wedge, fill(HONEY))
            c.drawPath(wedge, stroke(DEEP, 3))
            c.restore()
        c.drawCircle(0, 0, 6, fill(INK))
        c.restore()


# ───────────────────────── 장면 6: 마무리 + 루프 (26~30초) ─────────────────────────

S6_H = [seg("그러니까 꿀 한 티스푼은", R, 60)]
S6_BIG = [seg("12", XB, 110, DEEP), seg("마리의 일생", XB, 110)]
BEE_COLS = [270, 450, 630, 810]
BEE_ROWS = [600, 780, 960]


def draw_s6(c, t):
    ta = 1 - e_in_cubic(prog(t, 29.3, 0.4))
    reveal(c, S6_H, 140, 430, t, 25.95, alpha=ta)
    reveal(c, S6_BIG, 140, 1180, t, 28.00, alpha=ta)
    fly = prog(t, 29.4, 0.5)
    tx, ty = S1_SPOON["cx"], S1_SPOON["cy"]

    def bee_at(i, tt):
        r_, cc = divmod(i, 4)
        x, y = BEE_COLS[cc], BEE_ROWS[r_]
        t0 = 26.25 + 0.125 * i
        p = prog(tt, t0, 0.25)
        sc = e_out_back(p, 2.2)
        rot = lerp(-15, 0, e_out_cubic(p))
        bob = 3 * math.sin(2 * math.pi * (tt - t0) * 1.0 + i * 0.7) * clamp((tt - t0 - 0.25) / 0.3)
        f = e_in_cubic(prog(tt, 29.4, 0.5))   # easeInExpo는 마지막 3프레임에 몰려 튐 → easeInCubic
        x, y = lerp(x, tx, f), lerp(y + bob, ty, f)
        sc *= lerp(1, 0.3, f)
        if f > 0:
            rot += 18 * f * (1 if x > tx else -1)
        return x, y, sc, rot

    for i in range(12):
        t0 = 26.25 + 0.125 * i
        if t < t0:
            continue
        wing = 1 - 0.3 * (0.5 - 0.5 * math.cos(2 * math.pi * (t - t0) / 0.25))
        a = 1 - clamp((t - 29.82) / 0.08)
        if a <= 0:
            continue
        if fly > 0:
            for lag, ga in ((0.08, 0.12), (0.04, 0.25)):
                x, y, sc, rot = bee_at(i, t - lag)
                draw_bee(c, x, y, sc, rot, wing, ga * a)
        x, y, sc, rot = bee_at(i, t)
        draw_bee(c, x, y, sc, rot, wing, a)


# ───────────────────────── 한 프레임 합성 ─────────────────────────


def card_scale(t):
    s = 1.0
    if t < 0.35:
        s *= lerp(1.06, 1.0, e_out_back(prog(t, 0, 0.35), 1.7))
    if 20.0 <= t < 20.35:
        s *= lerp(1.04, 1.0, e_out_back(prog(t, 20.0, 0.35), 1.7))
    return s


def with_transform(c, sc=1.0, dx=0.0, alpha=1.0):
    c.save()
    if alpha < 1:
        c.saveLayer(None, skia.Paint(Alphaf=max(0.0, alpha)))
    c.translate(dx, 0)
    if sc != 1.0:
        c.translate(*CARD_C)
        c.scale(sc, sc)
        c.translate(-CARD_C[0], -CARD_C[1])


def end_transform(c, alpha=1.0):
    if alpha < 1:
        c.restore()
    c.restore()


def draw_content(c, t):
    # 장면 1 (+ 2.8~3.2 아래→위 마스크 와이프)
    if t < 3.2:
        wp = e_inout_cubic(prog(t, 2.8, 0.4))
        yw = lerp(1257, 325, wp)
        c.save()
        c.clipRect(skia.Rect(0, 0, W, yw))
        draw_s1(c, t)
        c.restore()
        if wp > 0:
            c.save()
            c.clipRect(skia.Rect(0, yw, W, H))
            draw_s2(c, t)
            c.restore()
            if wp < 1:
                band = skia.Rect(0, yw - 2, W, yw + 26)
                c.drawRect(band, fill(HONEY))
                c.drawLine(0, yw - 2, W, yw - 2, stroke(INK, 5, cap=skia.Paint.kButt_Cap))
                c.drawLine(0, yw + 26, W, yw + 26, stroke(INK, 5, cap=skia.Paint.kButt_Cap))
        return
    if t < 8.0:
        pe = e_in_expo(prog(t, 7.6, 0.4))
        a = 1 - pe
        with_transform(c, lerp(1.0, 0.92, pe), 0, a)
        draw_s2(c, t)
        end_transform(c, a)
        return
    if t < 14.1:
        pi_ = e_out_expo(prog(t, 8.0, 0.35))
        with_transform(c, lerp(1.10, 1.0, pi_), 0, pi_)
        draw_s3(c, t)
        end_transform(c, pi_)
        if t < 14.0:
            return
    if t < 20.0:
        draw_s4(c, t)
        if t >= 19.5:
            draw_s4_mask(c, t)
        return
    # 장면 5 → 6 푸시 (두 장면이 한 몸처럼 같이 밀려 이동)
    dx = -1080 * e_inout_cubic(prog(t, 25.7, 0.5))
    if t < 26.2:
        c.save()
        c.translate(dx, 0)
        draw_s5(c, t)
        c.restore()
    if t >= 25.7:
        c.save()
        c.translate(dx + 1080, 0)
        if t >= 29.5:
            draw_s1_spoon(c, t, e_out_cubic(prog(t, 29.5, 0.5)), S1_HONEY_START)
        draw_s6(c, t)
        c.restore()


def render(t):
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    draw_bg(c, t)
    sc = card_scale(t)
    c.save()
    c.translate(*CARD_C)
    c.scale(sc, sc)
    c.translate(-CARD_C[0], -CARD_C[1])
    c.drawRRect(card_rrect(), fill(TINT))
    c.save()
    c.clipRRect(card_rrect(2.5), doAntiAlias=True)
    draw_content(c, t)
    c.restore()
    c.drawRRect(card_rrect(), stroke(INK, 5))
    c.restore()
    draw_labels(c, t)
    draw_player(c, t)
    return surf.makeImageSnapshot().toarray()


def render_bytes(f):
    return render(f / FPS).tobytes()


# ───────────────────────── 소리 ─────────────────────────

N = int(DUR * SR)
_rng = np.random.default_rng(7)


def db(x):
    return 10 ** (x / 20)


def place(buf, sig, t0, gain=1.0, wrap=True):
    i0 = int(round(t0 * SR))
    idx = (np.arange(len(sig)) + i0)
    if wrap:
        idx %= len(buf)
        np.add.at(buf, idx, sig * gain)
    else:
        m = idx < len(buf)
        buf[idx[m]] += sig[m] * gain


def svf_bandpass(x, fc, q=1.4):
    """시간에 따라 변하는 중심 주파수 fc(배열)의 상태변수 대역통과 필터."""
    low = band = 0.0
    out = np.zeros_like(x)
    damp = 1.0 / q
    for i in range(len(x)):
        f = 2 * math.sin(math.pi * min(fc[i], SR / 6) / SR)
        high = x[i] - low - damp * band
        band += f * high
        low += f * band
        out[i] = band
    return out


def fft_filter(x, lo=None, hi=None):
    X = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    m = np.ones_like(fr)
    if lo:
        m *= 1 / np.sqrt(1 + (lo / np.maximum(fr, 1)) ** 4)
    if hi:
        m *= 1 / np.sqrt(1 + (fr / hi) ** 4)
    return np.fft.irfft(X * m, len(x))


def norm(x):
    return x / (np.abs(x).max() + 1e-9)


def sfx_whoosh(rev=False):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    fc = 400 * (3000 / 400) ** (t / 0.25)
    if rev:
        fc = fc[::-1]
    x = svf_bandpass(_rng.normal(0, 1, n), fc, 1.2)
    env = np.where(t < 0.08, t / 0.08, np.clip(1 - (t - 0.08) / 0.17, 0, 1)) ** 1.5
    return norm(x * env) * db(-14)


def sfx_pop(f):
    n = int(0.10 * SR)
    t = np.arange(n) / SR
    fr = f * 1.5 ** np.clip(t / 0.06, 0, 1)
    ph = 2 * np.pi * np.cumsum(fr) / SR
    x = np.sin(ph) * np.exp(-t / 0.04)
    x[:40] *= np.linspace(0, 1, 40)
    return x * db(-12)


def sfx_click(f=3000):
    n = int(0.03 * SR)
    t = np.arange(n) / SR
    nb = _rng.normal(0, 1, n) * (t < 0.002) * 0.6
    x = nb + np.sin(2 * np.pi * f * t) * np.exp(-t / 0.006) * (t < 0.02)
    return norm(x) * db(-16)


def sfx_tick():
    n = int(0.012 * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * 4000 * t) * np.exp(-t / 0.003) + _rng.normal(0, 1, n) * (t < 0.0015) * 0.4
    return norm(x) * db(-20)


def sfx_riser(d):
    n = int(d * SR)
    t = np.arange(n) / SR
    f = 200 * (2000 / 200) ** (t / d)
    ph = 2 * np.pi * np.cumsum(f) / SR
    saw = sum(np.sin(k * ph) / k * (k * f < 16000) for k in range(1, 9))
    noise = fft_filter(_rng.normal(0, 1, n), lo=1500)
    x = norm(saw) * 0.6 + norm(noise) * 0.5
    env = t / d
    env[-int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))
    return x * env * db(-15)


def sfx_impact(g=-8):
    n = int(0.6 * SR)
    t = np.arange(n) / SR
    f = 45 + 35 * np.exp(-t / 0.08)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t / 0.12)
    tr = fft_filter(_rng.normal(0, 1, n), hi=6000) * (t < 0.015) * np.exp(-t / 0.005)
    x = x + norm(tr) * 0.5
    x[:20] *= np.linspace(0, 1, 20)
    return norm(x) * db(g)


def make_sfx():
    buf = np.zeros(N)
    for tt in [0.00, 3.50, 8.00, 10.50, 17.50, 22.00, 28.00]:
        place(buf, sfx_impact(-8), tt)
    place(buf, sfx_impact(-5), 20.00)
    for tt in [0.05, 2.85, 3.10, 7.75, 13.75, 14.05, 17.50, 19.60, 20.10, 25.80]:
        place(buf, sfx_whoosh(), tt)
    place(buf, sfx_whoosh(rev=True), 29.45)
    for tt in [0.00, 0.50, 8.00, 14.00, 20.00]:
        place(buf, sfx_click(), tt)
    place(buf, sfx_click(), 3.00)
    for k, tt in enumerate([3.50, 4.00, 4.50, 5.00, 5.50, 6.00]):
        place(buf, sfx_click(2000 + 240 * k), tt)
    pops = [(1.00, 880), (14.50, 660), (16.00, 784), (17.00, 988), (20.60, 1568), (22.25, 1047)]
    pops += list(zip([8.95, 9.20, 9.45, 9.70, 9.95], [660, 740, 830, 990, 1110]))
    pops += list(zip([26.25 + 0.125 * i for i in range(12)],
                     [523, 587, 659, 784, 880, 1047, 1175, 1319, 1568, 1760, 2093, 2349]))
    for tt, f in pops:
        place(buf, sfx_pop(f), tt, 0.7 if tt == 20.60 else 1.0)
    for i in range(16):
        place(buf, sfx_tick(), 8.50 + 0.125 * i, lerp(1.0, 0.2, i / 15))
    for i in range(12):
        place(buf, sfx_tick(), 14.50 + 0.125 * i, lerp(1.0, 0.2, i / 11))
    for t0, t1 in [(2.00, 2.95), (7.50, 7.95), (13.40, 13.95), (19.00, 19.50), (25.40, 25.95), (29.00, 29.90)]:
        place(buf, sfx_riser(t1 - t0), t0, 1.4 if t0 == 19.00 else 1.0)
    return buf


NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def hz(midi):
    return 440 * 2 ** ((midi - 69) / 12)


CHORDS = [[60, 64, 67], [57, 60, 64], [53, 57, 60], [55, 59, 62]]   # C Am F G
ROOTS = [36, 33, 29, 31]


def quiet(t):
    return 21.0 <= t < 22.0


def make_music():
    mus = np.zeros(N)
    drums = np.zeros(N)
    pad = np.zeros(N)
    beat = 0.5
    # 드럼
    kn = int(0.15 * SR)
    kt = np.arange(kn) / SR
    kick = np.sin(2 * np.pi * np.cumsum(40 + 20 * np.exp(-kt / 0.03)) / SR) * np.exp(-kt / 0.06)
    kick[:30] *= np.linspace(0, 1, 30)
    cn = int(0.08 * SR)
    clap = svf_bandpass(_rng.normal(0, 1, cn), np.full(cn, 1500.0), 1.5) * np.exp(-np.arange(cn) / SR / 0.02)
    clap = norm(clap) * db(-18)
    hn = int(0.025 * SR)
    hat = fft_filter(_rng.normal(0, 1, 2048), lo=7000)[:hn] * np.exp(-np.arange(hn) / SR / 0.007)
    hat = norm(hat) * db(-26)
    for n in range(60):
        tt = n * beat
        if quiet(tt):
            continue
        if n % 2 == 0:
            place(drums, kick * db(-6), tt)
        else:
            place(drums, clap, tt)
        if not quiet(tt + 0.25):
            place(drums, hat, tt + 0.25)
    # 베이스 (마디 첫 박 + 3박)
    bn = int(0.95 * SR)
    bt = np.arange(bn) / SR
    for bar in range(15):
        f = hz(ROOTS[bar % 4])
        for off in (0.0, 1.0):
            tt = bar * 2 + off
            if quiet(tt):
                continue
            x = (np.sin(2 * np.pi * f * bt) + 0.3 * np.sin(4 * np.pi * f * bt)) * np.exp(-bt / 0.45)
            x[:60] *= np.linspace(0, 1, 60)
            x[-400:] *= np.linspace(1, 0, 400)
            place(mus, x * db(-10), tt)
    # 플럭 아르페지오 (16분음표)
    pn = int(0.6 * SR)
    pt = np.arange(pn) / SR
    pattern = [0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 4, 3, 2, 1, 2, 3]
    for bar in range(15):
        ch = CHORDS[bar % 4]
        tones = [ch[0], ch[1], ch[2], ch[0] + 12, ch[1] + 12]
        for k in range(16):
            tt = bar * 2 + k * 0.125
            if quiet(tt):
                continue
            m = tones[pattern[k]] + (12 if tt >= 22.0 else 0)
            f = hz(m)
            x = (np.sin(2 * np.pi * f * pt) + 0.25 * np.sin(4 * np.pi * f * pt) * np.exp(-pt / 0.05)) \
                * np.exp(-pt / 0.12)
            x[:30] *= np.linspace(0, 1, 30)
            acc = 1.0 if k % 4 == 0 else 0.7
            place(mus, x * db(-20) * acc * (0.75 if tt >= 22.0 else 1.0), tt)
    # 패드 (3화음 톱니파 + 저역통과, attack 0.3초)
    padn = int(2.3 * SR)
    padt = np.arange(padn) / SR
    for bar in range(15):
        ch = CHORDS[bar % 4]
        x = np.zeros(padn)
        for m in ch:
            f = hz(m)
            ph = 2 * np.pi * f * padt
            x += sum(np.sin(k * ph) / k for k in range(1, 12) if k * f < 8000)
        env = np.clip(padt / 0.3, 0, 1) * np.clip((2.3 - padt) / 0.3, 0, 1)
        place(pad, x * env, bar * 2.0)
    pad = fft_filter(pad, hi=1200)
    pad = norm(pad) * db(-24) * 1.8
    # 잔향: 원형 컨볼루션이라 꼬리가 0초 쪽으로 자연스럽게 겹쳐진다(루프 이음새 없음)
    irn = int(1.2 * SR)
    ir = _rng.normal(0, 1, irn) * np.exp(-np.arange(irn) / SR / 0.3)
    ir = fft_filter(ir, hi=5000)
    ir /= np.sqrt(np.sum(ir ** 2))
    irp = np.zeros(N)
    irp[:irn] = ir
    wet = np.fft.irfft(np.fft.rfft(mus) * np.fft.rfft(irp), N)
    return mus + 0.25 * wet + pad + drums


def write_wav(path, buf):
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.ascontiguousarray(pcm).tobytes())


def measure_lufs(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128",
                        "-f", "null", "-"], capture_output=True, text=True)
    s = r.stderr[r.stderr.rfind("Summary:"):]
    return float(re.search(r"I:\s+(-?[\d.]+) LUFS", s).group(1))


def make_audio(path):
    sfx = make_sfx()
    mus = make_music()
    write_wav(path, np.stack([sfx, sfx], 1))
    l_sfx = measure_lufs(path)
    write_wav(path, np.stack([mus, mus], 1) * 0.3)
    l_mus = measure_lufs(path) - 20 * math.log10(0.3)
    mus *= db((l_sfx - 6) - l_mus)            # 음악은 효과음보다 6dB 낮게
    # 약간의 스테레오 폭 (플럭 잔향 느낌): 왼쪽/오른쪽 미세 지연
    d = int(0.008 * SR)
    L = sfx + mus
    Rr = sfx + np.roll(mus, d)
    L, Rr = fft_filter(L, hi=13000), fft_filter(Rr, hi=13000)   # 날카로운 고역 정리(트루 피크 억제)
    buf = np.stack([L, Rr], 1)
    lim, knee = db(-2.5), db(-8)
    for _ in range(4):
        write_wav(path, buf)
        lufs = measure_lufs(path)
        buf *= db(-14.0 - lufs)
        a = np.abs(buf)
        over = a > knee
        buf[over] = np.sign(buf[over]) * (knee + (lim - knee) * np.tanh((a[over] - knee) / (lim - knee)))
    write_wav(path, buf)
    print(f"  효과음 {l_sfx:.1f} / 음악 {l_mus:.1f} LUFS(조정 전) → 최종 {measure_lufs(path):.2f} LUFS, "
          f"피크 {20 * math.log10(np.abs(buf).max()):.2f} dBFS")


# ───────────────────────── 실행 ─────────────────────────


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        prev = OUT_DIR / "preview"
        prev.mkdir(exist_ok=True)
        for a in sys.argv[2:]:
            t = float(a)
            arr = render(t)
            img = skia.Image.fromarray(arr, colorType=skia.ColorType.kRGBA_8888_ColorType)
            img.save(str(prev / f"p{t:05.2f}.png"), skia.kPNG)
            print("saved", prev / f"p{t:05.2f}.png")
        return
    wav = OUT_DIR / "audio.wav"
    out = OUT_DIR / f"{NAME}.mp4"
    make_audio(wav)
    if len(sys.argv) > 1 and sys.argv[1] == "--audio-only":
        return
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav), "-c:v", "libx264", "-crf", "17", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total = int(DUR * FPS)
    with Pool(8) as pool:
        for f, data in enumerate(pool.imap(render_bytes, range(total), chunksize=6)):
            proc.stdin.write(data)
            if f % 150 == 0:
                print(f"  {f}/{total} 프레임", flush=True)
    proc.stdin.close()
    proc.wait()
    wav.unlink()
    print(f"완성: {out}")


if __name__ == "__main__":
    main()
