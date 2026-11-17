#!/usr/bin/env python3
"""
비 오는 밤, 숯불 군고구마 (32초, 무대사 2D 힐링 요리 ASMR 쇼츠) — AI 도구 없이 코드로 그리고 소리를 합성한다.

원본 기획: prompts/20261116_1507_NOTg3j89Di0.txt
  컷1  0.0~ 2.5  훅: 갈라지는 군고구마 + 김          (컷1->2 하드컷)
  컷2  2.5~ 6.5  빗길: 나뭇잎 우산 쓰고 걸어오는 토리
  컷3  6.5~10.5  오두막: 문 닫고 몸 털기
  컷4 10.5~15.0  나무 대야에서 고구마 씻기
  컷5 15.0~20.0  화로에 부채질, 집게로 고구마 올리기
  컷6 20.0~24.0  집게로 뒤집기, "10분 뒤…", 부드러운 흰 전환
  컷7 24.0~27.5  고구마 반으로 가르기
  컷8 27.5~32.0  동생 미미와 나눠 먹기, 비 그치고 달, 첫 컷으로 이어지는 루프

그림: 2배(2160x3840)로 벡터 도형을 그린 뒤 카메라 줌 영역을 잘라 LANCZOS로 줄인다.
빛(숯불 글로우, 비네팅), 김, 불씨 후광은 절반 해상도 numpy 레이어로 부드럽게 합성한다.
소리: numpy로 빗소리·숯 타닥·김·효과음·오르골을 합성 (외부 음원 없음).

사용:
  .venv/bin/python videos/20261116_1507_NOTg3j89Di0/make_video.py            # 전체 렌더링
  .venv/bin/python videos/20261116_1507_NOTg3j89Di0/make_video.py --preview 1.0 4.2   # 특정 시각 PNG
"""

import math
import re
import subprocess
import sys
import wave
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent
NAME = "20261116_1507_NOTg3j89Di0"
W, H, FPS, DUR = 1080, 1920, 30, 32.0
S = 2
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
FONT_BOLD = 6
SR = 44100

CUTS = [(0.0, 2.5), (2.5, 6.5), (6.5, 10.5), (10.5, 15.0), (15.0, 20.0), (20.0, 24.0), (24.0, 27.5), (27.5, 32.0)]
XFADE = 0.25
SUB_Y = 420            # 자막 세로 중심 (화면 21.9%, 안전 구역 12~65% 안)


def hexc(s):
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))


OUTLINE = hexc("#2B1D14")
NIGHT, RAIN_C, MOON = hexc("#1F2A44"), hexc("#9DB4D9"), hexc("#FFF3C4")
TREE, GROUND, LEAF, LEAF_V = hexc("#2E4A3A"), hexc("#4A3B2C"), hexc("#6BAA4B"), hexc("#3F7A2B")
WALL, FLOOR, PLANK = hexc("#C9A27E"), hexc("#8C6A4A"), hexc("#6E5038")
CLAY, COAL = hexc("#A0522D"), hexc("#3A1F14")
GLOW1, GLOW2, EMBER = hexc("#FF7A1A"), hexc("#FFD166"), hexc("#FFB347")
SKIN, BURN, FLESH, FLESH_C = hexc("#8E3B5B"), hexc("#4B1F2E"), hexc("#F9C74F"), hexc("#FFB703")
HEART, BLUSH = hexc("#FF6B8A"), hexc("#F29C9C")
BODY, SPINE_T, SPINE_M, FACE = hexc("#8B5E3C"), hexc("#5C3A21"), hexc("#6B4A30"), hexc("#F3D9B1")
APRON, POCKET, SCARF = hexc("#E07A5F"), hexc("#C8664D"), hexc("#6FA8DC")
BLANKET, CHECK = hexc("#F4E1C1"), hexc("#E9C46A")
BASKET, TUB, WATER = hexc("#B5835A"), hexc("#A47148"), hexc("#7FB8D6")
FAN_C, TONGS, CLOTH = hexc("#F1E3C8"), hexc("#7A7A7A"), hexc("#F1E3C8")
EYE = (0x24, 0x17, 0x0F)
NOSE = hexc("#3B2416")
LW = 6

# ───────────────────────── 시간 상수 (그림과 소리가 함께 쓴다) ─────────────────────────
SPLIT1 = 0.3                     # 컷1 고구마 벌어짐
WALK_T0, WALK_T1 = 2.5, 6.5
PUDDLES = [(95, 1372, 78), (300, 1385, 64), (468, 1368, 58)]   # x, y, 반폭
DOOR_T = 6.5
SHAKE_T = 7.2
DIP_T = [11.0, 12.0, 13.0]
FAN_T0, FAN_T1 = 15.5, 17.5
PLACE_G = [17.6, 18.15, 18.7]     # 집게로 집기 시작
LAND_T = [g + 0.55 for g in PLACE_G]
FLIP_T = [20.8, 21.6, 22.4]
FLASH_T = 23.85
SPLIT2 = 25.0
MIMI_T = 28.0
GIVE_T = 28.8
BLOW_T = 29.6
BITE_T = 30.2
HEART_T = 30.4


def walk_x(t):
    return -200 + 740 * (t - WALK_T0) / (WALK_T1 - WALK_T0)


def puddle_cross_times():
    out = []
    for px, py, hw in PUDDLES:
        out.append(WALK_T0 + (px + 200) / 740 * (WALK_T1 - WALK_T0))
    return out


SPLASH_T = puddle_cross_times()


# ───────────────────────── 수학 도우미 ─────────────────────────

def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def lerp(a, b, u):
    return a + (b - a) * u


def seg(t, t0, t1):
    return clamp01((t - t0) / (t1 - t0))


def ease_io(u):
    u = clamp01(u)
    return u * u * u * (u * (6 * u - 15) + 10)        # smootherstep


def ease_out(u):
    u = clamp01(u)
    return 1 - (1 - u) ** 3


def ease_in(u):
    u = clamp01(u)
    return u * u


def ease_out_back(u, s=1.7):
    u = clamp01(u)
    return 1 + (s + 1) * (u - 1) ** 3 + s * (u - 1) ** 2


def bump(t, t0, dur):
    return math.sin(math.pi * (t - t0) / dur) if t0 <= t < t0 + dur else 0.0


def mixc(c1, c2, a):
    return tuple(int(round(x + (y - x) * a)) for x, y in zip(c1, c2))


def dark(c, k=0.15):
    return tuple(int(v * (1 - k)) for v in c)


def light(c, k=0.2):
    return tuple(int(v + (255 - v) * k) for v in c)


def lerp_pt(p, q, u):
    return (lerp(p[0], q[0], u), lerp(p[1], q[1], u))


# ───────────────────────── 도형 ─────────────────────────

def ell(cx, cy, rx, ry, n=48, a0=0.0, a1=360.0, closed=True):
    m = n if closed else n
    step = (a1 - a0) / (n if closed else n - 1)
    return [(cx + rx * math.cos(math.radians(a0 + step * k)), cy + ry * math.sin(math.radians(a0 + step * k)))
            for k in range(m)]


def rrect(cx, cy, w, h, r, n=6):
    hw, hh = w / 2, h / 2
    r = min(r, hw, hh)
    pts = []
    for ox, oy, a0 in [(hw - r, hh - r, 0), (-hw + r, hh - r, 90), (-hw + r, -hh + r, 180), (hw - r, -hh + r, 270)]:
        for k in range(n):
            a = math.radians(a0 + 90 * k / (n - 1))
            pts.append((cx + ox + r * math.cos(a), cy + oy + r * math.sin(a)))
    return pts


def capsule(p0, p1, w, n=9):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    ang = math.atan2(dy, dx) if (dx or dy) else 0.0
    r = w / 2
    pts = []
    for k in range(n):
        a = ang - math.pi / 2 + math.pi * k / (n - 1)
        pts.append((p1[0] + r * math.cos(a), p1[1] + r * math.sin(a)))
    for k in range(n):
        a = ang + math.pi / 2 + math.pi * k / (n - 1)
        pts.append((p0[0] + r * math.cos(a), p0[1] + r * math.sin(a)))
    return pts


def xf(pts, tx, ty, s=1.0, rot=0.0, sx=1.0, sy=1.0):
    a = math.radians(rot)
    ca, sa = math.cos(a), math.sin(a)
    return [(tx + (x * ca - y * sa) * sx * s, ty + (x * sa + y * ca) * sy * s) for x, y in pts]


def offset(pts, dx, dy):
    return [(x + dx, y + dy) for x, y in pts]


def clip_half(pts, y0):
    """y >= y0 부분만 남김 (Sutherland-Hodgman, 반평면)"""
    out = []
    n = len(pts)
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        pin, qin = p[1] >= y0, q[1] >= y0
        if pin:
            out.append(p)
        if pin != qin:
            u = (y0 - p[1]) / (q[1] - p[1])
            out.append((p[0] + (q[0] - p[0]) * u, y0))
    return out


def clip_convex(subject, clip):
    def area(poly):
        return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))
    sign = 1 if area(clip) > 0 else -1
    out = subject
    for i in range(len(clip)):
        a, b = clip[i], clip[(i + 1) % len(clip)]
        inp, out = out, []
        if not inp:
            break

        def inside(p):
            return sign * ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) >= 0

        for j in range(len(inp)):
            p, q = inp[j], inp[(j + 1) % len(inp)]
            pi, qi = inside(p), inside(q)
            if pi:
                out.append(p)
            if pi != qi:
                dx, dy = q[0] - p[0], q[1] - p[1]
                ex, ey = b[0] - a[0], b[1] - a[1]
                den = ex * dy - ey * dx
                if den:
                    u = (ey * (p[0] - a[0]) - ex * (p[1] - a[1])) / den
                    out.append((p[0] + dx * u, p[1] + dy * u))
    return out


def bite_poly(pts, circ):
    if not circ:
        return pts
    bx, by, br = circ
    out = []
    for x, y in pts:
        dx, dy = x - bx, y - by
        d = math.hypot(dx, dy)
        if d < br:
            if d < 1e-6:
                dx, dy, d = 0, 1, 1
            out.append((bx + dx / d * br, by + dy / d * br))
        else:
            out.append((x, y))
    return out


def clip_seg(x0, y0, x1, y1, rect):
    """Liang-Barsky 선분 자르기"""
    l, t, r, b = rect
    dx, dy = x1 - x0, y1 - y0
    u0, u1 = 0.0, 1.0
    for p, q in ((-dx, x0 - l), (dx, r - x0), (-dy, y0 - t), (dy, b - y0)):
        if p == 0:
            if q < 0:
                return None
        else:
            u = q / p
            if p < 0:
                u0 = max(u0, u)
            else:
                u1 = min(u1, u)
    if u0 > u1:
        return None
    return (x0 + dx * u0, y0 + dy * u0, x0 + dx * u1, y0 + dy * u1)


def P(pts):
    return [(x * S, y * S) for x, y in pts]


def stroke(d, pts, col, w, closed=False):
    if closed:
        pts = list(pts) + list(pts[:2])
    if len(pts) < 2:
        return
    d.line(P(pts), fill=col, width=max(1, int(round(w * S))), joint="curve")


def shape(d, pts, fill, shade=True, line=True, shadow=False, lw=LW, a=255, shade_k=0.15, frac=0.35,
          shade_col=None):
    if len(pts) < 3:
        return
    if shadow:
        d.polygon(P(offset(pts, 8, 8)), fill=(0, 0, 0, 46))
    d.polygon(P(pts), fill=tuple(fill) + (a,))
    if shade:
        ys = [p[1] for p in pts]
        y0 = min(ys) + (1 - frac) * (max(ys) - min(ys))
        sp = clip_half(pts, y0)
        if len(sp) >= 3:
            d.polygon(P(sp), fill=tuple(shade_col or dark(fill, shade_k)) + (a,))
    if line and lw > 0:
        stroke(d, pts, OUTLINE + (a,) if a < 255 else OUTLINE, lw, closed=True)


def circle(d, x, y, r, fill, **kw):
    shape(d, ell(x, y, r, r, n=max(16, min(48, int(r)))), fill, **kw)


def heart_pts(cx, cy, size, n=40):
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        x = 16 * math.sin(a) ** 3
        y = -(13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a))
        pts.append((cx + x * size / 34, cy + y * size / 34))
    return pts


def sparkle_pts(cx, cy, r):
    pts = []
    for k in range(8):
        rr = r if k % 2 == 0 else r * 0.28
        a = math.pi / 4 * k - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


# ───────────────────────── 캐릭터 (토리 / 미미) ─────────────────────────

def spiky_poly(fluff=1.0, turn=0.0):
    cx, cy = -turn * 8, -128
    pts = []
    n = 11
    rx, ry = 134, 116
    for k in range(n):
        a0 = math.radians(180 + 180 * k / n)
        am = math.radians(180 + 180 * (k + 0.5) / n)
        pts.append((cx + rx * math.cos(a0), cy + ry * math.sin(a0)))
        L = (66 + (6 if k % 2 else -4)) * fluff
        pts.append((cx + (rx + L) * math.cos(am), cy + (ry + L) * math.sin(am)))
    for k in range(13):
        a = math.radians(0 + 180 * k / 12)
        pts.append((cx + (rx + 4) * math.cos(a), cy + 4 + (ry + 6) * math.sin(a)))
    return pts


