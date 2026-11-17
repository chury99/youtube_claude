#!/usr/bin/env python3
"""
유아 협동 동요 쇼츠 "네모랑 동글이 블록 쌓기" (38초) — AI 도구 없이 코드로 그리고 작곡한다.

원본 기획: prompts/20261116_1437_gWB1uGe7RMg.txt
  0~2초   인트로: 빨간 블록이 '보잉' 떨어지고 네모(왼쪽)·동글이(오른쪽) 등장
  2~10초  1절: 네모 혼자 쌓기 -> 흔들흔들 -> 블록이 풀밭에 퐁퐁 -> 네모 웃음
  10~18초 2절: 동글이 혼자 -> 데굴데굴 굴러감 -> 웃음
  18~26초 3절: 네모가 바닥 블록을 받치고 동글이가 얹어서 탑이 쑥쑥
  26~34초 4절: 꼭대기에 별, 둘이 옆구리 하이파이브
  34~38초 아웃트로: 짝! 짝! 무지개 + "함께하면 최고!"

템포 120 BPM(1박 0.5초). 가사 자막의 음절 하이라이트 시각은 멜로디 음표 시각과
같은 데이터(SONG)에서 계산하므로 박자와 정확히 맞는다.

필요: numpy, Pillow, ffmpeg
사용: .venv/bin/python videos/20261116_1437_gWB1uGe7RMg/make_video.py
"""

import math
import re
import subprocess
import wave
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent
NAME = "20261116_1437_gWB1uGe7RMg"
W, H, FPS, DUR = 1080, 1920, 30, 38.0
S = 2                      # 2배로 그린 뒤 줄여서 테두리를 부드럽게
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
SR = 48000
BEAT = 0.5

GROUND = 1380              # 캐릭터·탑이 서는 높이 (아래 25% 쇼츠 UI 영역보다 위)
CH = 240                   # 캐릭터 크기
BW, BH = 160, 100          # 블록 크기
TOWER_X = 540

NAVY = (35, 46, 94)
SKY_TOP, SKY_BOTTOM = (0x9E, 0xDC, 0xFF), (0xD8, 0xF3, 0xFF)
GRASS = (0x8E, 0xDB, 0x6A)
NEMO_C, NEMO_CHEEK = (0xFF, 0xD2, 0x3F), (0xFF, 0x9E, 0xB5)
DONG_C, DONG_CHEEK = (0xFF, 0x7E, 0xB6), (0xFF, 0xB3, 0x6B)
RED, BLUE, GREEN, PURPLE = (0xFF, 0x5A, 0x5A), (0x4D, 0xA3, 0xFF), (0x5C, 0xD6, 0x5C), (0xB0, 0x7C, 0xFF)
STAR_C = (0xFF, 0xE4, 0x4D)
HILITE = (0xFF, 0xE4, 0x4D)   # 노래방 하이라이트 색

# ───────────────────────── 노래 (멜로디 + 가사를 한곳에서 정의) ─────────────────────────
A_LINE = [("C4", 1), ("E4", 1), ("G4", 1), ("G4", 1), ("A4", 1), ("G4", 1), ("E4", 2)]
B_LINE = [("D4", 1), ("E4", 1), ("F4", 1), ("A4", 1), ("G4", 1), ("E4", 1), ("C4", 2)]
B_LAST = B_LINE[:-1] + [("C5", 2)]          # 4절 마지막 음만 C5로 올려 '성공' 느낌
OUTRO = [("C5", 1), ("r", 1), ("C5", 1), ("r", 1), ("G4", 1), ("E4", 1), ("C4", 2)]

VERSES = [
    ("네모가 혼자 쌓아", "Nemo stacks alone", "흔들 흔들 우르르", "wobble wobble, tumble down"),
    ("동글이 혼자 쌓아", "Dongle stacks alone", "데굴 데굴 굴러가", "roly-poly, rolling away"),
    ("둘이 함께 쌓아요", "Let's stack together", "영차 영차 쑥쑥쑥", "heave-ho, up up up"),
    # 기획안의 "함께 하니"는 '함께하다'가 한 단어라 붙여 썼다 (음절 수는 7 그대로)
    ("꼭대기에 반짝별", "A twinkle star on top", "함께하니 최고야", "together we're the best"),
]
PUNCT = "!?.,"


def syllable_slots(text):
    """글자마다 몇 번째 음절인지 (공백 -1, 문장부호는 앞 음절에 붙음)"""
    idx, out = -1, []
    for ch in text:
        if ch == " ":
            out.append(-1)
        elif ch in PUNCT:
            out.append(max(idx, 0))
        else:
            idx += 1
            out.append(idx)
    return out, idx + 1


def build_song():
    """notes: (시작초, 음, 박수), lines: 자막 줄 정보 (음절 시작 시각 포함)"""
    notes, lines = [], []
    for i, n in enumerate(["C5", "G4", "E4", "G4"]):          # 인트로 실로폰
        notes.append((i * BEAT, n, 1))

    def add_line(t0, pattern, kor, eng, show, slot):
        times, t = [], t0
        for n, beats in pattern:
            if n != "r":
                notes.append((t, n, beats))
                times.append(t)
            t += beats * BEAT
        _, count = syllable_slots(kor)
        assert count == len(times), f"음절 수({count})와 음표 수({len(times)})가 다름: {kor}"
        lines.append(dict(kor=kor, eng=eng, times=times, show=show, slot=slot, start=t0))

    for v, (ka, ea, kb, eb) in enumerate(VERSES):
        base = 2 + 8 * v
        show = (0.0 if v == 0 else base - 0.4, base + 8 - 0.4)
        add_line(base, A_LINE, ka, ea, show, 0)
        add_line(base + 4, B_LAST if v == 3 else B_LINE, kb, eb, show, 1)
    add_line(34.0, OUTRO, "짝! 짝! 최고야!", "Clap! Clap! The best!", (33.6, DUR + 1), 0)
    return notes, lines