def hog(d, kind, x, gy, sc=1.0, rot=0.0, sx=1.0, sy=1.0, turn=0.0, eyes="open", blink=1.0, mouth="smile",
        blush=0.6, legs=(0.0, 0.0), hands=(None, None), sit=False, held=None, fluff=1.0, draw_body=True,
        draw_arms=True, look=(0.0, 0.0), shadow=True):
    mimi = kind == "mimi"
    spine = SPINE_M if mimi else SPINE_T

    def T(pts):
        return xf(pts, x, gy, sc, rot, sx, sy)

    k = sc * (sx + sy) / 2
    tx = turn * 26
    if draw_body:
        if shadow:
            d.polygon(P(ell(x + 6, gy + 4, 120 * sc, 18 * sc)), fill=(0, 0, 0, 55))
        # 다리
        if sit:
            for side in (-1, 1):
                shape(d, T(ell(side * 62 + tx * 0.3, -10, 30, 20, n=24)), BODY, lw=LW)
                stroke(d, T([(side * 62 + tx * 0.3 - 8, -18), (side * 62 + tx * 0.3 - 8, -8)]), OUTLINE, 3 * k)
                stroke(d, T([(side * 62 + tx * 0.3 + 8, -18), (side * 62 + tx * 0.3 + 8, -8)]), OUTLINE, 3 * k)
        else:
            for side, lift in ((-1, legs[0]), (1, legs[1])):
                lx = side * 52 + tx * 0.2
                shape(d, T(capsule((lx, -52 - lift), (lx, -17 - lift), 36)), BODY, lw=LW)
        # 가시 (몸통 뒤 하나의 뾰족한 실루엣)
        sp = T(spiky_poly(fluff, turn))
        shape(d, sp, spine, shadow=shadow, lw=LW, frac=0.3)
        for j in range(5):                                   # 가시 결 (밝은 짧은 선)
            a = math.radians(205 + 32 * j)
            p0 = (-turn * 8 + 138 * math.cos(a), -128 + 120 * math.sin(a))
            p1 = (-turn * 8 + 168 * math.cos(a), -128 + 150 * math.sin(a))
            stroke(d, T([p0, p1]), light(spine, 0.18), 4 * k)
        # 귀
        for side in (-1, 1):
            ex = side * 74 + tx * 0.4
            shape(d, T(ell(ex, -222, 24, 22, n=24)), BODY, shade=False, lw=LW)
            shape(d, T(ell(ex, -220, 12, 11, n=16)), BLUSH, shade=False, line=False)
        # 몸통
        body = T(ell(0, -125, 130, 115, n=56))
        shape(d, body, BODY, lw=LW)
        # 앞치마 (토리) / 목도리 (미미)
        if not mimi:
            ap = [(-58 + tx * 0.5, -84), (58 + tx * 0.5, -84), (84 + tx * 0.5, -6), (-84 + tx * 0.5, -6)]
            ap = clip_convex(T(ap), T(ell(0, -125, 128, 113, n=40)))
            shape(d, ap, APRON, lw=LW - 1)
            pk = T(rrect(tx * 0.5, -40, 50, 35, 6))
            shape(d, pk, POCKET, shade=False, lw=4)
            stroke(d, T([(-58 + tx * 0.5, -84), (-96, -128)]), APRON, 7 * k)
            stroke(d, T([(58 + tx * 0.5, -84), (96, -128)]), APRON, 7 * k)
        # 얼굴
        shape(d, T(ell(tx, -122, 86, 76, n=48)), FACE, lw=LW - 1, frac=0.25, shade_k=0.08)
        if mimi:
            band_top = [(xx, -64 + 0.0016 * xx * xx) for xx in range(-126, 127, 12)]
            band = band_top + [(xx, y + 34) for xx, y in reversed(band_top)]
            band = clip_convex(T(band), T(ell(0, -125, 134, 119, n=40)))
            shape(d, band, SCARF, lw=LW - 1)
            shape(d, T(rrect(52 + tx * 0.3, -18, 30, 52, 10)), SCARF, lw=LW - 1)
        # 볼
        bl = int(255 * clamp01(blush))
        for side in (-1, 1):
            d.polygon(P(T(ell(side * 60 + tx, -100, 19, 15, n=24))), fill=BLUSH + (bl,))
        # 눈
        er = 16 if mimi else 14
        lx, ly = look
        for side in (-1, 1):
            ex, ey = side * 36 + tx * 1.15 + lx * 5, -132 + ly * 4
            if eyes == "happy":
                stroke(d, T(ell(ex, ey + 5, er * 1.05, er * 0.85, n=12, a0=200, a1=340, closed=False)), EYE, 5.5 * k)
            elif eyes == "squeeze":
                pts = [(ex - side * 11, ey - 10), (ex + side * 9, ey), (ex - side * 11, ey + 10)]
                stroke(d, T(pts), EYE, 5 * k)
            elif blink < 0.2:
                stroke(d, T(ell(ex, ey - 2, er, er * 0.5, n=10, a0=20, a1=160, closed=False)), EYE, 5 * k)
            else:
                big = 1.22 if eyes == "sparkle" else 1.0
                r = er * big
                d.polygon(P(T(ell(ex, ey, r, r * blink, n=28))), fill=EYE)
                d.polygon(P(T(ell(ex - 4 * big, ey - 4 * big * blink, 5 * big, 5 * big * blink, n=16))),
                          fill=(255, 255, 255))
                d.polygon(P(T(ell(ex + 4.5 * big, ey + 4.5 * big * blink, 2.4 * big, 2.4 * big * blink, n=10))),
                          fill=(255, 255, 255))
                if eyes == "sparkle":
                    d.polygon(P(T(sparkle_pts(ex + 6, ey - 7, 7))), fill=(255, 255, 255))
        # 코
        nx = tx * 1.4
        shape(d, T(ell(nx, -107, 11, 9.5, n=20)), NOSE, shade=False, lw=3)
        d.polygon(P(T(ell(nx - 3, -110, 3.5, 2.5, n=10))), fill=(255, 255, 255, 200))
        # 입
        mx, my = tx * 1.3, -90
        if mouth == "smile":
            stroke(d, T(ell(mx - 7, my, 7, 6, n=8, a0=10, a1=170, closed=False)), EYE, 3.6 * k)
            stroke(d, T(ell(mx + 7, my, 7, 6, n=8, a0=10, a1=170, closed=False)), EYE, 3.6 * k)
        elif mouth == "o":
            shape(d, T(ell(mx, my + 4, 7, 8.5, n=16)), (0x7A, 0x2E, 0x2A), shade=False, lw=3)
        elif mouth == "open":
            pts = T(ell(mx, my - 2, 15, 15, n=16, a0=0, a1=180, closed=False))
            shape(d, pts, (0x7A, 0x2E, 0x2A), shade=False, lw=3)
            d.polygon(P(T(ell(mx, my + 8, 8, 4.5, n=12))), fill=(0xF2, 0x84, 0x8C))
        elif mouth == "chew":
            pts = [(mx - 11, my + 2), (mx - 5, my - 2), (mx, my + 2), (mx + 5, my - 2), (mx + 11, my + 2)]
            stroke(d, T(pts), EYE, 3.6 * k)
        elif mouth == "wavy":
            pts = [(mx - 10, my + 1), (mx - 4, my - 3), (mx + 3, my + 3), (mx + 10, my - 1)]
            stroke(d, T(pts), EYE, 3.6 * k)
    if held:
        held(d)
    if draw_arms:
        for side, hand in ((-1, hands[0]), (1, hands[1])):
            sh = T([(side * 104 + tx * 0.2, -108)])[0]
            if hand is None:
                hand = T([(side * 134, -58)])[0]
            shape(d, capsule(sh, hand, 34 * sc), BODY, lw=LW, frac=0.3)


def blink_amt(t, phase=0.0, period=3.0):
    u = (t + phase) % period
    if u < 0.12:
        return 1 - math.sin(math.pi * u / 0.12)
    return 1.0


# ───────────────────────── 소품 ─────────────────────────

def potato_local(L, Wd, n=56):
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        c = math.cos(a)
        pts.append((L / 2 * c, Wd / 2 * math.sin(a) * (1 - 0.3 * c * c) * (1 + 0.1 * c)))
    return pts


def potato(d, cx, cy, L, Wd, rot=0.0, fy=1.0, chars=0.0, wet=False, lw=LW, glow=0.0):
    back = fy < 0
    f = max(abs(fy), 0.06)
    pts = xf(potato_local(L, Wd), cx, cy, 1, rot, 1, f)
    col = mixc(SKIN, (0xA8, 0x40, 0x48), glow * 0.5)
    shape(d, pts, col, lw=lw, shadow=False)
    hl = xf(ell(-L * 0.08, -Wd * 0.2, L * 0.28, Wd * 0.07, n=20), cx, cy, 1, rot, 1, f if not back else -f)
    d.polygon(P(hl), fill=light(col, 0.35) + (150,))
    for oy in (-0.06, 0.16):
        g = xf(ell(0, Wd * oy, L * 0.3, Wd * 0.06, n=12, a0=200, a1=340, closed=False), cx, cy, 1, rot, 1, f)
        stroke(d, g, dark(col, 0.3) + (170,), 2.5)
    if wet:
        for ox, oy in ((-0.25, -0.12), (0.18, -0.16), (0.05, 0.05)):
            p = xf([(L * ox, Wd * oy)], cx, cy, 1, rot, 1, f)[0]
            d.polygon(P(ell(p[0], p[1], 5, 5, n=10)), fill=(255, 255, 255, 210))
    c_amt = 1.0 if back else chars
    if c_amt > 0:
        for ox, oy, r in ((-0.22, 0.08, 0.09), (0.12, -0.12, 0.07), (0.3, 0.14, 0.06), (-0.02, 0.2, 0.05)):
            sp = xf(ell(L * ox, Wd * oy, L * r, Wd * r * 1.3, n=16), cx, cy, 1, rot, 1, f)
            d.polygon(P(sp), fill=BURN + (int(230 * c_amt),))
    for side in (-1, 1):
        e = xf([(side * L * 0.5, 0), (side * (L * 0.5 + 12), 3)], cx, cy, 1, rot, 1, f)
        stroke(d, e, OUTLINE, 4)


def broken_half(d, fx, fy, L, Wd, rot=0.0, side=-1, open_=0.75, ripe=0.0, bite=None, lw=LW):
    """갈라진 고구마 반쪽: 단면(fx, fy)이 화면을 향하고 껍질은 side 방향으로 뻗는다"""
    def T(pts):
        return xf(pts, fx, fy, 1, rot)
    bc = None
    if bite:
        bc = T([(bite[0], bite[1])])[0] + (bite[2],)
    half = []
    for k in range(37):
        th = math.radians((-90 if side > 0 else 90) + 180 * k / 36)
        c = math.cos(th)
        half.append((L / 2 * c, Wd / 2 * math.sin(th) * (1 - 0.3 * c * c) * (1 + 0.1 * c)))
    skin = T(half)
    shape(d, bite_poly(skin, bc), SKIN, lw=lw)
    hl = T(ell(side * L * 0.2, -Wd * 0.2, L * 0.14, Wd * 0.06, n=16))
    d.polygon(P(hl), fill=light(SKIN, 0.35) + (150,))
    for j, oy in enumerate((-0.05, 0.16)):
        g = T(ell(side * L * 0.22, Wd * oy, L * 0.16, Wd * 0.05, n=10, a0=200, a1=340, closed=False))
        stroke(d, g, dark(SKIN, 0.3) + (180,), 2.5)
    e = T([(side * L * 0.5, 0), (side * (L * 0.5 + 12), 3)])
    stroke(d, e, OUTLINE, 4)
    # 단면 (조금 울퉁불퉁)
    rx, ry = Wd / 2 * open_, Wd / 2 * 0.93
    face = []
    for k in range(64):
        a = 2 * math.pi * k / 64
        jag = 1 + 0.035 * math.sin(a * 9 + 1.3) + 0.02 * math.sin(a * 17)
        face.append((rx * math.cos(a) * jag - side * rx * 0.15, ry * math.sin(a) * jag))
    fl = mixc(FLESH, FLESH_C, ripe)
    rim = T([(x * 1.08, y * 1.04) for x, y in face])
    shape(d, bite_poly(rim, bc), dark(SKIN, 0.05), shade=False, lw=max(2, lw - 2))
    shape(d, bite_poly(T(face), bc), fl, shade=False, lw=max(2, lw - 2))
    core = T(ell(-side * rx * 0.12, ry * 0.05, rx * 0.55, ry * 0.5, n=40))
    d.polygon(P(bite_poly(core, bc)), fill=mixc(FLESH_C, (0xFF, 0x9A, 0x1F), ripe * 0.6) + (190,))
    for k in range(7):                                   # 섬유결
        a = 2 * math.pi * (k + 0.3) / 7
        p0 = (-side * rx * 0.12 + rx * 0.2 * math.cos(a), ry * 0.2 * math.sin(a))
        p1 = (-side * rx * 0.12 + rx * 0.62 * math.cos(a), ry * 0.62 * math.sin(a))
        stroke(d, bite_poly(T([p0, p1]), bc), light(fl, 0.45) + (150,), 2.5)
    gl = T(ell(-side * rx * 0.1 - rx * 0.25, -ry * 0.42, rx * 0.28, ry * 0.12, n=20))
    d.polygon(P(bite_poly(gl, bc)), fill=(255, 255, 255, 160))


def leaf(d, sx_, sy_, rot, length=340, width=140):
    """줄기 끝(sx_, sy_)에서 rot 방향으로 뻗은 잎 우산 (rot: 잎의 장축 각도, -90이면 위쪽)"""
    a = math.radians(rot)
    ux, uy = math.cos(a), math.sin(a)
    cx, cy = sx_ + ux * (length / 2 + 40), sy_ + uy * (length / 2 + 40)
    pts = []
    n = 48
    for k in range(n):
        t = 2 * math.pi * k / n
        lx = length / 2 * math.cos(t)
        ly = width / 2 * math.sin(t) * (1 - 0.35 * math.cos(t)) * (1 + 0.05 * math.sin(3 * t))
        pts.append((lx, ly))
    pts = xf(pts, cx, cy, 1, rot)
    stroke(d, [(sx_, sy_), (cx - ux * length / 2, cy - uy * length / 2)], LEAF_V, 9)
    shape(d, pts, LEAF, shadow=True, frac=0.3)
    stroke(d, xf([(-length / 2, 0), (length / 2 - 10, 0)], cx, cy, 1, rot), LEAF_V, 5)
    for j in range(-3, 4):
        if j == 0:
            continue
        x0 = j * length / 9
        for side in (-1, 1):
            stroke(d, xf([(x0, 0), (x0 + length / 14, side * width * 0.32)], cx, cy, 1, rot), LEAF_V, 3.5)
    return (cx, cy)


def leaf_umbrella(d, hand, top, rot=0.0, length=340, width=140):
    """손(hand)에서 줄기를 올려 머리 위(top)에 펼친 잎 우산"""
    stroke(d, [hand, top], OUTLINE, 13)
    stroke(d, [hand, top], LEAF_V, 7)
    pts = []
    n = 48
    for k in range(n):
        th = 2 * math.pi * k / n
        lx = length / 2 * math.cos(th)
        ly = width / 2 * math.sin(th) * (1 - 0.3 * math.cos(th)) * 0.9 + 0.0016 * lx * lx - 30
        pts.append((lx, ly))
    poly = xf(pts, top[0], top[1], 1, rot)
    shape(d, poly, LEAF, shadow=True, frac=0.3)
    mid = [(x, 0.0016 * x * x - 30) for x in range(-int(length / 2) + 10, int(length / 2) - 10, 20)]
    stroke(d, xf(mid, top[0], top[1], 1, rot), LEAF_V, 5)
    for j in range(-3, 4):
        if j == 0:
            continue
        x0 = j * length / 8
        y0 = 0.0016 * x0 * x0 - 30
        for sd in (-1, 1):
            x1 = x0 + length / 14 * (1 if j > 0 else -1)
            stroke(d, xf([(x0, y0), (x1, y0 + sd * width * 0.3 + 0.0016 * (x1 * x1 - x0 * x0))],
                         top[0], top[1], 1, rot), LEAF_V, 3.5)
    tips = xf([(-length / 2 + 6, 0.0016 * (length / 2) ** 2 - 30), (length / 2 - 6, 0.0016 * (length / 2) ** 2 - 30)],
              top[0], top[1], 1, rot)
    return tips


def basket(d, cx, top, w=140, h=80, rot=0.0, n_pot=3, handle=True):
    def T(pts):
        return xf(pts, cx, top, 1, rot)
    if handle:
        stroke(d, T(ell(0, 0, w * 0.42, h * 0.95, n=16, a0=180, a1=360, closed=False)), OUTLINE, 11)
        stroke(d, T(ell(0, 0, w * 0.42, h * 0.95, n=16, a0=180, a1=360, closed=False)), BASKET, 6)
    for j in range(n_pot):
        px = (j - (n_pot - 1) / 2) * w * 0.28
        potato(d, *T([(px, -8 - (j % 2) * 6)])[0], w * 0.42, w * 0.22, rot + (j - 1) * 25, lw=4)
    bowl = T(ell(0, 0, w / 2, h, n=32, a0=0, a1=180, closed=False))
    shape(d, bowl, BASKET, lw=LW)
    for j in range(1, 3):
        stroke(d, T(ell(0, 0, w / 2 * (1 - j * 0.04), h * j / 3, n=16, a0=10, a1=170, closed=False)),
               dark(BASKET, 0.25), 3)
    for j in range(-2, 3):
        stroke(d, T([(j * w * 0.14, 2), (j * w * 0.11, h * 0.9)]), dark(BASKET, 0.25), 3)
    stroke(d, T([(-w / 2, 0), (w / 2, 0)]), OUTLINE, LW)


def fan(d, px, py, ang, r=160):
    a0, a1 = ang - 40, ang + 40
    pts = [(px, py)] + ell(px, py, r, r, n=20, a0=a0, a1=a1, closed=False)
    shape(d, pts, FAN_C, frac=0.3, lw=5)
    for j in range(7):
        a = math.radians(a0 + (a1 - a0) * j / 6)
        stroke(d, [(px, py), (px + r * 0.95 * math.cos(a), py + r * 0.95 * math.sin(a))], dark(FAN_C, 0.2), 3)
    stroke(d, [(px, py), (px - 70 * math.cos(math.radians(ang)), py - 70 * math.sin(math.radians(ang)))], OUTLINE, 12)
    stroke(d, [(px, py), (px - 68 * math.cos(math.radians(ang)), py - 68 * math.sin(math.radians(ang)))],
           hexc("#A0703E"), 7)