NOTES, LINES = build_song()


# ───────────────────────── 도우미 ─────────────────────────

def clamp01(x):
    return max(0.0, min(1.0, x))


def ease_io(u):
    u = clamp01(u)
    return u * u * (3 - 2 * u)


def ease_out_back(u):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2


def bump(d, length):
    """0~length 동안 0 -> 1 -> 0"""
    return math.sin(math.pi * d / length) if 0 <= d < length else 0.0


def P(pts):
    return [v * S for pt in pts for v in pt]


def mix(c1, c2, a):
    return tuple(int(round(x + (y - x) * a)) for x, y in zip(c1, c2))


def sky_at(y):
    return mix(SKY_TOP, SKY_BOTTOM, clamp01(y / H))


def ellipse_pts(cx, cy, rx, ry, n=40, a0=0.0, a1=360.0):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * k / (n - 1))),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * k / (n - 1)))) for k in range(n)]


def rrect_pts(hw, hh, r, n=7):
    """원점 중심의 둥근 사각형 꼭짓점 목록"""
    r = min(r, hw, hh)
    pts = []
    for cx, cy, a0 in [(hw - r, hh - r, 0), (-hw + r, hh - r, 90), (-hw + r, -hh + r, 180), (hw - r, -hh + r, 270)]:
        for k in range(n):
            a = math.radians(a0 + 90 * k / (n - 1))
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def xform(pts, cx, cy, rot=0.0, sx=1.0, sy=1.0):
    """회전 -> 늘어남 -> 이동 (늘어남은 화면 기준이라 땅에 눌린 느낌이 유지됨)"""
    a = math.radians(rot)
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + (x * ca - y * sa) * sx, cy + (x * sa + y * ca) * sy) for x, y in pts]


# ───────────────────────── 캐릭터 움직임 ─────────────────────────

class Actor:
    def __init__(self, x0, hops, rolls=(), hold=(), giggle=(), blinks=(), side_bump=(), lean=None):
        self.x0, self.hops, self.rolls = x0, list(hops), list(rolls)
        self.hold, self.giggle, self.blinks = hold, giggle, blinks
        self.side_bump, self.lean = side_bump, lean

    def state(self, t):
        x, yoff, rot, moving = self.x0, 0.0, 0.0, False
        for t0, t1, x0, x1, h in self.hops:
            if t >= t1:
                x = x1
            elif t >= t0:
                u = (t - t0) / (t1 - t0)
                x, yoff, moving = x0 + (x1 - x0) * ease_io(u), -h * 4 * u * (1 - u), True
                break
            else:
                break
        last_rot_end = 0.0
        for t0, t1, x0, x1, r0, r1 in self.rolls:
            if t0 <= t < t1:
                u = ease_io((t - t0) / (t1 - t0))
                x, rot, moving = x0 + (x1 - x0) * u, r0 + (r1 - r0) * u, True
            elif t >= t1:
                last_rot_end = r1
        if not moving:
            rot = last_rot_end % 360   # 롤은 항상 360도 단위로 끝나 얼굴이 바로 선다

        sx = sy = 1.0
        happy = any(a <= t < b for a, b in self.giggle)
        in_hold = any(a <= t < b for a, b in self.hold)
        if not moving:
            if happy:      # 깔깔 웃을 때는 잘게 통통
                yoff = -12 * abs(math.sin(math.pi * t / 0.25))
            elif not in_hold:   # 박자마다 1.0 -> 1.08 -> 1.0 바운스
                p = bump(t % BEAT, 0.25)
                sy, sx = 1 + 0.08 * p, 1 + 0.03 * p
        # 착지 찌그러짐
        for t0, t1, *_ in self.hops:
            q = bump(t - t1 + 0.02, 0.16)
            if q:
                if t1 in self.side_bump:   # 옆구리 하이파이브: 옆으로 눌림
                    sx, sy = sx * (1 - 0.12 * q), sy * (1 + 0.07 * q)
                else:
                    sx, sy = sx * (1 + 0.14 * q), sy * (1 - 0.18 * q)
        if self.lean:
            a, b, ang = self.lean
            rot += ang * ease_io((t - a) / (b - a)) if t >= a else 0.0
        blink = any(0 <= t - bt < 0.12 for bt in self.blinks)
        return dict(x=x, by=GROUND + yoff, sx=sx, sy=sy, rot=rot, happy=happy, blink=blink, air=-yoff)


def beat_hops(x, start, end, h=40):
    """start~end 사이 박마다 제자리 통통 (착지가 박에 맞음)"""
    out, t = [], start
    while t <= end + 1e-6:
        out.append((t - 0.35, t, x, x, h))
        t += BEAT
    return out


def toss_hops(x, lands, h=70):
    return [(L - 0.5, L - 0.15, x, x, h) for L in lands]


NEMO_LANDS = [3.0, 4.0, 5.0]                    # 1절: 네모가 얹는 블록 착지 시각
TOWER_LANDS = [22.0, 23.0, 24.0, 24.5, 25.0]    # 3절: 탑에 블록이 올라가는 시각

NEMO = Actor(
    x0=40,
    hops=[(0.5, 1.0, 40, 160, 110), (1.0, 1.5, 160, 280, 110)]
    + toss_hops(280, NEMO_LANDS, 80)
    + [(18.5, 19.0, 280, 340, 60)]
    + [(28.5, 29.0, 340, 380, 90), (29.5, 30.0, 380, 415, 90), (30.65, 31.0, 415, 395, 35)]
    + beat_hops(395, 31.5, 33.5, 35)
    + [(33.65, 34.0, 395, 395, 70), (34.65, 35.0, 395, 395, 70)],
    hold=[(19.0, 26.0)],
    giggle=[(9.4, 10.0), (17.0, 18.0), (30.0, 31.0), (36.0, 39.0)],
    blinks=[6.9, 9.15, 12.6, 20.6, 27.3, 33.1],
    side_bump=(30.0,),
    lean=(36.2, 36.8, 6.0),
)

DONGLE = Actor(
    x0=1030,
    hops=[(11.0, 11.5, 820, 770, 90), (12.0, 12.5, 770, 720, 90), (13.0, 13.5, 720, 720, 150)]
    + [(19.0, 19.5, 720, 740, 60)]
    + toss_hops(740, TOWER_LANDS, 70)
    + [(28.5, 29.0, 740, 700, 90), (29.5, 30.0, 700, 665, 90), (30.65, 31.0, 665, 685, 35)]
    + beat_hops(685, 31.5, 33.5, 35)
    + [(33.65, 34.0, 685, 685, 70), (34.65, 35.0, 685, 685, 70)],
    rolls=[(0.4, 1.5, 1030, 820, 0, -360), (14.0, 15.5, 720, 860, 0, 360), (15.5, 17.0, 860, 720, 360, 0)],
    giggle=[(9.4, 10.0), (17.0, 18.0), (30.0, 31.0), (36.0, 39.0)],
    blinks=[5.6, 9.2, 19.8, 27.0, 32.4],
    side_bump=(30.0,),
    lean=(36.2, 36.8, -6.0),
)


def nemo_state(t):
    st = NEMO.state(t)
    if 19.0 <= t < 26.0:      # 바닥 블록을 받치는 중: 블록이 올라올 때마다 살짝 눌림
        for L in TOWER_LANDS:
            q = bump(t - L, 0.2)
            if q:
                st["sx"], st["sy"] = 1 + 0.06 * q, 1 - 0.08 * q
    return st


def dongle_state(t):
    st = DONGLE.state(t)
    # 인트로 롤(1030->820) 이후 첫 hop(11초) 전까지는 820에 머문다
    if 1.5 <= t < 11.0:
        st["x"] = 820
    if t < 0.4:
        st["x"] = 1030
    # 2절 굴러가기(14~17초) 이후는 720 → hops 목록이 이어받는다
    if 17.0 <= t < 19.0:
        st["x"] = 720
    return st


def look_target(who, t, st):
    """눈동자 방향 (-1~1). None이면 정면"""
    if t >= 34.0:
        return (0.0, 0.0)
    if 26.0 <= t < 28.4:
        return (0.2 if who == "nemo" else -0.2, -1.0)        # 별 올려다보기
    if 10.5 <= t < 14.0 and who == "dongle":
        return (-0.2, -1.0)                                  # 머리 위 블록 보기
    if 5.0 <= t < 9.2:                                       # 흔들리는 탑 보기
        wob = math.sin(2 * math.pi * (t - 6.0) / 1.0) if t >= 6 else 0
        return (0.5 * wob + (0.6 if who == "nemo" else -0.6), -0.5)
    if 30.0 <= t < 31.0:
        return (1.0 if who == "nemo" else -1.0, 0.0)         # 서로 마주 보기
    return (0.55 if who == "nemo" else -0.55, 0.1)           # 기본: 가운데 쪽


def head_anchor(state_fn):
    def f(t):
        st = state_fn(t)
        return (st["x"], st["by"] - CH * st["sy"] - BH / 2)
    return f


NEMO_HEAD = head_anchor(nemo_state)
DONG_HEAD = head_anchor(dongle_state)


# ───────────────────────── 블록 ─────────────────────────

def stack_angle(t):
    """1절 탑 기울기 (회전 중심은 맨 아래 블록의 바닥 가운데)"""
    if t < 5.0:
        return 0.0
    if t < 6.0:
        return 3.0 * ease_io(t - 5.0)
    if t < 8.0:
        amp = 4 + 5 * (t - 6.0) / 2.0          # 박마다 왼쪽/오른쪽으로 한 번씩
        return 3.0 * (1 - (t - 6) / 2) + amp * math.sin(2 * math.pi * (t - 6.0) / 1.0)
    if t < 9.5:
        return 9.0 * math.exp(-(t - 8.0) * 3.0) * math.sin(2 * math.pi * (t - 8.0) / 0.6)
    return 0.0


def slot_pos(k):
    def f(t):
        a = math.radians(stack_angle(t))
        dy = -(BH / 2 + BH * k)
        return (TOWER_X - dy * math.sin(a), GROUND + dy * math.cos(a))
    return f


G_PURPLE, G_GREEN, G_BLUE = (650, 1590), (470, 1605), (560, 1720)   # 두 캐릭터 사이 앞쪽 풀밭
G_RED2, G_BLUE2 = (870, 1600), (790, 1730)


def placed_by(anchor, L, slot):
    """머리 위에 뿅 나타남 -> 함께 점프 -> 탑 위로 톡"""
    return [("pop", L - 0.8, L - 0.55, anchor), ("ride", L - 0.55, L - 0.33, anchor),
            ("arc", L - 0.33, L, anchor, slot_pos(slot), 110, 0, 0)]