def tongs(d, hand, tip, open_=0.25, wdt=12):
    dx, dy = tip[0] - hand[0], tip[1] - hand[1]
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    for side in (-1, 1):
        spread = side * (6 + 26 * open_)
        a = (hand[0] + nx * side * 5, hand[1] + ny * side * 5)
        b = (tip[0] + nx * spread, tip[1] + ny * spread)
        shape(d, capsule(a, b, wdt), TONGS, shade=False, lw=4)
        d.line(P([lerp_pt(a, b, 0.1), lerp_pt(a, b, 0.85)]), fill=(255, 255, 255, 110), width=3 * S)


def heart(d, x, y, size, a=255):
    if size < 2:
        return
    shape(d, heart_pts(x, y, size), HEART, lw=max(3, LW * size / 60), a=a, frac=0.3)
    d.polygon(P(ell(x - size * 0.22, y - size * 0.28, size * 0.1, size * 0.07, n=10)), fill=(255, 255, 255, int(200 * a / 255)))


def coal_pile(d, coals, level, t, scale=1.0, bed=None):
    """bed: (cx, cy, rx, ry) 숯 사이로 비치는 불빛 바닥"""
    b0 = clamp01(level * (0.8 + 0.2 * math.sin(2 * math.pi * 2 * t)))
    if bed:
        d.polygon(P(ell(*bed, n=40)), fill=mixc((0xC0, 0x40, 0x10), mixc(GLOW1, GLOW2, b0 * 0.7), b0))
    for i, (x, y, r, ph, jit) in enumerate(coals):
        b = clamp01(level * (0.78 + 0.22 * math.sin(2 * math.pi * 2 * t + ph)))
        poly = [(x + r * jit[k] * math.cos(2 * math.pi * k / len(jit) + ph),
                 y + r * 0.82 * jit[k] * math.sin(2 * math.pi * k / len(jit) + ph)) for k in range(len(jit))]
        base = mixc(COAL, (0x6A, 0x22, 0x10), 0.5 * b)
        shape(d, poly, base, lw=max(3, LW * min(1.0, scale)), frac=0.4,
              shade_col=mixc((0x5A, 0x1C, 0x0E), GLOW1, 0.55 * b))
        ys = [p[1] for p in poly]
        top = [p for p in poly]
        ash = clip_half([(px, -py) for px, py in top], -(min(ys) + (max(ys) - min(ys)) * 0.3))
        if len(ash) >= 3:
            d.polygon(P([(px, -py) for px, py in ash]), fill=(0x9A, 0x8C, 0x84, 70))
        hot = mixc(GLOW1, GLOW2, b)
        for j in range(2):
            a = ph * 2.3 + j * 2.6
            p0 = (x + r * 0.05 * math.cos(a), y + r * 0.05 * math.sin(a))
            pm = (x + r * 0.35 * math.cos(a + 0.35), y + r * 0.3 * math.sin(a + 0.35))
            p1 = (x + r * 0.62 * math.cos(a - 0.1), y + r * 0.5 * math.sin(a - 0.1))
            stroke(d, [p0, pm, p1], hot + (int(150 + 100 * b),), (3.5 + 2 * b) * scale)
            stroke(d, [p0, pm], (0xFF, 0xF1, 0xB0, int(80 + 150 * b)), 1.6 * scale)


def make_coals(cx, base_y, width, n, rmin, rmax, seed, mound=60):
    rng = np.random.default_rng(seed)
    coals = []
    for i in range(n):
        u = (i + 0.5) / n
        x = cx + (u - 0.5) * width + rng.uniform(-12, 12)
        y = base_y - mound * math.sin(math.pi * u) + rng.uniform(-10, 10) - (i % 2) * rmin * 0.6
        jit = list(rng.uniform(0.82, 1.08, 9))
        coals.append((x, y, rng.uniform(rmin, rmax), rng.uniform(0, 6.28), jit))
    coals.sort(key=lambda c: c[1])
    return coals


def brazier(d, cx, rim, rx, depth, legs=True):
    if legs:
        for side in (-0.6, 0, 0.6):
            shape(d, rrect(cx + side * rx, rim + depth - 8, 46, 60, 12), dark(CLAY, 0.2), shade=False)
    bowl = ell(cx, rim, rx, depth, n=48, a0=0, a1=180, closed=False)
    shape(d, bowl, CLAY, shadow=True, frac=0.4)
    stroke(d, ell(cx, rim + depth * 0.45, rx * 0.88, depth * 0.18, n=24, a0=20, a1=160, closed=False),
           dark(CLAY, 0.3), 4)
    shape(d, ell(cx, rim, rx * 1.03, 30, n=48), light(CLAY, 0.15), shade=False)


def window(d, rect, t, rain_n=150, moon_a=0.0, sky_k=0.0, drops=True, pane_cross=True):
    l, tp, w, h = rect
    r, b = l + w, tp + h
    gl = (l + 18, tp + 18, r - 18, b - 18)
    top_c = mixc(NIGHT, (0x2C, 0x3E, 0x66), sky_k)
    bot_c = mixc((0x2A, 0x3A, 0x5A), (0x3A, 0x52, 0x7E), sky_k)
    steps = 12
    for i in range(steps):
        y0 = gl[1] + (gl[3] - gl[1]) * i / steps
        y1 = gl[1] + (gl[3] - gl[1]) * (i + 1) / steps
        d.rectangle(P([(gl[0], y0), (gl[2], y1 + 1)]), fill=mixc(top_c, bot_c, i / (steps - 1)))
    # 바깥 숲 실루엣
    for k in range(5):
        tx_ = gl[0] + (gl[2] - gl[0]) * (k + 0.3) / 5
        pts = [(tx_ - 45, gl[3]), (tx_, gl[3] - 150 - 30 * (k % 2)), (tx_ + 45, gl[3])]
        pts = [(min(max(x, gl[0]), gl[2]), y) for x, y in pts]
        d.polygon(P(pts), fill=(0x1A, 0x2E, 0x2A))
    if moon_a > 0:
        mx, my = gl[2] - 85, gl[1] + 95
        d.polygon(P(ell(mx, my, 70, 70, n=40)), fill=MOON + (int(60 * moon_a),))
        d.polygon(P(ell(mx, my, 44, 44, n=40)), fill=MOON + (int(255 * moon_a),))
        d.polygon(P(ell(mx + 12, my - 8, 9, 8, n=14)), fill=(0xF2, 0xE2, 0xA8, int(255 * moon_a)))
    if rain_n > 0:
        rain_lines(d, t, rain_n, clip=gl, alpha=0.6)
    if drops:                                         # 유리에 맺혀 흘러내리는 물방울
        rng = np.random.default_rng(int(l * 7 + tp))
        for k in range(9):
            x = rng.uniform(gl[0] + 15, gl[2] - 15)
            speed = rng.uniform(20, 60)
            y0 = rng.uniform(gl[1], gl[3])
            y = gl[1] + (y0 - gl[1] + speed * t) % (gl[3] - gl[1])
            rr = rng.uniform(5, 9)
            d.line(P([(x, max(gl[1], y - 50)), (x, y)]), fill=(0xC8, 0xD8, 0xF0, 60), width=int(rr * 0.8 * S))
            d.polygon(P(ell(x, y, rr, rr * 1.15, n=14)), fill=(0xC8, 0xD8, 0xF0, 120))
            d.polygon(P(ell(x - rr * 0.3, y - rr * 0.4, rr * 0.3, rr * 0.3, n=8)), fill=(255, 255, 255, 190))
    # 창틀
    frame_c = PLANK
    for rr in ([(l, tp), (r, tp + 20)], [(l, b - 20), (r, b)], [(l, tp), (l + 20, b)], [(r - 20, tp), (r, b)]):
        d.rectangle(P(rr), fill=frame_c)
    if pane_cross:
        d.rectangle(P([((l + r) / 2 - 9, tp), ((l + r) / 2 + 9, b)]), fill=frame_c)
        d.rectangle(P([(l, (tp + b) / 2 - 9), (r, (tp + b) / 2 + 9)]), fill=frame_c)
        stroke(d, [((l + r) / 2 - 9, tp + 20), ((l + r) / 2 - 9, b - 20)], OUTLINE, 3)
        stroke(d, [((l + r) / 2 + 9, tp + 20), ((l + r) / 2 + 9, b - 20)], OUTLINE, 3)
    stroke(d, [(l, tp), (r, tp), (r, b), (l, b)], OUTLINE, LW, closed=True)
    stroke(d, [gl[:2], (gl[2], gl[1]), gl[2:], (gl[0], gl[3])], OUTLINE, 4, closed=True)
    shape(d, rrect((l + r) / 2, b + 14, w + 50, 26, 8), light(PLANK, 0.1), shade=False)


def lantern(d, x, y, t):
    stroke(d, [(x, y - 120), (x, y - 62)], OUTLINE, 4)
    sway = 2 * math.sin(t * 1.3)
    pts = xf(rrect(0, 0, 76, 104, 30), x, y, 1, sway)
    shape(d, pts, hexc("#F6C77A"), frac=0.3, lw=5)
    d.polygon(P(xf(ell(0, 4, 24, 34, n=20), x, y, 1, sway)), fill=(0xFF, 0xF0, 0xC0, 230))
    for yy in (-34, 0, 34):
        stroke(d, xf([(-34, yy), (34, yy)], x, y, 1, sway), dark(hexc("#F6C77A"), 0.3), 3)
    shape(d, xf(rrect(0, -58, 50, 16, 5), x, y, 1, sway), PLANK, shade=False, lw=4)
    shape(d, xf(rrect(0, 58, 50, 16, 5), x, y, 1, sway), PLANK, shade=False, lw=4)


# ───────────────────────── 비 ─────────────────────────

_rr = np.random.default_rng(11)
N_RAIN = 150
RAIN_X0 = _rr.uniform(0, W + 300, N_RAIN)
RAIN_Y0 = _rr.uniform(0, H + 200, N_RAIN)
RAIN_V = _rr.uniform(0.85, 1.15, N_RAIN)
RAIN_TH = _rr.choice([2.0, 3.0, 3.0, 3.5], N_RAIN)
TAN15 = math.tan(math.radians(15))


def rain_lines(d, t, n, clip=None, alpha=0.6, color=RAIN_C):
    sx_, sy_ = 40 * math.sin(math.radians(15)), 40 * math.cos(math.radians(15))
    for i in range(int(n)):
        y = (RAIN_Y0[i] + 1400 * RAIN_V[i] * t) % (H + 200) - 100
        x = (RAIN_X0[i] + y * TAN15) % (W + 300) - 150
        seg_ = (x, y, x - sx_, y - sy_)
        if clip:
            # 창문처럼 작은 영역에서는 빗줄기를 영역 크기에 맞게 반복시킨다
            cw, ch = clip[2] - clip[0], clip[3] - clip[1]
            yy = clip[1] + (RAIN_Y0[i] + 1400 * RAIN_V[i] * t) % (ch + 60) - 30
            xx = clip[0] + (RAIN_X0[i] + yy * TAN15) % (cw + 40) - 20
            seg_ = clip_seg(xx, yy, xx - sx_ * 0.8, yy - sy_ * 0.8, clip)
            if seg_ is None:
                continue
        d.line(P([seg_[:2], seg_[2:]]), fill=color + (int(255 * alpha),), width=int(RAIN_TH[i] * S))


# ───────────────────────── 입자 (결정적) ─────────────────────────

def steam_burst(t, t0, cx, cy, spread, seed, n_burst=30, trickle=10.0, until=None, life=1.2, rmin=20, rmax=45,
                amax=0.35, speed=120):
    out = []
    if t < t0 - 0.05:
        return out
    rng = np.random.default_rng(seed)
    births = list(t0 + rng.uniform(0, 0.25, n_burst))
    kinds = [1] * n_burst
    if until:
        k = 0
        while t0 + 0.25 + k / trickle < until:
            births.append(t0 + 0.25 + k / trickle)
            kinds.append(0)
            k += 1
    xs = rng.uniform(-spread, spread, len(births))
    rs = rng.uniform(rmin, rmax, len(births))
    ph = rng.uniform(0, 6.28, len(births))
    for b, kd, x0, r0, p in zip(births, kinds, xs, rs, ph):
        age = t - b
        if not 0 <= age < life:
            continue
        y = cy + (p - 3.14) * 8 - speed * age - (90 * (1 - math.exp(-age * 4)) if kd else 0)
        x = cx + x0 * (1 - 0.35 * min(age, 1.0)) + 15 * math.sin(2 * math.pi * 1.5 * age + p)
        a = amax * (1 - age / life) * clamp01(age / 0.08) * (1.0 if kd else 0.7)
        out.append((x, y, r0 * (1 + 0.9 * age), a))
    return out


def embers(t, t0, t1, rate, cx, cy, spread, seed, vmin=200, vmax=350, life=0.8):
    out = []
    rng = np.random.default_rng(seed)
    n = int((t1 - t0) * rate)
    if n <= 0:
        return out
    births = np.sort(rng.uniform(t0, t1, n))
    xs = rng.uniform(-spread, spread, n)
    vs = rng.uniform(vmin, vmax, n)
    rs = rng.uniform(4, 8, n)
    ph = rng.uniform(0, 6.28, n)
    for b, x0, v, r, p in zip(births, xs, vs, rs, ph):
        age = t - b
        if not 0 <= age < life:
            continue
        x = cx + x0 + 18 * math.sin(age * 6 + p)
        y = cy - v * age
        a = (1 - age / life) * clamp01(age / 0.05)
        out.append((x, y, r * (1 - 0.4 * age / life), a))
    return out


def draw_embers(d, pts, soft):
    for x, y, r, a in pts:
        d.polygon(P(ell(x, y, r, r, n=12)), fill=EMBER + (int(255 * a),))
        d.polygon(P(ell(x, y, r * 0.5, r * 0.5, n=8)), fill=(0xFF, 0xF4, 0xC8, int(255 * a)))
        soft["halos"].append((x, y, r * 5, GLOW1, 0.5 * a))


def droplets(t, t0, n, cx, cy, seed, speed=600, g=1800, life=0.6, cone=(200, 340), spread_r=0):
    out = []
    age = t - t0
    if not 0 <= age < life:
        return out
    rng = np.random.default_rng(seed)
    angs = rng.uniform(math.radians(cone[0]), math.radians(cone[1]), n)
    sp = rng.uniform(0.6, 1.0, n) * speed
    rs = rng.uniform(5, 10, n)
    for a, v, r in zip(angs, sp, rs):
        x = cx + math.cos(a) * (v * age + spread_r)
        y = cy + math.sin(a) * (v * age + spread_r) + 0.5 * g * age * age
        out.append((x, y, r, 1 - (age / life) ** 2))
    return out


def draw_drops(d, pts, color=(0xA8, 0xD8, 0xF5)):
    for x, y, r, a in pts:
        aa = int(255 * clamp01(a))
        d.polygon(P(ell(x, y, r, r * 1.15, n=14)), fill=color + (aa,))
        d.line(P(ell(x, y, r, r * 1.15, n=14) + [ell(x, y, r, r * 1.15, n=14)[0]]),
               fill=OUTLINE + (int(aa * 0.6),), width=2 * S)
        d.polygon(P(ell(x - r * 0.3, y - r * 0.35, r * 0.3, r * 0.3, n=8)), fill=(255, 255, 255, aa))


def new_soft(amb=(1, 1, 1), vig=0.4):
    return {"amb": amb, "vig": vig, "glows": [], "steam": [], "halos": []}


# ───────────────────────── 배경 (워커마다 한 번 만들어 둠) ─────────────────────────