def picked_by_dongle(src, L, slot):
    """땅의 블록이 동글이 머리로 폴짝 -> 탑 위로 톡"""
    return [("arc", L - 0.8, L - 0.55, src, DONG_HEAD, 140, 0, 0), ("ride", L - 0.55, L - 0.33, DONG_HEAD),
            ("arc", L - 0.33, L, DONG_HEAD, slot_pos(slot), 110, 0, 0)]


BLOCKS = [
    (RED, [("drop", 0.0, 0.5, (540, 640), slot_pos(0)), ("arc", 0.5, 1.0, slot_pos(0), slot_pos(0), 150, 0, 0),
           ("arc", 1.0, 1.25, slot_pos(0), slot_pos(0), 30, 0, 0), ("stack", 1.25, 99, 0)]),
    (BLUE, placed_by(NEMO_HEAD, 3.0, 1) + [
        ("stack", 3.0, 8.5, 1), ("arc", 8.5, 9.0, slot_pos(1), G_BLUE, 60, None, -180),
        ("ground", 9.0, 10.0, G_BLUE), ("arc", 10.0, 10.5, G_BLUE, DONG_HEAD, 160, 0, 0),
        ("ride", 10.5, 14.0, DONG_HEAD), ("arc", 14.0, 14.25, DONG_HEAD, (490, 1050), 30, 0, -60),   # 머리에서 왼쪽으로 미끄러진 뒤
        ("arc", 14.25, 14.55, (490, 1050), G_BLUE, 0, -60, -180),  # 캐릭터와 떨어진 풀밭에 톡
        ("ground", 14.55, 21.2, G_BLUE)] + picked_by_dongle(G_BLUE, 22.0, 1) + [("stack", 22.0, 99, 1)]),
    (GREEN, placed_by(NEMO_HEAD, 4.0, 2) + [
        ("stack", 4.0, 8.25, 2), ("arc", 8.25, 8.75, slot_pos(2), G_GREEN, 60, None, -180),
        ("ground", 8.75, 22.2, G_GREEN)] + picked_by_dongle(G_GREEN, 23.0, 2) + [("stack", 23.0, 99, 2)]),
    (PURPLE, placed_by(NEMO_HEAD, 5.0, 3) + [
        ("stack", 5.0, 8.0, 3), ("arc", 8.0, 8.5, slot_pos(3), G_PURPLE, 60, None, 180),
        ("ground", 8.5, 23.2, G_PURPLE)] + picked_by_dongle(G_PURPLE, 24.0, 3) + [("stack", 24.0, 99, 3)]),
    (RED, [("drop", 19.4, 20.0, (G_RED2[0], 600), G_RED2), ("ground", 20.0, 23.7, G_RED2)]
     + picked_by_dongle(G_RED2, 24.5, 4) + [("stack", 24.5, 99, 4)]),
    (BLUE, [("drop", 20.4, 21.0, (G_BLUE2[0], 600), G_BLUE2), ("ground", 21.0, 24.2, G_BLUE2)]
     + picked_by_dongle(G_BLUE2, 25.0, 5) + [("stack", 25.0, 99, 5)]),
]


def _pt(v, t):
    return v(t) if callable(v) else v


def block_state(phases, t):
    """(x, y, 각도, sx, sy, 크기, 탑에 있음?) 또는 None(아직 안 보임)"""
    if t < phases[0][1]:
        return None
    prev = None
    for i, ph in enumerate(phases):
        kind, t0, t1 = ph[0], ph[1], ph[2]
        if t < t1 or i == len(phases) - 1:
            break
        prev = ph
    sq = 0.0
    if prev and prev[0] in ("arc", "drop") and kind in ("stack", "ground", "ride", "arc"):
        sq = bump(t - t0, 0.16)
    sx, sy = 1 + 0.14 * sq, 1 - 0.2 * sq
    if kind == "pop":
        u = clamp01((t - t0) / (t1 - t0))
        x, y = ph[3](t)
        return (x, y, 0.0, 1, 1, max(ease_out_back(u), 0.01), False)
    if kind == "ride":
        x, y = ph[3](t)
        return (x, y, 0.0, sx, sy, 1, False)
    if kind == "stack":
        x, y = slot_pos(ph[3])(t)
        return (x, y, stack_angle(t), sx, sy, 1, True)
    if kind == "ground":
        x, y = ph[3]
        y -= 22 * bump(t - t0, 0.28)          # 풀밭에 퐁 튀었다가 멈춤
        return (x, y, 0.0, sx, sy, 1, False)
    if kind == "drop":
        u = clamp01((t - t0) / (t1 - t0))
        x0, y0 = _pt(ph[3], t0)
        x1, y1 = _pt(ph[4], t1)
        pop = 1.0 if t0 == 0.0 else max(ease_out_back(clamp01(u / 0.3)), 0.01)   # 하늘에서 뿅 나타남 (자막 아래에서)
        return (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u * u, 0.0, 0.94, 1.08, pop, False)
    if kind == "arc":
        _, t0, t1, src, dst, h, a0, a1 = ph
        u = clamp01((t - t0) / (t1 - t0))
        x0, y0 = _pt(src, t0)
        x1, y1 = _pt(dst, t1)
        if a0 is None:
            a0 = stack_angle(t0)
        x = x0 + (x1 - x0) * u
        y = y0 + (y1 - y0) * u - h * 4 * u * (1 - u)
        return (x, y, a0 + (a1 - a0) * ease_io(u), sx, sy, 1, False)
    return None


# ───────────────────────── 그리기 ─────────────────────────

def make_sky():
    top, bottom = np.array(SKY_TOP, float), np.array(SKY_BOTTOM, float)
    g = np.linspace(0, 1, H * S)[:, None]
    col = (top * (1 - g) + bottom * g).astype(np.uint8)
    return Image.fromarray(np.repeat(col[:, None, :], W * S, axis=1), "RGB")


def draw_cloud(d, x, y, s):
    for dx, dy, r in [(-75, 12, 55), (0, -18, 78), (78, 12, 58)]:
        d.ellipse(P([(x + (dx - r) * s, y + (dy - r) * s), (x + (dx + r) * s, y + (dy + r) * s)]), fill=(255, 255, 255))
    d.rounded_rectangle(P([(x - 75 * s, y + 10 * s), (x + 78 * s, y + 68 * s)]), radius=28 * s * S, fill=(255, 255, 255))


def draw_hill(d):
    d.ellipse(P([(-520, 1290), (1600, 2500)]), fill=GRASS)
    d.ellipse(P([(-300, 1480), (1380, 2600)]), fill=(0x84, 0xD3, 0x60))
    for x, y, c in [(70, 1440, (255, 255, 255)), (1010, 1470, (255, 240, 120)),
                    (110, 1800, (255, 170, 200)), (990, 1860, (255, 255, 255))]:
        for k in range(5):
            a = 2 * math.pi * k / 5
            px, py = x + 14 * math.cos(a), y + 14 * math.sin(a)
            d.ellipse(P([(px - 10, py - 10), (px + 10, py + 10)]), fill=c)
        d.ellipse(P([(x - 8, y - 8), (x + 8, y + 8)]), fill=(255, 196, 60))


def draw_shadow(d, x, y, w, air):
    k = 1 - 0.55 * clamp01(air / 400)
    d.ellipse(P([(x - w * k, y - 14 * k), (x + w * k, y + 14 * k)]), fill=(0x74, 0xC0, 0x55))


def draw_block(d, color, x, y, ang, sx, sy, scale):
    hw, hh = BW / 2 * scale, BH / 2 * scale
    dark = mix(color, NAVY, 0.45)
    body = xform(rrect_pts(hw, hh, 20 * scale), x, y, ang, sx, sy)
    d.polygon(P(body), fill=color, outline=dark, width=5 * S)
    shine = xform([(px, py - hh * 0.52) for px, py in rrect_pts(hw * 0.7, hh * 0.16, 8 * scale)], x, y, ang, sx, sy)
    d.polygon(P(shine), fill=mix(color, (255, 255, 255), 0.45))


def draw_character(d, kind, st, look):
    x, by, sx, sy, rot = st["x"], st["by"], st["sx"], st["sy"], st["rot"]
    cx, cy = x, by - CH / 2 * sy
    half = CH / 2
    if kind == "nemo":
        color, cheek, shine_c = NEMO_C, NEMO_CHEEK, (255, 236, 160)
        body = rrect_pts(half, half, 40)
    else:
        color, cheek, shine_c = DONG_C, DONG_CHEEK, (255, 190, 222)
        body = ellipse_pts(0, 0, half, half, 72)

    def T(pts):
        return P(xform(pts, cx, cy, rot, sx, sy))

    d.polygon(T(body), fill=color, outline=mix(color, NAVY, 0.55), width=6 * S)
    d.polygon(T(ellipse_pts(-58, -70, 22, 12, 24)), fill=shine_c)
    for side in (-1, 1):
        d.polygon(T(ellipse_pts(side * 80, 36, 22, 15, 24)), fill=cheek)
    lx, ly = look
    for side in (-1, 1):
        ex, ey = side * 46, -18
        if st["happy"]:      # ^ ^ 웃는 눈
            arc = ellipse_pts(ex, ey + 12, 24, 22, 14, 200, 340)
            d.line(T(arc), fill=NAVY, width=9 * S, joint="curve")
        elif st["blink"]:
            arc = ellipse_pts(ex, ey - 10, 24, 14, 12, 30, 150)
            d.line(T(arc), fill=NAVY, width=8 * S, joint="curve")
        else:
            d.polygon(T(ellipse_pts(ex, ey, 30, 38, 32)), fill=(255, 255, 255), outline=mix((255, 255, 255), NAVY, 0.35), width=3 * S)
            px, py = ex + lx * 10, ey + ly * 14
            d.polygon(T(ellipse_pts(px, py, 18, 20, 24)), fill=(30, 30, 40))
            d.polygon(T(ellipse_pts(px - 6, py - 8, 6, 6, 12)), fill=(255, 255, 255))
    if st["happy"]:          # 활짝 웃는 입
        mouth = ellipse_pts(0, 30, 30, 30, 20, 0, 180)
        d.polygon(T(mouth), fill=(205, 70, 95), outline=NAVY, width=4 * S)
        d.polygon(T(ellipse_pts(0, 48, 13, 8, 16)), fill=(255, 140, 160))
    else:
        d.line(T(ellipse_pts(0, 28, 26, 20, 16, 20, 160)), fill=NAVY, width=8 * S, joint="curve")


def star_pts(R, r_in=0.46):
    pts = []
    for k in range(10):
        a = math.radians(-90 + 36 * k)
        rad = R if k % 2 == 0 else R * r_in
        pts.append((rad * math.cos(a), rad * math.sin(a)))
    return pts


STAR_T = 26.0


def star_scale(t):
    if t < STAR_T:
        return 0.0
    u = t - STAR_T
    if u < 0.5:
        return 1.2 * math.sin(math.pi / 2 * u / 0.5)
    if u < 0.8:
        return 1.2 - 0.2 * ease_io((u - 0.5) / 0.3)
    return 1.0