def watercolor(img, strength=0.06, seed=0, scale=48):
    rng = np.random.default_rng(seed)
    w, h = img.size
    small = rng.normal(0, 1, (h // scale + 2, w // scale + 2)).astype(np.float32)
    n1 = np.asarray(Image.fromarray(small).resize((w, h), Image.BICUBIC))
    small2 = rng.normal(0, 1, (h // (scale // 4) + 2, w // (scale // 4) + 2)).astype(np.float32)
    n2 = np.asarray(Image.fromarray(small2).resize((w, h), Image.BICUBIC))
    m = 1 + strength * (0.7 * n1 + 0.3 * n2)
    arr = np.asarray(img).astype(np.float32) * m[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def grad_rect(d, box, c1, c2, steps=24):
    l, t_, r, b = box
    for i in range(steps):
        y0 = t_ + (b - t_) * i / steps
        y1 = t_ + (b - t_) * (i + 1) / steps
        d.rectangle(P([(l, y0), (r, y1 + 1)]), fill=mixc(c1, c2, i / (steps - 1)))


ROOM = {
    2: dict(floor=1250, plank=120, seam=135),
    3: dict(floor=960, plank=170, seam=200),
    4: dict(floor=1180, plank=130, seam=150),
    5: dict(floor=860, plank=200, seam=240),
    6: dict(floor=1235, plank=140, seam=160),
    7: dict(floor=1300, plank=120, seam=135),
}


def make_bg(ci):
    img = Image.new("RGB", (W * S, H * S), (0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    if ci == 0:
        grad_rect(d, (0, 0, W, 1180), hexc("#2A160E"), COAL)
        grad_rect(d, (0, 1180, W, H), hexc("#5A3E2A"), hexc("#3E2A1C"))
        stroke(d, [(0, 1180), (W, 1180)], OUTLINE, LW)
        for k in range(5):
            y = 1260 + k * 150
            stroke(d, [(0, y), (W, y + 10)], hexc("#33231A") + (120,), 4)
        return watercolor(img, 0.07, seed=1)
    if ci == 1:
        grad_rect(d, (0, 0, W, 1250), NIGHT, hexc("#34466A"))
        for k in range(14):                               # 수채화 구름 얼룩
            rng = np.random.default_rng(100 + k)
            x, y = rng.uniform(0, W), rng.uniform(80, 700)
            d.polygon(P(ell(x, y, rng.uniform(140, 300), rng.uniform(40, 80), n=24)), fill=(0x3A, 0x4A, 0x6E, 70))
        for layer, (col, base, hgt, cnt) in enumerate([((0x27, 0x3C, 0x4A), 1160, 300, 9),
                                                        ((0x22, 0x38, 0x3A), 1230, 240, 7)]):
            rng = np.random.default_rng(20 + layer)
            for k in range(cnt):
                x = (k + rng.uniform(-0.3, 0.3)) * W / (cnt - 1)
                hh = hgt * rng.uniform(0.7, 1.1)
                for tier in range(3):
                    yy = base - hh * tier / 3.2
                    wd = 120 - tier * 26
                    d.polygon(P([(x - wd, yy), (x, yy - hh * 0.5), (x + wd, yy)]), fill=col)
        grad_rect(d, (0, 1250, W, H), GROUND, hexc("#3A2E22"))
        d.polygon(P([(0, 1318), (W, 1300), (W, 1430), (0, 1445)]), fill=hexc("#5A4836"))
        stroke(d, [(0, 1250), (W, 1250)], OUTLINE + (160,), 4)
        return watercolor(img, 0.07, seed=2)
    cfg = ROOM[ci]
    fl = cfg["floor"]
    grad_rect(d, (0, 0, W, fl), dark(WALL, 0.08), WALL)
    k = 0
    x = 40
    while x < W:
        stroke(d, [(x, 0), (x, fl)], dark(WALL, 0.18) + (150,), 4)
        for j in range(3):
            yk = ((k * 37 + j * 211) % 700) + 120
            if yk < fl - 40:
                d.polygon(P(ell(x + cfg["seam"] * 0.5, yk, 8, 4, n=10)), fill=dark(WALL, 0.25) + (120,))
        x += cfg["seam"]
        k += 1
    d.rectangle(P([(0, fl - 26), (W, fl)]), fill=PLANK)
    stroke(d, [(0, fl - 26), (W, fl - 26)], OUTLINE, 4)
    grad_rect(d, (0, fl, W, H), FLOOR, dark(FLOOR, 0.12))
    stroke(d, [(0, fl), (W, fl)], OUTLINE, LW)
    y = fl + cfg["plank"]
    row = 0
    while y < H:
        stroke(d, [(0, y), (W, y)], PLANK, 4)
        for j in range(4):
            xx = ((row * 263 + j * 311) % W)
            stroke(d, [(xx, y - cfg["plank"]), (xx, y)], PLANK + (180,), 3)
        y += cfg["plank"]
        row += 1
    return watercolor(img, 0.06, seed=3 + ci)


def make_paper():
    rng = np.random.default_rng(99)
    small = rng.normal(0, 1, (H // 64 + 2, W // 64 + 2)).astype(np.float32)
    n1 = np.asarray(Image.fromarray(small).resize((W, H), Image.BICUBIC))
    fine = rng.normal(0, 1, (H // 3, W // 3)).astype(np.float32)
    n2 = np.asarray(Image.fromarray(fine).resize((W, H), Image.BILINEAR))
    return (1 + 0.025 * n1 + 0.012 * n2).astype(np.float32)[..., None]


_G = {}


def bg(ci):
    if ci not in _G:
        _G[ci] = make_bg(ci)
    return _G[ci]


# ───────────────────────── 컷별 장면 ─────────────────────────

def paw(d, x, y, rot, sc=1.0):
    pts = xf(ell(0, 0, 52 * sc, 62 * sc, n=32), x, y, 1, rot)
    shape(d, pts, BODY, frac=0.35)
    for j in (-1, 0, 1):
        stroke(d, xf([(j * 17 * sc, -58 * sc), (j * 15 * sc, -36 * sc)], x, y, 1, rot), OUTLINE, 4 * sc)
    d.polygon(P(xf(ell(-14 * sc, -24 * sc, 12 * sc, 8 * sc, n=12), x, y, 1, rot)), fill=light(BODY, 0.2) + (140,))


def split_halves(d, e, cx, cy, L, Wd, ripe, sep=40.0, paws=None, tilt=(14, 6), open_=(0.35, 0.42), lw=LW,
                 cloth=True):
    """두 반쪽을 V자로 벌린다. e: 0(붙어 있음)~1(벌어짐). paws: 발 크기(None이면 생략). 손 위치 목록을 돌려준다"""
    hands = []
    for side in (-1, 1):
        op = open_[0] + open_[1] * e
        rx = Wd / 2 * op
        fx = cx + side * (rx * 0.85 + 3 + sep * e)
        rot = side * (tilt[0] + tilt[1] * e)
        fy = cy - 8 * e
        end = xf([(side * L * 0.34, 4)], fx, fy, 1, rot)[0]
        if cloth:
            cl = xf(rrect(0, 0, L * 0.2, Wd * 0.95, Wd * 0.3), end[0], end[1], 1, rot + side * 8)
            shape(d, cl, CLOTH, frac=0.3, lw=lw)
        broken_half(d, fx, fy, L, Wd, rot=rot, side=side, open_=op, ripe=ripe, lw=lw)
        hands.append(end)
        if paws:
            arm = capsule((end[0] + side * 150 * paws, end[1] + 700 * paws), (end[0] + side * 10, end[1] + 30 * paws),
                          92 * paws)
            shape(d, arm, BODY, frac=0.35)
            paw(d, end[0] + side * 6, end[1] + 6, side * 18 + rot * 0.5, paws)
    return hands

def scene_hook(d, t, soft):
    rng = np.random.default_rng(5)
    for k in range(9):
        x = rng.uniform(80, 1000) + 14 * math.sin(t * 0.8 + k)
        y = rng.uniform(250, 760) - 10 * t
        soft["glows"].append((x, y, rng.uniform(50, 110), GLOW2 if k % 2 else GLOW1, 0.22))
    plate_c = hexc("#E8D9C4")
    shape(d, ell(540, 1135, 440, 120, n=64), dark(plate_c, 0.25), shadow=True, shade=False)
    shape(d, ell(540, 1122, 440, 116, n=64), plate_c, frac=0.3)
    stroke(d, ell(540, 1118, 350, 82, n=48), dark(plate_c, 0.12), 4, closed=True)
    stroke(d, ell(540, 1122, 420, 106, n=32, a0=200, a1=250, closed=False), (255, 255, 255, 160), 5)
    e = ease_out(seg(t, SPLIT1, SPLIT1 + 0.22))
    split_halves(d, e, 540, 1010, 620, 300, 1.0, paws=None, lw=LW + 1, cloth=False)
    for k, (ox, oy, ph) in enumerate([(-170, -40, 0.0), (150, -60, 0.9), (-120, 50, 1.7), (190, 30, 2.4)]):
        tw = max(0.0, math.sin(t * 4.2 + ph * 2.1))
        if tw > 0.15:
            d.polygon(P(sparkle_pts(540 + ox * (0.6 + 0.4 * e), 1010 + oy, 18 * tw)), fill=(255, 255, 255, int(230 * tw)))
    soft["glows"].append((540, 1000, 700, GLOW1, 0.25))
    soft["glows"].append((540, 980, 330, GLOW2, 0.2 + 0.12 * e))
    soft["steam"] += steam_burst(t, -1.0, 540, 930, 50, 31, n_burst=0, trickle=10, until=SPLIT1, amax=0.22)
    soft["steam"] += steam_burst(t, SPLIT1, 540, 920, 170, 32, n_burst=30, trickle=16, until=3.0)
    draw_embers(d, embers(t, -1.0, 3.0, 3, 540, 1300, 400, 7, vmin=90, vmax=160, life=1.6), soft)
    soft["vig"] = 0.5

def tree(d, x, base, hgt, col=TREE):
    shape(d, rrect(x, base - hgt * 0.16, 46, hgt * 0.34, 8), hexc("#3B2B20"), shade=False, lw=5)
    for tier in range(3):
        yy = base - hgt * 0.25 - tier * hgt * 0.22
        wd = 170 - tier * 38
        shape(d, [(x - wd, yy), (x, yy - hgt * 0.36), (x + wd, yy)], col, lw=5, frac=0.3)


def hut(d, x0, base):
    wall = [(x0, base - 330), (x0 + 400, base - 330), (x0 + 400, base), (x0, base)]
    shape(d, wall, WALL, shadow=True)
    for k in range(1, 6):
        stroke(d, [(x0, base - 330 + k * 55), (x0 + 400, base - 330 + k * 55)], dark(WALL, 0.2), 3)
    roof = [(x0 - 50, base - 320), (x0 + 200, base - 520), (x0 + 450, base - 320)]
    shape(d, roof, hexc("#5C3A21"), frac=0.4)
    win = rrect(x0 + 110, base - 200, 120, 120, 10)
    shape(d, win, hexc("#FFD98A"), shade=False)
    stroke(d, [(x0 + 110, base - 260), (x0 + 110, base - 140)], PLANK, 8)
    stroke(d, [(x0 + 50, base - 200), (x0 + 170, base - 200)], PLANK, 8)
    shape(d, rrect(x0 + 300, base - 120, 110, 240, 8), PLANK, frac=0.3)
    return (x0 + 110, base - 200)


def tori_walk_pose(t, t0=0.0):
    ph = 2 * math.pi * (t - t0) / 0.5
    legs = (12 * max(0.0, math.sin(ph)), 12 * max(0.0, -math.sin(ph)))
    bob = -6 * abs(math.sin(ph))
    rot = 3 * math.sin(ph)
    return legs, bob, rot, ph


def scene_forest(d, t, soft):
    u = t - WALK_T0
    par = -20 * u
    for x, base, hgt in [(90, 1300, 620), (330, 1272, 520), (560, 1290, 580)]:
        tree(d, x + par, base, hgt)
    hwin = hut(d, 760 + par, 1320)
    soft["glows"].append((hwin[0], hwin[1], 230, hexc("#FFB45A"), 0.55))
    soft["glows"].append((hwin[0] + 40, 1380, 260, hexc("#FFB45A"), 0.18))
    # 웅덩이
    for i, (px, py, hw) in enumerate(PUDDLES):
        shape(d, ell(px, py, hw, hw * 0.24, n=32), hexc("#3C4F6E"), shade=False, lw=4)
        d.polygon(P(ell(px - hw * 0.25, py - 3, hw * 0.4, hw * 0.05, n=16)), fill=(0xBF, 0xD4, 0xF0, 110))
        rng = np.random.default_rng(40 + i)
        for k in range(14):                     # 빗방울 파문
            tb = rng.uniform(0, 4.5)
            age = (t - 2.5 - tb) % 0.9
            if age < 0.5:
                ox = rng.uniform(-0.6, 0.6) * hw
                rr = 4 + 30 * age / 0.5
                pts = ell(px + ox, py + rng.uniform(-3, 3), rr, rr * 0.26, n=20)
                d.line(P(pts + [pts[0]]), fill=(0xC8, 0xDC, 0xF5, int(170 * (1 - age / 0.5))), width=2 * S)
    # 땅 위 튀는 빗방울
    rng = np.random.default_rng(55)
    for k in range(40):
        tb = rng.uniform(0, 0.4)
        x = rng.uniform(0, W)
        y = rng.uniform(1290, 1560)
        age = (t + tb) % 0.4
        if age < 0.12:
            a = int(200 * (1 - age / 0.12))
            s_ = 6 + 40 * age
            d.line(P([(x - s_, y - s_ * 0.8), (x, y)]), fill=RAIN_C + (a,), width=2 * S)
            d.line(P([(x + s_, y - s_ * 0.8), (x, y)]), fill=RAIN_C + (a,), width=2 * S)
    # 풀
    for k in range(18):
        gx = (k * 67 + 20) % W
        gy_ = 1300 + (k % 3) * 8 if k % 2 else 1450 + (k % 4) * 10
        for j in (-1, 0, 1):
            stroke(d, [(gx + j * 9, gy_), (gx + j * 16, gy_ - 30 - 8 * (j == 0))], hexc("#2F5236"), 5)
    # 토리
    x = walk_x(t)
    sc = 1.2
    legs, bob, rot, ph = tori_walk_pose(t, WALK_T0)
    gy = 1350 + bob * sc
    sw = math.sin(ph) * 4
    hand_l = (x - 130 * sc, gy - 80 * sc)
    hand_r = (x + 70 * sc, gy - 140 * sc)
    top = (x + 20, gy - 450 + 4 * math.sin(ph))

    def held(dd):
        basket(dd, hand_l[0], hand_l[1] + 14, rot=sw)

    hog(d, "tori", x, gy, sc=sc, rot=rot, turn=0.55, legs=legs, hands=(hand_l, hand_r), held=held,
        blink=blink_amt(t, 1.1), mouth="smile")
    tips = leaf_umbrella(d, hand_r, top, rot=-4 + sw * 0.6)
    # 잎 끝에서 떨어지는 물방울
    for k in range(6):
        age = (t * 1.4 + k * 0.37) % 1.0
        tp = tips[k % 2]
        if age < 0.45:
            dd_ = (tp[0] + (k % 3 - 1) * 6, tp[1] + 10 + 1100 * age * age)
            d.polygon(P(ell(dd_[0], dd_[1], 5, 7, n=10)), fill=(0xB8, 0xD4, 0xF2, 220))
    # 웅덩이 지날 때 튀는 물
    for i, ts in enumerate(SPLASH_T):
        draw_drops(d, droplets(t, ts, 5, PUDDLES[i][0], PUDDLES[i][1] - 8, 60 + i, speed=420, g=2000, life=0.4,
                               cone=(215, 325)))
    rain_lines(d, t, N_RAIN)
    soft["amb"] = (0.78, 0.84, 1.0)
    soft["vig"] = 0.45


def scene_room_wide(d, t, soft, ci, rain_n=150, moon_a=0.0, win=(520, 500, 400, 500), lant=(160, 560),
                    braz=(880, 1255), sky_k=0.0):
    if win:
        window(d, win, t, rain_n=rain_n, moon_a=moon_a, sky_k=sky_k)
        soft["glows"].append((win[0] + win[2] / 2, win[1] + win[3] / 2, 320, (0x6F, 0x86, 0xB5), 0.10))
        if moon_a > 0:
            soft["glows"].append((win[0] + win[2] - 103, win[1] + 113, 260, MOON, 0.35 * moon_a))
    if lant:
        lantern(d, lant[0], lant[1], t)
        soft["glows"].append((lant[0], lant[1], 380, hexc("#FFB45A"), 0.42))
        soft["glows"].append((lant[0], lant[1], 120, hexc("#FFE2A8"), 0.35))
    if braz:
        bx, by = braz
        brazier(d, bx, by - 70, 130, 70)
        coal_pile(d, make_coals(bx, by - 78, 200, 6, 18, 26, 3, mound=20), 0.55, t, 0.6, bed=(bx, by - 74, 115, 16))
        fl = 0.8 + 0.2 * math.sin(2 * math.pi * 2 * t)
        soft["glows"].append((bx, by - 100, 340, GLOW1, 0.3 * fl))


def scene_door(d, t, soft):
    door = (40, 700, 290, 1250)
    shape(d, rrect(165, 975, 290, 590, 6), PLANK, shade=False)
    gl = (door[0] + 10, door[1] + 10, door[2] - 10, door[3])
    e = ease_io(seg(t, DOOR_T, DOOR_T + 0.3))
    if e < 1:
        d.rectangle(P([gl[:2], gl[2:]]), fill=NIGHT)
        rain_lines(d, t, 80, clip=gl, alpha=0.6)
    pw = (gl[2] - gl[0]) * (0.12 + 0.88 * e)
    panel = [(gl[0], gl[1]), (gl[0] + pw, gl[1]), (gl[0] + pw, gl[3]), (gl[0], gl[3])]
    shape(d, panel, hexc("#9C7452"), frac=0.25)
    for k in range(1, 4):
        xx = gl[0] + pw * k / 4
        stroke(d, [(xx, gl[1] + 6), (xx, gl[3] - 6)], dark(hexc("#9C7452"), 0.25), 3)
    if e > 0.6:
        circle(d, gl[0] + pw - 30, 990, 11, hexc("#E9C46A"), shade=False, lw=3)


def scene_hut_in(d, t, soft):
    scene_room_wide(d, t, soft, 2)
    scene_door(d, t, soft)
    x0 = 430
    # 토리 상태
    shake = 0.0
    rot = 0.0
    if SHAKE_T <= t < SHAKE_T + 0.6:
        env = math.sin(math.pi * (t - SHAKE_T) / 0.6) ** 0.5
        shake = 25 * math.sin(2 * math.pi * 6 * (t - SHAKE_T)) * env
        rot = 6 * math.sin(2 * math.pi * 6 * (t - SHAKE_T) + 0.6) * env
    settle = t - (SHAKE_T + 0.6)
    sx = sy = 1.0
    if 0 <= settle < 0.5:
        q = math.sin(settle / 0.5 * math.pi * 2) * math.exp(-settle * 5)
        sx, sy = 1 + 0.07 * q, 1 - 0.07 * q
    fluff = 1.0 + (0.18 * math.exp(-max(0, settle) * 3) if settle >= 0 else 0.0)
    step = ease_io(seg(t, 10.0, 10.5))
    x = x0 + shake + 50 * step
    legs = (0.0, 0.0)
    if 10.0 <= t < 10.6:
        legs, _, _, _ = tori_walk_pose(t, 10.0)
    eyes, mouth = "open", "smile"
    if SHAKE_T - 0.05 <= t < SHAKE_T + 0.65:
        eyes, mouth = "squeeze", "wavy"
    elif SHAKE_T + 0.65 <= t < SHAKE_T + 1.6:
        eyes, mouth = "happy", "open"
    gy = 1350
    # 바구니 위치
    put = ease_io(seg(t, 6.6, 7.0))
    pick = ease_io(seg(t, 9.4, 9.9))
    floor_b = (300, 1290)
    hold_b = (x - 128, gy - 68)
    if t < 9.4:
        bpos = lerp_pt((x0 - 128, gy - 68), floor_b, put)
    else:
        bpos = lerp_pt(floor_b, hold_b, pick)
    hand_r = None
    hand_l = bpos if (t < 7.0 or t >= 9.4) else None
    if t >= 9.4 and pick < 0.4:
        hand_l = lerp_pt((x - 134, gy - 58), bpos, pick / 0.4)
    leaf(d, 600, 1345, -76)

    def held(dd):
        basket(dd, bpos[0], bpos[1] + 14, rot=0)

    blink = blink_amt(t, 0.4)
    hog(d, "tori", x, gy, rot=rot, sx=sx, sy=sy, turn=0.25 if t < 9.9 else 0.5, eyes=eyes, mouth=mouth,
        hands=(hand_l, hand_r), held=held, fluff=fluff, legs=legs, blink=blink,
        blush=0.6 + 0.25 * (eyes == "happy"))
    # 젖은 몸에서 떨어지는 물방울 (털기 전)
    if t < SHAKE_T:
        for k in range(5):
            age = (t * 1.1 + k * 0.21) % 0.7
            px = x + (-110 + k * 55)
            py = gy - 200 + 60 * abs(math.sin(k)) + 600 * age * age
            if py < gy:
                d.polygon(P(ell(px, py, 5, 7, n=10)), fill=(0xA8, 0xD8, 0xF5, 230))
    draw_drops(d, droplets(t, SHAKE_T + 0.05, 20, x0, gy - 140, 77, speed=600, g=1800, life=0.65,
                           cone=(150, 390), spread_r=90))
    # 털고 난 뒤 반짝
    if 0 <= settle < 1.2:
        for k, (ox, oy) in enumerate([(-170, -270), (160, -300), (190, -150), (-200, -130)]):
            tw = bump(settle, k * 0.15, 0.6)
            if tw > 0:
                d.polygon(P(sparkle_pts(x0 + ox, gy + oy, 20 * tw)), fill=(255, 250, 220, int(255 * tw)))
    soft["amb"] = (0.86, 0.82, 0.8)
    soft["vig"] = 0.5


def tub_geom():
    return dict(cx=560, rim=1180, rx=262, ry=80, wrx=236, wry=66, bot=1450)


def scene_wash(d, t, soft):
    g = tub_geom()
    cx, rim = g["cx"], g["rim"]
    tori_x, tori_gy, sc = 560, 1190, 1.45
    # 각 고구마 위치
    basket_spots = [(388, 1170, 18), (345, 1162, -10), (300, 1172, 12)]
    plate_spots = [(752, 1205, -8), (806, 1196, 6), (858, 1208, -4)]
    pot = []
    for i, T0 in enumerate(DIP_T):
        b = basket_spots[i]
        pl = plate_spots[i]
        above = (cx, rim - 48)
        dip = (cx, rim + 2)
        state = "basket"
        pos, rot = (b[0], b[1]), b[2]
        if t >= T0 - 0.4:
            if t < T0 - 0.15:
                u = ease_io(seg(t, T0 - 0.4, T0 - 0.15))
                pos = (lerp(b[0], above[0], u), lerp(b[1], above[1], u) - 22 * math.sin(math.pi * u))
                rot = lerp(b[2], 0, u)
                state = "held"
            elif t < T0:
                u = ease_in(seg(t, T0 - 0.15, T0))
                pos, rot, state = lerp_pt(above, dip, u), 0, "held"
            elif t < T0 + 0.3:
                q = t - T0
                pos = (cx + 12 * math.sin(2 * math.pi * 5 * q), rim + 2 + 3 * math.sin(2 * math.pi * 10 * q))
                rot = 6 * math.sin(2 * math.pi * 5 * q)
                state = "water"
            elif t < T0 + 0.6:
                u = ease_io(seg(t, T0 + 0.3, T0 + 0.6))
                pos = (lerp(dip[0], pl[0], u), lerp(dip[1], pl[1], u) - 30 * math.sin(math.pi * u))
                rot = lerp(0, pl[2], u)
                state = "held"
            else:
                pos, rot, state = (pl[0], pl[1]), pl[2], "plate"
        pot.append((pos, rot, state, t >= T0))
    holding = [p for p in pot if p[2] in ("held", "water")]
    hands = (None, None)
    if holding:
        (px, py), r_, st, _ = holding[0]
        ca, sa = math.cos(math.radians(r_)), math.sin(math.radians(r_))
        hands = ((px - 78 * ca, py - 78 * sa + 4), (px + 78 * ca, py + 78 * sa + 4))
    look_down = (0.0, 1.0)
    eyes = "open"
    mouth = "smile"
    if t > 13.75:
        eyes, mouth = "happy", "open"
    hog(d, "tori", tori_x, tori_gy, sc=sc, eyes=eyes, mouth=mouth, look=look_down, draw_arms=False,
        blink=blink_amt(t, 2.1), shadow=False)
    # 대야 몸통
    body = ell(cx, rim, g["rx"], g["ry"], n=40, a0=0, a1=180, closed=False)
    bot = ell(cx, g["bot"], g["rx"] * 0.9, 50, n=40, a0=180, a1=0, closed=False)
    tubpoly = bot[::-1][::-1]
    shape(d, body + bot, TUB, shadow=True, frac=0.45)
    for j in range(-4, 5):
        xx = cx + j * 52
        stroke(d, [(xx, rim + g["ry"] * math.sqrt(max(0, 1 - (j * 52 / g["rx"]) ** 2)) - 2),
                   (cx + j * 47, g["bot"] + 44 * math.sqrt(max(0, 1 - (j * 47 / (g["rx"] * 0.9)) ** 2)))],
               dark(TUB, 0.25), 3)
    for yy, rr in ((rim + 95, 0.985), (g["bot"] - 50, 0.93)):
        band = ell(cx, yy, g["rx"] * rr, g["ry"] * 0.9, n=32, a0=10, a1=170, closed=False)
        stroke(d, band, OUTLINE, 20)
        stroke(d, band, hexc("#7A5230"), 13)
    del tubpoly
    shape(d, ell(cx, rim, g["rx"], g["ry"], n=56), light(TUB, 0.12), shade=False)
    shape(d, ell(cx, rim + 4, g["wrx"], g["wry"], n=56), WATER, shade=False, lw=4)
    d.polygon(P(ell(cx - 70, rim - 22, 90, 10, n=20)), fill=(255, 255, 255, 90))
    # 물 위 파문과 물보라
    for i, T0 in enumerate(DIP_T):
        for k in range(3):
            age = t - T0 - k * 0.18
            if 0 <= age < 0.9:
                rr = 30 + 180 * age
                pts = ell(cx, rim + 4, min(rr, g["wrx"] - 4), min(rr * 0.27, g["wry"] - 4), n=40)
                d.line(P(pts + [pts[0]]), fill=(255, 255, 255, int(180 * (1 - age / 0.9))), width=3 * S)
    # 물에 담긴 고구마 (반투명 물 덮기)
    for (pos, r_, st, done) in pot:
        if st == "water":
            potato(d, pos[0], pos[1], 200, 92, r_, wet=True)
            water_cover = clip_half(ell(cx, rim + 4, g["wrx"], g["wry"], n=56), pos[1] - 6)
            d.polygon(P(water_cover), fill=WATER + (150,))
            stroke(d, [(pos[0] - 95, pos[1] - 6), (pos[0] + 95, pos[1] - 6)], (255, 255, 255, 150), 3)
    # 거품
    rng = np.random.default_rng(88)
    for i, T0 in enumerate(DIP_T):
        for k in range(10):
            b0 = T0 + rng.uniform(0, 0.9)
            life = rng.uniform(0.5, 1.0)
            age = t - b0
            ox, oy, r0 = rng.uniform(-170, 170), rng.uniform(-30, 30), rng.uniform(8, 16)
            if 0 <= age < life:
                bx, by = cx + ox * (0.4 + age), rim + 4 + oy * (0.4 + age * 0.6)
                a = int(180 * (1 - age / life))
                pts = ell(bx, by, r0, r0 * 0.8, n=16)
                d.polygon(P(pts), fill=(255, 255, 255, int(a * 0.45)))
                d.line(P(pts + [pts[0]]), fill=(255, 255, 255, a), width=2 * S)
                d.polygon(P(ell(bx - r0 * 0.35, by - r0 * 0.3, r0 * 0.25, r0 * 0.2, n=8)), fill=(255, 255, 255, a))
            elif life <= age < life + 0.12:          # 톡 터짐
                q = (age - life) / 0.12
                bx, by = cx + ox * (0.4 + life), rim + 4 + oy * (0.4 + life * 0.6)
                for j in range(4):
                    aa = j * math.pi / 2 + 0.6
                    rr = r0 * (1 + q)
                    d.line(P([(bx + math.cos(aa) * rr, by + math.sin(aa) * rr * 0.8),
                              (bx + math.cos(aa) * (rr + 6), by + math.sin(aa) * (rr + 6) * 0.8)]),
                           fill=(255, 255, 255, int(200 * (1 - q))), width=2 * S)
    # 팔 (뒤에서 대야로)
    shoulders = [xf([(side * 104, -108)], tori_x, tori_gy, sc)[0] for side in (-1, 1)]
    for side, sh, hd in zip((-1, 1), shoulders, hands):
        if hd is None:
            hd = (sh[0] + side * 30, sh[1] + 120)
            hd = (sh[0] + side * 10, rim - 32)
        shape(d, capsule(sh, hd, 34 * sc), BODY, frac=0.3)
    # 바구니(왼쪽 앞)·접시(오른쪽 앞)
    plate = ell(805, 1222, 118, 30, n=40)
    shape(d, plate, hexc("#EADBC8"), shadow=True, frac=0.4)
    stroke(d, ell(805, 1218, 92, 20, n=32), dark(hexc("#EADBC8"), 0.15), 3, closed=True)
    for (pos, r_, st, done) in pot:
        if st == "plate":
            potato(d, pos[0], pos[1], 112, 54, r_, wet=True, lw=5)
    bsk = (345, 1196)
    stroke(d, ell(bsk[0], bsk[1], 70, 76, n=16, a0=180, a1=360, closed=False), OUTLINE, 11)
    stroke(d, ell(bsk[0], bsk[1], 70, 76, n=16, a0=180, a1=360, closed=False), BASKET, 6)
    for (pos, r_, st, done) in pot:
        if st == "basket":
            potato(d, pos[0], pos[1], 112, 54, r_, lw=5)
    shape(d, ell(bsk[0], bsk[1], 92, 72, n=32, a0=0, a1=180, closed=False), BASKET, shadow=True)
    for j in range(-2, 3):
        stroke(d, [(bsk[0] + j * 30, bsk[1] + 4), (bsk[0] + j * 24, bsk[1] + 64)], dark(BASKET, 0.25), 3)
    stroke(d, [(bsk[0] - 92, bsk[1]), (bsk[0] + 92, bsk[1])], OUTLINE, LW)
    # 들고 있는 고구마 (손 아래에)
    for (pos, r_, st, done) in pot:
        if st == "held":
            potato(d, pos[0], pos[1], 200, 92, r_, wet=done)
            ca, sa = math.cos(math.radians(r_)), math.sin(math.radians(r_))
            for side in (-1, 1):
                hx, hy = pos[0] + side * 78 * ca, pos[1] + side * 78 * sa + 4
                shape(d, ell(hx, hy, 26 * 1.0, 24, n=20), BODY, frac=0.35)
            if done:
                for k in range(3):
                    age = (t * 2 + k * 0.33) % 1.0
                    d.polygon(P(ell(pos[0] - 60 + k * 60, pos[1] + 40 + 260 * age * age, 5, 7, n=10)),
                              fill=(0xA8, 0xD8, 0xF5, int(230 * (1 - age))))
    for i, T0 in enumerate(DIP_T):
        draw_drops(d, droplets(t, T0, 8, cx, rim - 10, 120 + i, speed=520, g=2000, life=0.45, cone=(205, 335)))
    soft["glows"].append((-80, 260, 900, hexc("#FFB45A"), 0.3))
    soft["glows"].append((1180, 1600, 700, GLOW1, 0.22))
    soft["amb"] = (0.88, 0.85, 0.82)
    soft["vig"] = 0.45


BRAZ5 = dict(cx=700, rim=1135, rx=290, depth=290)
COALS5 = make_coals(700, 1125, 470, 12, 34, 52, 21, mound=70)
TARGETS5 = [(612, 1040), (700, 1018), (790, 1040)]


def scene_brazier(d, t, soft):
    b = BRAZ5
    scene_room_wide(d, t, soft, 4, win=(700, 330, 300, 380), lant=None, braz=None)
    level = lerp(0.5, 1.0, ease_io(seg(t, FAN_T0, FAN_T1 - 0.3)))
    brazier(d, b["cx"], b["rim"], b["rx"], b["depth"])
    coal_pile(d, COALS5, level, t, bed=(b["cx"], b["rim"] - 10, b["rx"] * 0.9, 50))
    # 숯 위 고구마
    pot_draw = []
    plate_c = (330, 1468)
    plate_spots = [(292, 1458), (336, 1450), (380, 1460)]
    tori_x, tori_gy = 225, 1405
    hand_r = (380, 1300)
    tong_tip = None
    fan_ang = None
    holding_k = None
    for k, g0 in enumerate(PLACE_G):
        tgt = TARGETS5[k]
        drop_y0 = tgt[1] - 90
        if t < g0 + 0.1:
            pos = plate_spots[k]
            st = "plate"
        elif t < g0 + 0.32:
            u = ease_io(seg(t, g0 + 0.1, g0 + 0.32))
            pos = (lerp(plate_spots[k][0], tgt[0], u), lerp(plate_spots[k][1], drop_y0, u) - 80 * math.sin(math.pi * u))
            st = "tongs"
            holding_k = k
        elif t < g0 + 0.55:
            u = ease_in(seg(t, g0 + 0.32, g0 + 0.55))
            pos = (tgt[0], lerp(drop_y0, tgt[1], u))
            st = "fall"
        else:
            q = t - (g0 + 0.55)
            pos = (tgt[0], tgt[1] - 4 * abs(math.sin(q * 18)) * math.exp(-q * 10))
            st = "coal"
        pot_draw.append((pos, st))
    # 집게 끝 위치
    if PLACE_G[0] - 0.1 <= t < PLACE_G[-1] + 0.55:
        tong_tip = None
        for k, g0 in enumerate(PLACE_G):
            if g0 - 0.1 <= t < g0 + 0.1:
                prev = TARGETS5[k - 1] if k else (430, 1440)
                prev = (prev[0], prev[1] - 90) if k else prev
                u = ease_io(seg(t, g0 - 0.1, g0 + 0.1))
                tong_tip = lerp_pt(prev, (plate_spots[k][0], plate_spots[k][1] - 6), u)
            elif g0 + 0.1 <= t < g0 + 0.32:
                tong_tip = (pot_draw[k][0][0], pot_draw[k][0][1] - 6)
            elif g0 + 0.32 <= t < g0 + 0.55:
                tong_tip = (TARGETS5[k][0], TARGETS5[k][1] - 96)
        if tong_tip is None:
            tong_tip = (TARGETS5[-1][0] - 60, TARGETS5[-1][1] - 140)
    elif t >= PLACE_G[-1] + 0.55:
        u = ease_io(seg(t, PLACE_G[-1] + 0.55, PLACE_G[-1] + 0.95))
        tong_tip = lerp_pt((TARGETS5[-1][0] - 60, TARGETS5[-1][1] - 140), (470, 1440), u)
    if t < FAN_T1 + 0.1:
        sw = 30 * math.sin(2 * math.pi * 3 * (t - FAN_T0)) if FAN_T0 <= t < FAN_T1 else 0
        ramp = ease_io(seg(t, FAN_T0 - 0.3, FAN_T0))
        fan_ang = -38 + sw - 12 * (1 - ramp)
    # 토리
    lean = 0.0
    if tong_tip:
        lean = 6
    blink = blink_amt(t, 0.7)
    eyes = "open"
    mouth = "smile"
    if FAN_T0 <= t < FAN_T1:
        mouth = "o"
    if t > LAND_T[-1]:
        eyes, mouth = "happy", "open"
    hands = (None, hand_r)
    hand_t = None
    if tong_tip:
        sh = xf([(104, -108)], tori_x, tori_gy, 1.0, lean)[0]
        dx, dy = tong_tip[0] - sh[0], tong_tip[1] - sh[1]
        Ld = math.hypot(dx, dy)
        hand_t = (tong_tip[0] - dx / Ld * 290, tong_tip[1] - dy / Ld * 290) if Ld > 300 else lerp_pt(sh, tong_tip, 0.25)
        hands = (None, hand_t)
    if fan_ang is not None and not tong_tip:
        hands = (None, hand_r)
    # 부채 (내려놓기 전)
    fan_floor = (250, 1500)

    def held(dd):
        pass

    hog(d, "tori", tori_x, tori_gy, rot=lean, turn=0.45, sit=True, eyes=eyes, mouth=mouth, hands=hands,
        blink=blink, blush=0.6 + 0.2 * level, draw_arms=False)
    # 접시
    shape(d, ell(plate_c[0], plate_c[1] + 8, 110, 28, n=40), hexc("#EADBC8"), shadow=True, frac=0.4)
    for k, (pos, st) in enumerate(pot_draw):
        if st == "plate":
            potato(d, pos[0], pos[1], 100, 50, -8 + 8 * k, wet=False, lw=5)
    for k, (pos, st) in enumerate(pot_draw):
        if st in ("fall", "coal"):
            potato(d, pos[0], pos[1], 130, 64, -6 + 6 * k, lw=5, glow=level)
    # 부채
    if fan_ang is not None:
        fan(d, hand_r[0] + 8, hand_r[1] - 8, fan_ang)
    else:
        fan(d, fan_floor[0], fan_floor[1], -8, r=110)
    # 집게
    if tong_tip:
        if holding_k is not None:
            pos = pot_draw[holding_k][0]
            potato(d, pos[0], pos[1], 130, 64, 0, lw=5)
        tongs(d, hand_t, tong_tip, open_=0.15 if holding_k is not None else 0.5)
    elif t < PLACE_G[0] - 0.1:
        tongs(d, (470, 1452), (700, 1470), open_=0.2)
    # 팔
    for side, hd in ((-1, None), (1, hands[1])):
        sh = xf([(side * 104 + 0.45 * 26 * 0.2, -108)], tori_x, tori_gy, 1.0, lean)[0]
        if hd is None:
            hd = xf([(side * 134, -58)], tori_x, tori_gy, 1.0, lean)[0]
        shape(d, capsule(sh, hd, 34), BODY, frac=0.3)
    # 불씨
    rate_pts = embers(t, 14.5, FAN_T0, 4, 700, 1040, 200, 13) + embers(t, FAN_T0, FAN_T1, 25, 700, 1030, 220, 14) \
        + embers(t, FAN_T1, 20.5, 5, 700, 1040, 200, 15)
    draw_embers(d, rate_pts, soft)
    for k, lt in enumerate(LAND_T):
        draw_embers(d, embers(t, lt, lt + 0.12, 60, TARGETS5[k][0], TARGETS5[k][1], 50, 300 + k,
                              vmin=150, vmax=300, life=0.6), soft)
    fl = level * (0.75 + 0.25 * math.sin(2 * math.pi * 2 * t))
    soft["glows"].append((700, 1060, 650, GLOW1, 0.42 * fl))
    soft["glows"].append((700, 1050, 260, GLOW2, 0.35 * fl))
    soft["glows"].append((300, 1250, 300, GLOW1, 0.18 * fl))
    soft["amb"] = (0.72, 0.68, 0.7)
    soft["vig"] = 0.55


COALS6 = make_coals(540, 1280, 1150, 13, 80, 118, 33, mound=60)
POT6 = [(300, 1110, -7), (548, 1085, 3), (800, 1112, 8)]


def scene_flip(d, t, soft):
    shape(d, ell(540, 1330, 680, 70, n=60), light(CLAY, 0.15), shade=False)
    bowl = ell(540, 1330, 660, 620, n=60, a0=0, a1=180, closed=False)
    shape(d, bowl, CLAY, frac=0.6)
    coal_pile(d, COALS6, 1.0, t, scale=1.6, bed=(540, 1290, 640, 100))
    hinge = (1250, 640)
    tip = None
    grab = None
    for k, (px, py, r0) in enumerate(POT6):
        F = FLIP_T[k]
        u = seg(t, F, F + 0.4)
        flipped = t >= F + 0.2
        lift = 50 * math.sin(math.pi * u) if F <= t < F + 0.4 else 0.0
        fy = math.cos(math.pi * ease_io(u)) if F <= t < F + 0.4 else (-1.0 if t >= F + 0.4 else 1.0)
        ch = 0.25 * seg(t, 20, 24) if not flipped else 0.0
        glow = 0.6 + 0.4 * math.sin(t * 3 + k)
        potato(d, px, py - lift, 300, 150, r0, fy=fy, chars=ch, lw=LW + 1, glow=glow * 0.6)
        if F - 0.3 <= t < F + 0.45:
            grab = k
            tip = (px + 20, py - lift - 30)
        # 착지 불씨
        draw_embers(d, embers(t, F + 0.4, F + 0.52, 70, px, py + 40, 110, 400 + k, vmin=180, vmax=360, life=0.7), soft)
    # 집게 이동
    if tip is None:
        if t < FLIP_T[0] - 0.3:
            u = ease_out(seg(t, 20.15, FLIP_T[0] - 0.3))
            tip = lerp_pt((1260, 900), (POT6[0][0] + 20, POT6[0][1] - 30), u)
        else:
            nxt = [k for k in range(3) if t < FLIP_T[k] - 0.3]
            if nxt:
                k = nxt[0]
                u = ease_io(seg(t, FLIP_T[k - 1] + 0.45, FLIP_T[k] - 0.3))
                tip = lerp_pt((POT6[k - 1][0] + 20, POT6[k - 1][1] - 30), (POT6[k][0] + 20, POT6[k][1] - 30), u)
            else:
                u = ease_io(seg(t, FLIP_T[2] + 0.45, FLIP_T[2] + 0.9))
                tip = lerp_pt((POT6[2][0] + 20, POT6[2][1] - 30), (1300, 760), u)
    tongs(d, hinge, tip, open_=0.25 if grab is not None else 0.6, wdt=22)
    draw_embers(d, embers(t, 19.5, 24.5, 9, 540, 1200, 480, 17, vmin=150, vmax=320, life=1.0), soft)
    # 연기·김 (뒤집은 뒤 늘어남)
    for k, (px, py, r0) in enumerate(POT6):
        soft["steam"] += steam_burst(t, FLIP_T[k] + 0.4, px, py - 70, 70, 500 + k, n_burst=6, trickle=4 + 4 * seg(t, 22.8, 24),
                                     until=24.6, rmin=18, rmax=34, amax=0.22, speed=110, life=1.4)
    soft["glows"].append((540, 1300, 800, GLOW1, 0.5 * (0.85 + 0.15 * math.sin(2 * math.pi * 2 * t))))
    soft["glows"].append((540, 1200, 420, GLOW2, 0.3))
    soft["amb"] = (0.66, 0.6, 0.62)
    soft["vig"] = 0.55


def scene_split(d, t, soft):
    scene_room_wide(d, t, soft, 6, win=(600, 330, 380, 470), lant=(160, 430), braz=None)
    tori_x, tori_gy, sc = 540, 1300, 1.7
    split = t >= SPLIT2
    e = ease_out(seg(t, SPLIT2, SPLIT2 + 0.25))
    hop = 0.0
    sx = sy = 1.0
    q = t - (SPLIT2 + 0.2)
    if 0 <= q < 0.5:
        hop = -26 * math.sin(math.pi * q / 0.5)
        sx, sy = 1 - 0.04 * math.sin(math.pi * q / 0.5), 1 + 0.04 * math.sin(math.pi * q / 0.5)
    ant = bump(t, SPLIT2 - 0.35, 0.35)       # 가르기 직전 살짝 웅크림
    sy *= 1 - 0.03 * ant
    sx *= 1 + 0.03 * ant
    gy = tori_gy + hop
    py = 1262 + hop
    eyes = "sparkle" if t < SPLIT2 + 0.12 else "happy"
    mouth = "smile" if not split else "open"
    ripe = ease_io(seg(t, SPLIT2, SPLIT2 + 0.5))
    L, Wd = 300, 140
    hold = {}

    def held(dd):
        if not split:
            potato(dd, 540, py, L, Wd * 0.9, 0, chars=0.6, lw=LW + 1)
            for side in (-1, 1):
                cl = xf(rrect(0, 0, 72, 124, 26), 540 + side * L * 0.36, py + 4, 1, side * 8)
                shape(dd, cl, CLOTH, frac=0.3)
            hold["h"] = [(540 - L * 0.36, py + 6), (540 + L * 0.36, py + 6)]
        else:
            hold["h"] = split_halves(dd, e, 540, py - 6, L, Wd, ripe, sep=30, tilt=(6, 12), open_=(0.3, 0.5))

    held(ImageDraw.Draw(Image.new("RGBA", (4, 4)), "RGBA"))       # 손 위치만 먼저 계산
    hands = tuple((hx, hy + 4) for hx, hy in hold["h"])
    hog(d, "tori", tori_x, gy, sc=sc, sx=sx, sy=sy, eyes=eyes, mouth=mouth, hands=hands, held=held,
        blink=1.0, blush=0.6 + 0.3 * ripe, look=(0, 0.7) if not split else (0, 0))
    if split:
        soft["steam"] += steam_burst(t, SPLIT2, 540, py - 70, 160, 71, n_burst=30, trickle=12, until=28.0, amax=0.3)
        for k, (ox, oy) in enumerate([(-220, -110), (210, -140), (-250, 30), (240, 10)]):
            tw = bump(t, SPLIT2 + 0.1 + k * 0.18, 0.7)
            if tw > 0:
                d.polygon(P(sparkle_pts(540 + ox, py + oy, 26 * tw)), fill=(255, 250, 220, int(255 * tw)))
    else:
        soft["steam"] += steam_burst(t, 23.5, 540, py - 50, 90, 70, n_burst=0, trickle=5, until=SPLIT2, amax=0.16)
    draw_embers(d, embers(t, 23.5, 28.0, 3, 120, 1700, 200, 19, vmin=150, vmax=260, life=1.4), soft)
    soft["glows"].append((540, py - 20, 300, GLOW2, 0.35 * ripe))
    soft["glows"].append((0, 1750, 950, GLOW1, 0.45 * (0.85 + 0.15 * math.sin(2 * math.pi * 2 * t))))
    soft["amb"] = (0.8, 0.77, 0.77)
    soft["vig"] = 0.5


BLANKET_C = (770, 1300)


def blanket_sprite():
    w, h = 540, 280
    img = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    mask = Image.new("L", (w * S, h * S), 0)
    pts = rrect(w / 2, h / 2 + 8, w - 20, h - 24, 90)
    ImageDraw.Draw(mask).polygon(P(pts), fill=255)
    fill = Image.new("RGB", img.size, BLANKET)
    d = ImageDraw.Draw(fill, "RGBA")
    for x in range(0, w, 60):
        d.line(P([(x + 10, 0), (x - 20, h)]), fill=CHECK + (255,), width=10 * S)
    for y in range(20, h, 60):
        d.line(P([(0, y), (w, y + 8)]), fill=CHECK + (255,), width=10 * S)
    d.polygon(P(clip_half(pts, h * 0.66)), fill=(0x8C, 0x6A, 0x4A, 40))
    img.paste(fill, (0, 0), mask)
    d2 = ImageDraw.Draw(img, "RGBA")
    d2.line(P(pts + pts[:2]), fill=OUTLINE + (255,), width=LW * S, joint="curve")
    for k in range(3):
        d2.line(P([(120 + k * 140, 70), (150 + k * 140, 180)]), fill=dark(BLANKET, 0.2) + (200,), width=3 * S)
    return img


def scene_share(d, t, soft, img):
    rain_n = int(N_RAIN * (1 - ease_io(seg(t, 30.0, 32.0))))
    moon_a = ease_io(seg(t, 30.0, 31.8))
    scene_room_wide(d, t, soft, 7, rain_n=rain_n, moon_a=moon_a, braz=None, sky_k=moon_a)
    tori_x, tori_gy = 400, 1350
    msc = 0.75
    rise = ease_out_back(seg(t, MIMI_T, MIMI_T + 0.4), 1.2)
    mimi_gy = lerp(1385, 1235, rise)
    mx = BLANKET_C[0]
    hump_y = lerp(1196, 1222, rise)
    shape(d, ell(mx, hump_y, 150, 64, n=40), dark(BLANKET, 0.07), frac=0.3)
    stroke(d, ell(mx, hump_y + 6, 120, 40, n=16, a0=200, a1=340, closed=False), CHECK, 6)
    # 반쪽 위치 (단면 중심)
    L, Wd = 190, 100
    give = ease_io(seg(t, GIVE_T, GIVE_T + 0.5))
    gather = ease_io(seg(t, GIVE_T + 0.5, GIVE_T + 0.8))
    to_mouth = ease_io(seg(t, BITE_T - 0.3, BITE_T)) * (1 - ease_io(seg(t, BITE_T + 0.15, BITE_T + 0.5)))
    lean = 6 * bump(t, GIVE_T - 0.1, 0.9)
    step = 100 * (ease_io(seg(t, GIVE_T - 0.35, GIVE_T)) - ease_io(seg(t, GIVE_T + 0.55, GIVE_T + 0.95)))
    tx = tori_x + step
    stepping = GIVE_T - 0.35 <= t < GIVE_T or GIVE_T + 0.55 <= t < GIVE_T + 0.95
    walk_legs = tori_walk_pose(t, GIVE_T - 0.35)[0] if stepping else (0.0, 0.0)
    face_l = lerp_pt((tx - 150, tori_gy - 64), (tx - 125, tori_gy - 70), gather)
    face_l = lerp_pt(face_l, (tx - 62, tori_gy - 84), to_mouth)
    mimi_face = (mx - 34, 1222 - 20 * to_mouth)
    face_r = lerp_pt((tx + 150, tori_gy - 64), mimi_face, give) if give < 1 else mimi_face
    bitten = t >= BITE_T
    blowing = BLOW_T <= t < BLOW_T + 0.45
    chewing = BITE_T <= t < BITE_T + 0.9
    blush_amt = 0.6 + 0.35 * ease_io(seg(t, HEART_T, HEART_T + 0.3))
    t_eyes, t_mouth = "open", "smile"
    m_eyes, m_mouth = "open", "smile"
    if blowing:
        t_mouth = m_mouth = "o"
    if chewing:
        t_eyes, t_mouth, m_eyes, m_mouth = "happy", "chew", "happy", "chew"
    elif t >= BITE_T + 0.9:
        t_eyes, t_mouth, m_eyes, m_mouth = "happy", "open", "happy", "open"
    chew_b = 1 + 0.03 * math.sin(2 * math.pi * 5 * (t - BITE_T)) if chewing else 1.0
    if MIMI_T <= t < MIMI_T + 0.5:
        m_eyes = "sparkle" if t > MIMI_T + 0.15 else "open"
    hog(d, "mimi", mx, mimi_gy, sc=msc, turn=-0.4 if t > MIMI_T + 0.5 else 0.0, eyes=m_eyes, mouth=m_mouth,
        blush=blush_amt, blink=blink_amt(t, 1.7, 2.5), draw_arms=False, shadow=False, sy=chew_b,
        look=(-1.0, 0.0) if MIMI_T + 0.5 < t < BLOW_T else (0.0, 0.0))
    img.alpha_composite(_G["blanket"], (int((BLANKET_C[0] - 270) * S), int((BLANKET_C[1] - 140) * S)))
    bob_l = 5 * abs(math.sin(2 * math.pi * 1.5 * (t - 27.5))) if t < MIMI_T else 0.0
    hands = {}

    def tori_held(dd):
        bite = (0, -Wd * 0.46, Wd * 0.26) if bitten else None
        broken_half(dd, face_l[0], face_l[1], L, Wd, rot=-14 + 10 * to_mouth, side=-1,
                    open_=0.8, ripe=1.0, lw=5, bite=bite)
        hands["l"] = xf([(-L * 0.34, 6)], face_l[0], face_l[1], 1, -14 + 10 * to_mouth)[0]
        if give < 1:
            broken_half(dd, face_r[0], face_r[1], L, Wd, rot=14, side=1, open_=0.8, ripe=1.0, lw=5)
            hands["r"] = (face_r[0] + 40, face_r[1] + 26)
        else:
            hands["r"] = lerp_pt((mimi_face[0] + L * 0.3, mimi_face[1] + 10), (tx + 134, tori_gy - 58), gather)

    tori_held(ImageDraw.Draw(Image.new("RGBA", (4, 4)), "RGBA"))
    hog(d, "tori", tx, tori_gy - bob_l, rot=lean, turn=0.35, eyes=t_eyes, mouth=t_mouth,
        blush=blush_amt, blink=blink_amt(t, 0.3), hands=(hands["l"], hands["r"]), held=tori_held, sy=chew_b,
        legs=walk_legs,
        look=(1.0, 0.0) if MIMI_T < t < GIVE_T + 0.5 else (0, 0))
    if give >= 1:
        bite = (0, -Wd * 0.46, Wd * 0.24) if bitten else None
        broken_half(d, face_r[0], face_r[1], L * 0.9, Wd * 0.9, rot=10, side=1, open_=0.8, ripe=1.0, lw=5, bite=bite)
    if give > 0.85:
        for side, hp in ((-1, (face_r[0] - 34, face_r[1] + 22)), (1, xf([(L * 0.3, 8)], face_r[0], face_r[1], 1, 10)[0])):
            sh = (mx + side * 70 * msc, mimi_gy - 80 * msc)
            shape(d, capsule(sh, hp, 26), BODY, frac=0.3)
    for k, (hx, hy) in enumerate((face_l, face_r)):
        soft["steam"] += steam_burst(t, 27.0, hx, hy - 40, 25, 600 + k, n_burst=0, trickle=6, until=31.0,
                                     rmin=14, rmax=26, amax=0.22, speed=90, life=1.1)
    if blowing:
        q = (t - BLOW_T) / 0.45
        for who, (ox, oy, dx) in enumerate(((tx + 14, tori_gy - 86, 1), (mx - 14, mimi_gy - 66, -1))):
            for j in range(3):
                qq = q - j * 0.12
                if 0 <= qq < 1:
                    r = 6 + 5 * j
                    px = ox + dx * (16 + 50 * qq)
                    py_ = oy + 26 * qq
                    pts = ell(px, py_, r, r, n=14)
                    d.polygon(P(pts), fill=(255, 255, 255, int(220 * (1 - qq))))
                    d.line(P(pts + [pts[0]]), fill=OUTLINE + (int(150 * (1 - qq)),), width=2 * S)
    if t >= HEART_T:
        spots = [(tx - 70, 1010), (tx + 70, 990), (tx, 950), (mx - 60, 1040), (mx + 60, 1020), (mx, 980)]
        for k, (hx, hy) in enumerate(spots):
            age = t - (HEART_T + 0.08 * k)
            if 0 <= age < 1.3:
                size = 60 * ease_out_back(age / 0.2) if age < 0.2 else 60
                a = 255 if age < 1.0 else int(255 * (1 - (age - 1.0) / 0.3))
                heart(d, hx + 10 * math.sin(age * 5 + k), hy - 110 * age, size, a=max(0, a))
    soft["glows"].append((-60, 1450, 820, GLOW1, 0.35 * (0.85 + 0.15 * math.sin(2 * math.pi * 2 * t))))
    soft["glows"].append((face_l[0], face_l[1], 160, GLOW2, 0.25))
    soft["amb"] = (0.82, 0.8, 0.8)
    soft["vig"] = 0.5


# ───────────────────────── 카메라·빛 합성 ─────────────────────────

CAMS = [   # (초점 x, 초점 y, 시작 줌, 끝 줌) — 컷마다 천천히 6% 줌인
    (540, 1000, 1.00, 1.06), (560, 1120, 1.06, 1.12), (520, 1100, 1.06, 1.12), (560, 1150, 1.08, 1.14),
    (500, 1230, 1.16, 1.22), (540, 1150, 1.05, 1.11), (540, 1150, 1.08, 1.14), (600, 1180, 1.10, 1.16),
]


def cam_box(ci, t):
    t0, t1 = CUTS[ci]
    fx, fy, z0, z1 = CAMS[ci]
    z = lerp(z0, z1, ease_io(seg(t, t0, t1)))
    if ci == 7 and t > 31.6:                          # 루프용: 토리 고구마로 빠르게 줌인
        u = ease_in(seg(t, 31.6, 32.0))
        z = lerp(z1, 2.6, u)
        fx, fy = lerp(fx, 260, u), lerp(fy, 1290, u)
    w, h = W / z, H / z
    left = min(max(fx - w / 2, 0), W - w)
    top = min(max(fy - h / 2, 0), H - h)
    return left, top, z


HS = 2                       # 빛 레이어 축소 배율
_YY, _XX = np.mgrid[0:H // HS, 0:W // HS].astype(np.float32)


def blob(acc, x, y, r, a, power=2.0):
    """acc(H/2, W/2)에 부드러운 원을 덮어 그린다 (알파 합성)"""
    x, y, r = x / HS, y / HS, max(r / HS, 1.0)
    x0, x1 = int(max(0, x - r - 1)), int(min(acc.shape[1], x + r + 2))
    y0, y1 = int(max(0, y - r - 1)), int(min(acc.shape[0], y + r + 2))
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = _YY[y0:y1, x0:x1], _XX[y0:y1, x0:x1]
    q = 1 - ((xx - x) ** 2 + (yy - y) ** 2) / (r * r)
    q = np.clip(q, 0, 1) ** power * a
    sub = acc[y0:y1, x0:x1]
    sub += q * (1 - sub)


def apply_light(arr, soft, box):
    left, top, z = box
    hh, ww = H // HS, W // HS
    amb = np.array(soft["amb"], np.float32)
    # 비네팅
    cx, cy = ww / 2, hh / 2
    r2 = ((_XX - cx) / (ww * 0.62)) ** 2 + ((_YY - cy) / (hh * 0.62)) ** 2
    vig = 1 - soft["vig"] * np.clip(r2, 0, 1.6) ** 1.3 * 0.55
    mult = vig[..., None] * amb[None, None, :]
    add = np.zeros((hh, ww, 3), np.float32)
    for (x, y, r, col, s) in soft["glows"]:
        sx_, sy_, sr = (x - left) * z / HS, (y - top) * z / HS, r * z / HS
        g = np.exp(-(((_XX - sx_) ** 2 + (_YY - sy_) ** 2) / (sr * sr)) * 2.2)
        c = np.array(col, np.float32) / 255
        mult += g[..., None] * c * s * 1.1
        add += g[..., None] * c * s * 0.28
    for (x, y, r, col, s) in soft["halos"]:
        sx_, sy_, sr = (x - left) * z / HS, (y - top) * z / HS, max(r * z / HS, 1)
        x0, x1 = int(max(0, sx_ - sr * 2)), int(min(ww, sx_ + sr * 2 + 1))
        y0, y1 = int(max(0, sy_ - sr * 2)), int(min(hh, sy_ + sr * 2 + 1))
        if x0 < x1 and y0 < y1:
            g = np.exp(-(((_XX[y0:y1, x0:x1] - sx_) ** 2 + (_YY[y0:y1, x0:x1] - sy_) ** 2) / (sr * sr)) * 2.5)
            add[y0:y1, x0:x1] += g[..., None] * (np.array(col, np.float32) / 255) * s
    steam = np.zeros((hh, ww), np.float32)
    for (x, y, r, a) in soft["steam"]:
        blob(steam, (x - left) * z, (y - top) * z, r * z, a, power=1.6)
    up = lambda m: np.asarray(Image.fromarray(m).resize((W, H), Image.BILINEAR))
    mult_f = np.stack([up(np.ascontiguousarray(mult[..., i])) for i in range(3)], -1)
    add_f = np.stack([up(np.ascontiguousarray(add[..., i])) for i in range(3)], -1)
    out = arr * mult_f + add_f * 255
    if soft["steam"]:
        st = up(steam)[..., None]
        out = out * (1 - st) + np.array([255, 248, 238], np.float32) * st
    return out


def render_cut(ci, t):
    img = bg(ci).copy()
    if ci == 7:
        img = img.convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    soft = new_soft()
    [scene_hook, scene_forest, scene_hut_in, scene_wash, scene_brazier, scene_flip, scene_split,
     lambda dd, tt, ss: scene_share(dd, tt, ss, img)][ci](d, t, soft)
    if img.mode == "RGBA":
        img = img.convert("RGB")
    box = cam_box(ci, t)
    left, top, z = box
    crop = img.resize((W, H), Image.LANCZOS, box=(left * S, top * S, (left + W / z) * S, (top + H / z) * S))
    arr = np.asarray(crop).astype(np.float32)
    return apply_light(arr, soft, box)


def cut_index(t):
    for i, (a, b) in enumerate(CUTS):
        if t < b:
            return i
    return len(CUTS) - 1


SUBS = [(0.5, 2.3, "비 오는 밤엔…"), (22.8, 24.0, "10분 뒤…"), (30.3, 31.8, "따끈따끈 반씩")]


def draw_subs(img, t):
    for t0, t1, text in SUBS:
        if not (t0 - 0.01 <= t < t1):
            continue
        a = min(seg(t, t0, t0 + 0.2), 1 - seg(t, t1 - 0.2, t1))
        if a <= 0:
            continue
        f = ImageFont.truetype(FONT, 72, index=FONT_BOLD)
        layer = Image.new("RGBA", (W, 220), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        rise = 12 * (1 - ease_out(seg(t, t0, t0 + 0.3)))
        ld.text((W / 2, 110 + rise), text, font=f, fill=(255, 255, 255, 255), anchor="mm",
                stroke_width=8, stroke_fill=OUTLINE + (255,))
        if a < 1:
            al = layer.getchannel("A").point(lambda v: int(v * a))
            layer.putalpha(al)
        img.alpha_composite(layer, (0, SUB_Y - 110))


def init_worker():
    _G["paper"] = make_paper()
    _G["blanket"] = blanket_sprite()


def render_frame(t):
    if "paper" not in _G:
        init_worker()
    ci = cut_index(t)
    arr = render_cut(ci, t)
    # 크로스페이드 (컷1->2 하드컷, 컷6->7 흰 전환은 제외)
    for b_i in (1, 2, 3, 4, 6):
        b = CUTS[b_i][1]
        if b - XFADE / 2 <= t < b + XFADE / 2:
            other = b_i + 1 if t < b else b_i
            w = seg(t, b - XFADE / 2, b + XFADE / 2)
            w = ease_io(w)
            arr2 = render_cut(other, t)
            arr = arr * (1 - w) + arr2 * w if other > b_i else arr2 * (1 - w) + arr * w
    # 루프: 마지막에 첫 컷 화면으로
    if t >= 31.72:
        w = ease_io(seg(t, 31.72, 31.95))
        arr = arr * (1 - w) + render_cut(0, 0.0) * w
    # 부드러운 흰 전환
    if FLASH_T <= t < 24.15:
        fa = 0.85 * (ease_io(seg(t, FLASH_T, 24.0)) if t < 24.0 else 1 - ease_io(seg(t, 24.0, 24.15)))
        arr = arr * (1 - fa) + np.array([255, 250, 240], np.float32) * fa
    arr = arr * _G["paper"]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")
    draw_subs(img, t)
    return img.convert("RGB").tobytes()


# ───────────────────────── 소리 (모두 직접 합성) ─────────────────────────

N = int(DUR * SR)


def fft_filter(x, lo=None, hi=None, order=2):
    n = len(x)
    nfft = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, nfft)
    f = np.fft.rfftfreq(nfft, 1 / SR)
    Hm = np.ones_like(f)
    if hi:
        Hm /= np.sqrt(1 + (f / hi) ** (2 * order))
    if lo:
        Hm /= np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** (2 * order))
    return np.fft.irfft(X * Hm, nfft)[:n]


def tv(dur):
    return np.arange(int(dur * SR)) / SR


class Mix:
    def __init__(self):
        self.L = np.zeros(N)
        self.R = np.zeros(N)

    def add(self, start, sig, vol=1.0, pan=0.0):
        i = int(round(start * SR))
        if i >= N:
            return
        if i < 0:
            sig = sig[-i:]
            i = 0
        j = min(N, i + len(sig))
        a = (pan + 1) * math.pi / 4
        self.L[i:j] += sig[: j - i] * vol * math.cos(a) * 1.414
        self.R[i:j] += sig[: j - i] * vol * math.sin(a) * 1.414

    def add_st(self, start, l, r, vol=1.0):
        i = int(round(start * SR))
        j = min(N, i + len(l))
        self.L[i:j] += l[: j - i] * vol
        self.R[i:j] += r[: j - i] * vol


RNG = np.random.default_rng(2026)


def noise(dur):
    return RNG.normal(0, 1, int(dur * SR))


def norm(x):
    m = np.abs(x).max()
    return x / m if m > 0 else x


def burst(dur, lo, hi, tau, order=2):
    n = fft_filter(noise(dur + 0.05), lo, hi, order)[: int(dur * SR)]
    return norm(n) * np.exp(-tv(dur) / tau)


def sweep(f0, f1, dur, shape_="lin"):
    t = tv(dur)
    f = f0 + (f1 - f0) * (t / dur)
    ph = 2 * np.pi * np.cumsum(f) / SR
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 0.6
    return np.sin(ph) * env


def rain_bed(lp, dur, seed):
    rng = np.random.default_rng(seed)
    out = []
    for ch in range(2):
        n = rng.normal(0, 1, int(dur * SR))
        n = fft_filter(n, 60, lp, order=1)
        # 굵은 빗방울 톡톡
        ticks = np.zeros_like(n)
        cnt = int(dur * 35)
        pos = rng.integers(0, len(n) - 400, cnt)
        tk = fft_filter(rng.normal(0, 1, 300), 1500, min(5000, lp * 3), 2) * np.exp(-np.arange(300) / 40)
        for p, v in zip(pos, rng.uniform(0.2, 1.0, cnt)):
            ticks[p:p + 300] += tk * v
        n = n / (np.std(n) + 1e-9) + ticks / (np.abs(tk).max() + 1e-9) * 0.9
        out.append(n)
    return out


def make_audio(path):
    m = Mix()
    # 빗소리 (바깥 2.5~6.5, 안 6.5~32)
    out_l, out_r = rain_bed(1500, 4.4, 1)
    env = np.ones(len(out_l))
    nfade = int(0.3 * SR)
    env[:int(0.02 * SR)] = np.linspace(0, 1, int(0.02 * SR))
    env[-nfade:] = np.linspace(1, 0, nfade)
    m.add_st(2.5, out_l * env, out_r * env, vol=0.12 * 0.33)
    in_dur = 32.0 - 6.4
    in_l, in_r = rain_bed(800, in_dur, 2)
    tt = tv(in_dur)
    env = np.clip(tt / 0.3, 0, 1)
    abs_t = tt + 6.4
    env *= np.clip((32.0 - abs_t) / 2.0, 0, 1) ** 1.5 * (abs_t < 30.0) + (abs_t >= 30.0) * np.clip((32.0 - abs_t) / 2.0, 0, 1) ** 1.5
    m.add_st(6.4, in_l * env, in_r * env, vol=0.08 * 0.33)
    # 숯불 타닥 (포아송)
    rng = np.random.default_rng(5)

    def crackles(t0, t1, rate, vol_lo, vol_hi, pan_spread=0.5, lp=None):
        n = rng.poisson((t1 - t0) * rate)
        for tt_ in np.sort(rng.uniform(t0, t1, n)):
            dur = rng.uniform(0.003, 0.008)
            c = burst(dur + 0.02, 1200, 9000 if lp is None else lp, rng.uniform(0.002, 0.006))
            m.add(tt_, c, vol=rng.uniform(vol_lo, vol_hi), pan=rng.uniform(-pan_spread, pan_spread))
            if rng.random() < 0.3:
                m.add(tt_ + rng.uniform(0.01, 0.04), c * 0.6, vol=rng.uniform(vol_lo, vol_hi) * 0.6,
                      pan=rng.uniform(-pan_spread, pan_spread))
    crackles(0.0, 2.5, 5, 0.08, 0.22)
    crackles(6.5, 15.0, 2, 0.04, 0.1, lp=4000)
    crackles(15.0, FAN_T0, 8, 0.1, 0.3, pan_spread=0.3)
    crackles(FAN_T0, FAN_T1, 13, 0.12, 0.3, pan_spread=0.3)
    crackles(FAN_T1, 27.5, 8, 0.1, 0.3, pan_spread=0.4)
    crackles(27.5, 32.0, 3, 0.05, 0.14, pan_spread=0.6)
    # 고구마 갈라지는 소리 + 김 쉬익
    for ts in (SPLIT1, SPLIT2):
        m.add(ts, burst(0.08, 2000, 6000, 0.02), vol=0.5)
        m.add(ts + 0.012, burst(0.06, 600, 2000, 0.015), vol=0.2)
        hiss = norm(fft_filter(noise(1.3), 3500, 10000, 2))[: int(1.2 * SR)]
        e = np.linspace(1, 0, len(hiss)) * np.clip(tv(1.2) / 0.05, 0, 1)
        m.add(ts, hiss * e, vol=0.15)
    # 발소리 (팬: 토리 위치)
    k = 0
    while WALK_T0 + 0.25 * k < WALK_T1:
        ts = WALK_T0 + 0.25 * k
        t60 = tv(0.06)
        step = (np.sin(2 * np.pi * 110 * t60) + 0.25 * norm(fft_filter(noise(0.06), None, 900, 2))) * np.exp(-t60 / 0.015)
        pan = clamp01((walk_x(ts) + 200) / 1280) * 1.4 - 0.7
        m.add(ts, step, vol=0.25, pan=pan)
        k += 1
    for i, ts in enumerate(SPLASH_T):
        pan = clamp01((PUDDLES[i][0] + 200) / 1280) * 1.4 - 0.7
        m.add(ts, burst(0.1, 1000, 3000, 0.035), vol=0.3, pan=pan)
        for j in range(4):
            m.add(ts + 0.08 + j * 0.05, burst(0.03, 2000, 5000, 0.008), vol=0.08, pan=pan)
    # 문 닫힘 (부드러운 나무 '톡') - 기획에 없던 작은 추가음
    tt_ = tv(0.15)
    m.add(DOOR_T + 0.3, np.sin(2 * np.pi * 170 * tt_) * np.exp(-tt_ / 0.03) * 0.8 + burst(0.15, 300, 1500, 0.01) * 0.4,
          vol=0.22, pan=-0.5)
    m.add(7.0, np.sin(2 * np.pi * 140 * tt_) * np.exp(-tt_ / 0.025), vol=0.14, pan=-0.3)   # 바구니 내려놓기
    # 몸 터는 소리
    sh = norm(fft_filter(noise(0.6), 1000, 4000, 2))
    tt_ = tv(0.6)
    am = (0.5 + 0.5 * np.sin(2 * np.pi * 6 * tt_ - np.pi / 2)) * np.sin(np.pi * tt_ / 0.6) ** 0.5
    m.add(SHAKE_T, sh * am, vol=0.3, pan=-0.2)
    for j in range(10):
        m.add(SHAKE_T + 0.3 + rng.uniform(0, 0.6), burst(0.02, 2000, 6000, 0.005), vol=0.06, pan=rng.uniform(-0.8, 0.8))
    # 물 첨벙 + 거품
    for ts in DIP_T:
        sp = burst(0.15, 500, 2500, 0.05)
        tt_ = tv(0.1)
        dr = np.sin(2 * np.pi * np.cumsum(300 - 150 * tt_ / 0.1) / SR) * np.exp(-tt_ / 0.04)
        m.add(ts, sp, vol=0.35)
        m.add(ts, dr, vol=0.2)
        for j in range(int(0.3 * 18)):                    # 문지르는 찰랑
            m.add(ts + 0.03 + j * 0.055, burst(0.05, 600, 2400, 0.02), vol=0.07, pan=rng.uniform(-0.2, 0.2))
    nb = int(3.6 * 8)
    for j in range(nb):
        ts = 11.0 + rng.uniform(0, 3.6)
        f = rng.uniform(800, 1400)
        tt_ = tv(0.03)
        b = np.sin(2 * np.pi * np.cumsum(f * (1 + 0.6 * tt_ / 0.03)) / SR) * np.sin(np.pi * tt_ / 0.03)
        m.add(ts, b, vol=0.08, pan=rng.uniform(-0.4, 0.4))
    # 부채 휘익
    k = 0
    while FAN_T0 + k / 3 < FAN_T1:
        w_ = norm(fft_filter(noise(0.25), 300, 1200, 2)) * np.sin(np.pi * tv(0.25) / 0.25)
        m.add(FAN_T0 + k / 3, w_, vol=0.2, pan=-0.3)
        k += 1
    # 내려놓기 툭
    for ts in LAND_T:
        tt_ = tv(0.08)
        m.add(ts, np.sin(2 * np.pi * 90 * tt_) * np.exp(-tt_ / 0.03) + burst(0.08, 1500, 6000, 0.004) * 0.5, vol=0.35)
    # 뒤집기: 집게 '찰칵' + 툭 (작은 추가음)
    for ts in FLIP_T:
        m.add(ts - 0.02, burst(0.03, 3000, 9000, 0.006), vol=0.1, pan=0.3)
        tt_ = tv(0.08)
        m.add(ts + 0.4, np.sin(2 * np.pi * 100 * tt_) * np.exp(-tt_ / 0.025), vol=0.22)
    # 띵
    tt_ = tv(0.6)
    ding = (np.sin(2 * np.pi * 1568 * tt_) + 0.3 * np.sin(2 * np.pi * 3136 * tt_)) * np.exp(-tt_ / 0.18)
    m.add(FLASH_T, ding, vol=0.2)
    # 미미 뿅, 호 불기, 냠, 하트 뿅뿅
    m.add(MIMI_T, sweep(400, 900, 0.12), vol=0.3, pan=0.4)
    for pan in (-0.3, 0.4):
        bl = norm(fft_filter(noise(0.4), 400, 2500, 2)) * np.sin(np.pi * tv(0.4) / 0.4) ** 1.5
        m.add(BLOW_T, bl, vol=0.08, pan=pan)
    tt_ = tv(0.06)
    m.add(BITE_T, np.sin(2 * np.pi * np.cumsum(260 - 100 * tt_ / 0.06) / SR) * np.exp(-tt_ / 0.02), vol=0.15)
    for k in range(6):
        m.add(HEART_T + 0.08 * k, sweep(600, 1200, 0.1), vol=0.18, pan=-0.3 if k < 3 else 0.4)
    sfx_L, sfx_R = m.L.copy(), m.R.copy()
    # 오르골
    mus = np.zeros(N)
    beat = 60 / 80
    nf = {"C3": 130.81, "G3": 196.0, "C5": 523.25, "D5": 587.33, "E5": 659.25, "G5": 783.99, "A5": 880.0}
    mel = ["E5", "G5", "A5", "G5", "E5", "D5", "C5", None, "D5", "E5", "G5", "E5", "D5", "C5", "C5", None]
    t0 = 2.5
    while t0 < DUR:
        for i, n_ in enumerate(mel):
            ts = t0 + i * beat
            if n_ and ts < DUR:
                tt_ = tv(min(2.5, DUR - ts))
                f = nf[n_]
                tone = (np.sin(2 * np.pi * f * tt_) + 0.3 * np.sin(2 * np.pi * 2 * f * tt_)
                        + 0.1 * np.sin(2 * np.pi * 3 * f * tt_)) * np.exp(-tt_ / 0.6) * np.clip(tt_ / 0.004, 0, 1)
                i0 = int(ts * SR)
                mus[i0:i0 + len(tone)] += tone[: N - i0] * 0.6
        for bar in range(4):
            for j, n_ in enumerate(("C3", "G3")):
                ts = t0 + bar * 4 * beat + j * 2 * beat
                if ts < DUR:
                    tt_ = tv(min(1.6, DUR - ts))
                    f = nf[n_]
                    tone = (np.sin(2 * np.pi * f * tt_) + 0.2 * np.sin(2 * np.pi * 2 * f * tt_)) * np.exp(-tt_ / 0.9) \
                        * np.clip(tt_ / 0.01, 0, 1)
                    i0 = int(ts * SR)
                    mus[i0:i0 + len(tone)] += tone[: N - i0] * 0.4
        t0 += 16 * beat
    # 잔향 (지수 감쇠 잡음 IR, FFT 컨볼루션)
    irn = int(1.4 * SR)
    ir = np.random.default_rng(3).normal(0, 1, irn) * np.exp(-np.arange(irn) / SR / 0.35)
    ir = fft_filter(ir, None, 5000, 1)
    ir /= np.sqrt(np.sum(ir ** 2))
    nfft = 1 << (N + irn).bit_length()
    wet = np.fft.irfft(np.fft.rfft(mus, nfft) * np.fft.rfft(ir, nfft), nfft)[:N]
    mus = mus + 0.35 * wet
    t_all = np.arange(N) / SR
    menv = np.clip((t_all - 2.5) / 1.0, 0, 1) * np.clip((32.0 - t_all) / 1.0, 0, 1)
    mus = mus / np.abs(mus).max() * menv
    MUSIC_VOL = 0.05
    L = sfx_L + mus * MUSIC_VOL
    R = sfx_R + mus * MUSIC_VOL
    # 비교용 음량 (효과음 대비 음악)
    write_wav(path, np.stack([sfx_L, sfx_R], 1))
    sfx_lufs = measure_lufs(path)
    write_wav(path, np.stack([mus * MUSIC_VOL, mus * MUSIC_VOL], 1))
    mus_lufs = measure_lufs(path)
    print(f"  효과음 {sfx_lufs:.1f} LUFS / 음악 {mus_lufs:.1f} LUFS (믹스 전 상대값)")
    buf = np.stack([L, R], 1)
    for _ in range(3):
        write_wav(path, buf)
        lufs = measure_lufs(path)
        buf *= 10 ** ((-14.0 - lufs) / 20)
        lim, knee = 10 ** (-1.6 / 20), 10 ** (-6 / 20)
        a = np.abs(buf)
        over = a > knee
        buf[over] = np.sign(buf[over]) * (knee + (lim - knee) * np.tanh((a[over] - knee) / (lim - knee)))
    write_wav(path, buf)
    print(f"  최종 음량 {measure_lufs(path):.2f} LUFS, 피크 {20 * math.log10(np.abs(buf).max()):.2f} dBFS")


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


# ───────────────────────── 합치기 ─────────────────────────

def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        prev = OUT_DIR / "preview"
        prev.mkdir(exist_ok=True)
        init_worker()
        for a in sys.argv[2:]:
            t = float(a)
            Image.frombytes("RGB", (W, H), render_frame(t)).save(prev / f"p{t:05.2f}.png")
            print("saved", prev / f"p{t:05.2f}.png")
        return
    wav = OUT_DIR / "audio.wav"
    out = OUT_DIR / f"{NAME}.mp4"
    make_audio(wav)
    if len(sys.argv) > 1 and sys.argv[1] == "--audio-only":
        return
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav), "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total = int(DUR * FPS)
    with Pool(8, initializer=init_worker) as pool:
        for f, data in enumerate(pool.imap(render_frame, [k / FPS for k in range(total)], chunksize=4)):
            proc.stdin.write(data)
            if f % 120 == 0:
                print(f"  {f}/{total} 프레임", flush=True)
    proc.stdin.close()
    proc.wait()
    wav.unlink()
    print(f"완성: {out}")


if __name__ == "__main__":
    main()