def draw_star(d, t):
    s = star_scale(t)
    if s <= 0.01:
        return
    R = 90 * s
    cx, cy = TOWER_X, GROUND - 6 * BH - 100
    # 고정된 은은한 빛 (점멸 없음): 하늘색 -> 연노랑 동심원
    base = sky_at(cy)
    for k, rr in enumerate([1.4, 1.28, 1.17, 1.07]):
        c = mix(base, (255, 248, 200), 0.18 + 0.14 * k)
        d.ellipse(P([(cx - R * rr, cy - R * rr), (cx + R * rr, cy + R * rr)]), fill=c)
    rot = 15 * (t - STAR_T)
    pts = xform(star_pts(R), cx, cy, rot)
    flat = P(pts)
    d.line(flat + flat[:2], fill=(240, 170, 40), width=int(16 * s * S) + 1, joint="curve")
    d.polygon(flat, fill=(240, 170, 40))
    d.line(flat + flat[:2], fill=STAR_C, width=int(8 * s * S) + 1, joint="curve")
    d.polygon(flat, fill=STAR_C)
    d.polygon(P(xform(ellipse_pts(-22 * s, -24 * s, 13 * s, 9 * s, 16), cx, cy, rot)), fill=(255, 250, 215))


def draw_twinkle(d, x, y, r, color):
    pts = []
    for k in range(8):
        a = math.pi / 4 * k
        rad = r if k % 2 == 0 else r * 0.3
        pts.append((x + rad * math.cos(a), y + rad * math.sin(a)))
    d.polygon(P(pts), fill=color)


def draw_sparkles(d, t):
    """하이파이브 순간 작은 반짝이가 퍼짐 (밝기 번쩍임 없이 움직임만)"""
    dt = t - 30.0
    if not 0 <= dt < 0.9:
        return
    ox, oy = 540, GROUND - 190
    cols = [(255, 240, 120), (255, 255, 255), (255, 170, 210)]
    for k in range(8):
        a = math.radians(-90 + 360 * k / 8 + 22)
        dist = 60 + 170 * (1 - (1 - dt / 0.9) ** 2)
        r = 26 * (1 - dt / 0.9)
        draw_twinkle(d, ox + dist * math.cos(a), oy + dist * math.sin(a) * 0.8, r, cols[k % 3])


RAINBOW_T = 34.0
RAINBOW_COLORS = [(255, 170, 170), (255, 205, 150), (255, 240, 160), (180, 235, 170), (165, 210, 255), (200, 180, 255)]


def draw_rainbow(d, scale=1.0):
    cx, cy, outer, band = 540, 1340, 660, 34
    for i, c in enumerate(RAINBOW_COLORS):
        r = outer - i * band
        d.arc(P([(cx - r, cy - r), (cx + r, cy + r)]), 180, 360, fill=c, width=band * S + 2)


_FONT_CACHE = {}


def font(size, bold=14):
    key = (int(size), bold)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(FONT, int(size), index=bold)
    return _FONT_CACHE[key]


def draw_lyric_line(d, line, t, y, size):
    text = line["kor"]
    slots, _ = syllable_slots(text)
    f = font(size * S)
    total = f.getlength(text)
    x0 = 540 * S - total / 2
    for i, ch in enumerate(text):
        k = slots[i]
        if k < 0:
            continue
        onset = line["times"][k]
        sung = t >= onset
        sc = 1.0
        if sung and ch not in PUNCT:
            sc = 1 + 0.18 * bump(t - onset, 0.25)
        cx = x0 + f.getlength(text[:i]) + f.getlength(ch) / 2
        ff = font(size * S * sc) if sc != 1.0 else f
        d.text((cx, y * S), ch, font=ff, anchor="mm", fill=HILITE if sung else (255, 255, 255),
               stroke_width=int(10 * S * sc), stroke_fill=NAVY)


def draw_lyrics(d, t):
    active = [ln for ln in LINES if ln["show"][0] <= t < ln["show"][1]]
    if not active:
        return
    if len(active) == 1:          # 아웃트로 한 줄
        ln = active[0]
        draw_lyric_line(d, ln, t, 280, 96)
        d.text((540 * S, 372 * S), ln["eng"], font=font(48 * S, 6), anchor="mm", fill=(255, 255, 255),
               stroke_width=6 * S, stroke_fill=NAVY)
        return
    a, b = active
    draw_lyric_line(d, a, t, 300, 92)
    draw_lyric_line(d, b, t, 412, 92)
    cur = b if t >= b["start"] - 0.3 else a
    d.text((540 * S, 506 * S), cur["eng"], font=font(50 * S, 6), anchor="mm", fill=(255, 255, 255),
           stroke_width=6 * S, stroke_fill=NAVY)


def draw_banner(d, t):
    if t < 36.0:
        return
    u = clamp01((t - 36.0) / 0.4)
    sc = max(ease_out_back(u), 0.01) * (1 + 0.03 * bump(t % BEAT, 0.25) if u >= 1 else 1)
    f = font(100 * S * sc)
    text = "함께하면 최고!"
    # 테두리는 한 겹만 (두 겹으로 그리면 글자 속 빈 공간에 남색 점이 남음)
    d.text((540 * S, 476 * S), text, font=f, anchor="mm", fill=(255, 111, 168),
           stroke_width=int(9 * S * sc), stroke_fill=NAVY)


_G = {}


def _init_worker():
    _G["sky"] = make_sky()
    rb = Image.new("RGB", (W * S, H * S), (0, 0, 0))
    mask = Image.new("L", (W * S, H * S), 0)
    draw_rainbow(ImageDraw.Draw(rb))
    md = ImageDraw.Draw(mask)
    cx, cy, outer, band = 540, 1340, 660, 34
    r0, r1 = outer - 1, outer - band * len(RAINBOW_COLORS) + 2   # 마스크를 띠 안쪽으로 살짝 줄여 검은 테두리 방지
    md.ellipse(P([(cx - r0, cy - r0), (cx + r0, cy + r0)]), fill=255)
    md.ellipse(P([(cx - r1, cy - r1), (cx + r1, cy + r1)]), fill=0)
    md.rectangle(P([(0, cy), (W, H)]), fill=0)
    _G["rainbow"], _G["rainbow_mask"] = rb, mask


def render_frame(t):
    if not _G:
        _init_worker()
    img = _G["sky"].copy()
    # 무지개 (천천히 나타남, 하늘 위·구름 앞)
    if t >= RAINBOW_T:
        a = ease_io((t - RAINBOW_T) / 1.5)
        m = _G["rainbow_mask"] if a >= 1 else _G["rainbow_mask"].point(lambda v: int(v * a))
        img = Image.composite(_G["rainbow"], img, m)
    d = ImageDraw.Draw(img)
    draw_cloud(d, 300 - 6 * t, 650, 1.0)      # 별 뒤로 지나가지 않게 왼쪽으로 천천히
    draw_cloud(d, 860 - 10 * t, 930, 0.8)
    draw_hill(d)

    nst, dst = nemo_state(t), dongle_state(t)
    draw_shadow(d, TOWER_X, GROUND, 95, 0)
    draw_shadow(d, nst["x"], GROUND, 120, nst["air"])
    draw_shadow(d, dst["x"], GROUND, 120, dst["air"])

    front = []
    for color, phases in BLOCKS:
        s = block_state(phases, t)
        if s is None:
            continue
        if s[6]:
            draw_block(d, color, *s[:6])
        else:
            front.append((color, s))
    draw_star(d, t)
    draw_character(d, "nemo", nst, look_target("nemo", t, nst))
    draw_character(d, "dongle", dst, look_target("dongle", t, dst))
    # 땅에 있는 블록은 아래쪽(앞)에 있는 것부터 나중에 그린다
    front.sort(key=lambda cs: cs[1][1])
    for color, s in front:
        draw_block(d, color, *s[:6])
    draw_sparkles(d, t)
    draw_lyrics(d, t)
    draw_banner(d, t)
    return img.resize((W, H), Image.LANCZOS).tobytes()


# ───────────────────────── 소리 (모두 직접 합성) ─────────────────────────

def nf(name):
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    return 440 * 2 ** ((names[name[0]] + (int(name[1:]) - 4) * 12) / 12)


def add(buf, start, sig):
    i = int(round(start * SR))
    j = min(len(buf), i + len(sig))
    if i < j:
        buf[i:j] += sig[: j - i]


def tvec(dur):
    return np.arange(int(dur * SR)) / SR


def xylophone(f, beats=1, vol=0.3):
    dur = 0.9 + 0.5 * beats
    t = tvec(dur)
    decay = 6.0 if beats == 1 else 3.2
    env = np.exp(-t * decay) * np.minimum(t * 500, 1)
    sig = (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 9)
           + 0.25 * np.sin(2 * np.pi * 4.0 * f * t) * np.exp(-t * 22))
    sig *= np.minimum((dur - t) * 20, 1)
    return vol * env * sig


def bass(f, dur=1.0, vol=0.16):
    t = tvec(dur + 0.3)
    env = np.minimum(t * 60, 1) * np.exp(-t * 2.2) * np.minimum((dur + 0.3 - t) * 10, 1)
    return vol * env * (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t))


def pad(freqs, dur, vol=0.035):
    t = tvec(dur + 0.25)
    env = np.minimum(t / 0.15, 1) * np.minimum((dur + 0.25 - t) / 0.25, 1)
    sig = sum(np.sin(2 * np.pi * f * t) * (1 + 0.003 * np.sin(2 * np.pi * 5 * t)) for f in freqs)
    return vol * env * sig


def boing(f0=600, f1=300, dur=0.15, vol=0.13):
    t = tvec(dur + 0.08)
    f = np.where(t < dur, f0 + (f1 - f0) * t / dur, f1) + 18 * np.sin(2 * np.pi * 28 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return vol * np.sin(ph) * np.exp(-t * 10) * np.minimum(t * 400, 1)


def pong(f=400, vol=0.14):
    t = tvec(0.18)
    return vol * np.sin(2 * np.pi * f * t * (1 - 0.15 * t)) * np.exp(-t * 26) * np.minimum(t * 600, 1)


def slide_whistle(dur, f0, f1, vol=0.07):
    t = tvec(dur)
    u = t / dur
    f = f0 * (f1 / f0) ** u * (1 + 0.015 * np.sin(2 * np.pi * 6 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    return vol * np.sin(ph) * np.minimum(t * 20, 1) * np.minimum((dur - t) * 20, 1)


def laugh(vol=0.07):
    """사람 목소리 대신 '삐뽀롱' 상승음"""
    out = np.zeros(int(0.45 * SR))
    for k, n in enumerate(["G5", "C6", "E6"]):
        t = tvec(0.2)
        f = nf(n) * (1 + 0.02 * np.sin(2 * np.pi * 14 * t))
        ph = 2 * np.pi * np.cumsum(f) / SR
        sig = (np.sin(ph) + 0.25 * np.sin(3 * ph)) * np.exp(-t * 14) * np.minimum(t * 300, 1)
        add(out, k * 0.08, vol * sig)
    return out


def clap(vol=0.18, seed=3):
    rng = np.random.default_rng(seed)
    t = tvec(0.16)
    noise = np.diff(rng.uniform(-1, 1, len(t) + 1))
    env = np.exp(-t * 38) + 0.4 * np.exp(-np.maximum(t - 0.012, 0) * 45) * (t > 0.012)
    return vol * noise * env * np.minimum(t * 2000, 1)


CHORDS = {"C": ["C3", "E3", "G3"], "F": ["F3", "A3", "C4"], "G": ["G2", "B2", "D3"]}


def make_audio(path):
    n = int(DUR * SR)
    mus, sfx = np.zeros(n), np.zeros(n)
    # 멜로디: 실로폰 + 한 옥타브 위 글로켄 겹침(작은 스피커에서도 잘 들리게)
    for t0, name, beats in NOTES:
        f = nf(name)
        add(mus, t0, xylophone(f, beats, 0.30))
        add(mus, t0, xylophone(2 * f, beats, 0.09))
    # 반주: 반 마디(2박)마다 베이스 + 부드러운 패드
    bars = [("C", "C3", "C", "G2")]                                  # 인트로
    for v in range(4):
        bars += [("C", "C3", "C", "G2"), ("C", "C3", "C", "G2"),     # A줄
                 ("F", "F2", "G", "G2"), ("G", "G2", "C", "C3")]     # B줄
    bars += [("C", "C3", "C", "G2"), ("G", "G2", "C", "C3")]         # 아웃트로
    for b, (c1, b1, c2, b2) in enumerate(bars):
        t0 = b * 2.0
        last = b == len(bars) - 1
        add(mus, t0, bass(nf(b1)))
        add(mus, t0 + 1.0, bass(nf(b2), dur=1.0 if not last else 1.0))
        add(mus, t0, pad([nf(x) for x in CHORDS[c1]], 1.0))
        add(mus, t0 + 1.0, pad([nf(x) for x in CHORDS[c2]], 1.0 if not last else 0.9))

    # 효과음 (음악보다 약 6dB 작게)
    add(sfx, 0.5, boing())
    add(sfx, 1.0, boing(vol=0.08))
    add(sfx, 0.4, slide_whistle(1.1, 900, 500, 0.05))                # 동글이 굴러 들어옴
    for L in NEMO_LANDS:
        add(sfx, L, boing())
    for L, f in [(8.5, 420), (8.75, 380), (9.0, 400)]:               # 블록이 풀밭에 퐁퐁
        add(sfx, L, pong(f))
    add(sfx, 9.4, laugh())
    add(sfx, 9.62, laugh(0.05))
    add(sfx, 10.5, boing(vol=0.10))
    add(sfx, 14.0, slide_whistle(1.5, 500, 1300))                   # 데굴데굴 (올라감)
    add(sfx, 14.55, pong(380))
    add(sfx, 15.5, slide_whistle(1.5, 1300, 500))                   # 굴러 돌아옴 (내려감)
    add(sfx, 17.0, laugh())
    add(sfx, 17.22, laugh(0.05))
    add(sfx, 20.0, boing())
    add(sfx, 21.0, boing())
    for t0, name in zip([19.0] + TOWER_LANDS, ["C5", "D5", "E5", "F5", "G5", "A5"]):
        add(sfx, t0, xylophone(nf(name), 1, 0.12))                  # 탑이 한 칸씩
    for k, name in enumerate(["C6", "E6", "G6"]):                    # 별 등장 차임
        add(sfx, STAR_T + 0.12 * k, xylophone(nf(name), 2, 0.07))
    add(sfx, 30.0, boing(420, 720, 0.12, 0.10))                     # 하이파이브
    add(sfx, 30.05, laugh())
    add(sfx, 34.0, clap(seed=3))
    add(sfx, 35.0, clap(seed=4))
    for k, name in enumerate(["G5", "C6", "E6"]):                    # 문구 등장
        add(sfx, 36.0 + 0.08 * k, xylophone(nf(name), 1, 0.045))

    buf = mus + sfx
    buf *= np.minimum(1, (DUR - np.arange(n) / SR) / 0.25)           # 마지막 0.25초 페이드
    write_wav(path, buf)
    # 통합 음량 -14 LUFS로 맞추고 피크는 -1.5 dBFS 아래로 제한
    for _ in range(3):
        lufs = measure_lufs(path)
        buf *= 10 ** ((-14.0 - lufs) / 20)
        lim = 10 ** (-1.5 / 20)
        knee = 0.7 * lim
        a = np.abs(buf)
        over = a > knee
        buf[over] = np.sign(buf[over]) * (knee + (lim - knee) * np.tanh((a[over] - knee) / (lim - knee)))
        write_wav(path, buf)
    print(f"  음량 {measure_lufs(path):.2f} LUFS, 피크 {20 * math.log10(np.abs(buf).max()):.2f} dBFS")


def write_wav(path, buf):
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())


def measure_lufs(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128",
                        "-f", "null", "-"], capture_output=True, text=True)
    s = r.stderr[r.stderr.rfind("Summary:"):]
    return float(re.search(r"I:\s+(-?[\d.]+) LUFS", s).group(1))


# ───────────────────────── 합치기 ─────────────────────────

def main():
    wav = OUT_DIR / "audio.wav"
    out = OUT_DIR / f"{NAME}.mp4"
    make_audio(wav)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav), "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total = int(DUR * FPS)
    with Pool(8, initializer=_init_worker) as pool:
        for f, data in enumerate(pool.imap(render_frame, [k / FPS for k in range(total)], chunksize=4)):
            proc.stdin.write(data)
            if f % 150 == 0:
                print(f"  {f}/{total} 프레임")
    proc.stdin.close()
    proc.wait()
    wav.unlink()
    print(f"완성: {out}")


if __name__ == "__main__":
    main()
