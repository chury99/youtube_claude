#!/usr/bin/env python3
"""
20261119_놀이터색깔 후처리 (scripts/assemble_video.py가 만든 _raw.mp4 → 최종본)

  구간(edit.json 7개): _1·_2·_3 전체(각 7.93초),
     _4 0~4.417초 + 5.25~7.93초  (터널 속으로 다시 들어가 사라졌다가 0.8초 뒤 밖에 서서 나타나는 생성 오류 제거)
     _5 0~2.25초 + 4.65~7.93초   (미끄럼틀 활강로를 거꾸로 기어오르는 2.4초 제거: 아동 안전·기획안 [9] 안전 조건)
  → 1093프레임 = 36.433초

  1) 반주 합성: 새 멜로디(C장조, 4/4, 72박 = 18마디, 박 = 영상길이/72 ≈ 0.506초 ≈ 118.5BPM)
     실로폰 멜로디 + 우쿨렐레풍 화음 + 베이스 + 손뼉 + 작은 탬버린, 노랑 구간은 "콩콩" 피치카토.
     numpy 합성 → bgm_synth.wav (노래 목소리 없음, 원본 멜로디 아님, 외부 음원 없음)
     루프: 원형 버퍼라 끝 음의 여운이 0초로 감기고, 18마디는 G(딸림화음)로 끝나 1마디 C로 이어진다.
     엔딩 화음·페이드아웃 없음.
  2) 소리 섞기: 클립 효과음 + 반주 → 효과음 피크 리미터 → loudnorm 2패스(-14 LUFS, TP -1.5)
  3) 화면 손질: Veo가 화면에 그려 넣은 자막·글자를 흐림 처리 (깨진 한글, "Whee~ What color?",
     "Wom!", "Red, yellow, blue and green/", "One more time?" 등). Veo 워터마크는 건드리지 않는다.
     루프 마감: 마지막 0.2초 동안 0프레임(흐림 적용, 자막 전) 그림으로 서서히 겹침. 암전 없음.
  4) 가사 자막: Pretendard ExtraBold, 한국어 위(크게)·영어 아래(작게), 색 이름은 해당 색 글자.
     세로 12~65% 안, 가로 중심 320px(오른쪽 15% 쇼츠 UI 피함). 봄이 얼굴을 가리지 않게 위/아래 선택.
  5) 인코딩: 720x1280, 30fps, H.264 + AAC 48kHz, +faststart

다시 실행해도 같은 결과 (난수 시드 고정).
실행: .venv/bin/python 5_videos/20261119_놀이터색깔/edit_video.py
"""

import json
import re
import subprocess
import wave
from pathlib import Path

import numpy as np
import skia
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
FONT_PATH = ROOT / "assets" / "fonts" / "Pretendard-ExtraBold.otf"
HERE = Path(__file__).resolve().parent
BASE = "20261119_놀이터색깔"
RAW = HERE / f"{BASE}_raw.mp4"
OUT = HERE / f"{BASE}.mp4"
BGM = HERE / "bgm_synth.wav"
MIX = HERE / "mix_tmp.wav"
W, H, FPS = 720, 1280, 30

# (클립 번호 0~4 = 프롬프트 _1~_5, 원본 시작초, raw 안 프레임 수) — 프레임 수는 raw 장면 전환 실측
SEGS = [
    (0, 0.0, 238),
    (1, 0.0, 238),
    (2, 0.0, 238),
    (3, 0.0, 133),     # _4 0~4.417
    (3, 5.25, 80),     # _4 5.25~끝 (터널 앞에 서 있음)
    (4, 0.0, 68),      # _5 0~2.25 (달려가며 가리킴)
    (4, 4.65, 98),     # _5 4.65~끝 (꼭대기에 앉음 → 두 손 번쩍)
]
SEG_START = [sum(n for *_, n in SEGS[:k]) for k in range(len(SEGS))]
NFRAMES = sum(n for *_, n in SEGS)
DUR = NFRAMES / FPS
SR = 48000
N = int(round(DUR * SR))
AUDIO_CUTS = [f / FPS for f in SEG_START[1:]]
O = [f / FPS for f in SEG_START]       # 각 구간이 시작하는 완성본 시각

# ───────────────────────── 1) 반주 합성 ─────────────────────────
TOTAL_BEATS = 72
BEAT = DUR / TOTAL_BEATS
NOTE_IDX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(name):
    base = NOTE_IDX[name[0]]
    if name[1] == "#":
        base += 1
    elif name[1] == "b":
        base -= 1
    return 12 * (int(name[-1]) + 1) + base


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


Q1 = [("G4", 1), ("C5", 1), ("E5", 1.5), ("D5", .5)]                                   # 슈웅~ 무슨 색?
Q2 = [("C5", .5), ("D5", .5), ("E5", .5), ("G5", .5), ("E5", 1), ("R", 1)]
A1 = [("A4", .5), ("A4", .5), ("C5", .5), ("A4", .5), ("G4", 1), ("E4", 1)]            # 빨강! 빨간 미끄럼틀
A2 = [("F4", .5), ("A4", .5), ("G4", .5), ("E4", .5), ("D4", 1), ("G4", 1)]
P = "p"   # 콩콩 피치카토
K1 = [("C5", .5, P), ("R", .5), ("C5", .5, P), ("R", .5), ("E5", .5, P), ("D5", .5, P), ("C5", 1, P)]   # 콩콩~ 무슨 색?
K2 = [("D5", .5, P), ("R", .5), ("D5", .5, P), ("R", .5), ("G5", .5, P), ("F5", .5, P), ("E5", 1, P)]
Y1 = [("E5", .5), ("E5", .5), ("G5", .5), ("E5", .5), ("D5", 1), ("C5", 1)]             # 노랑! 노란 병아리
Y2 = [("A4", .5), ("C5", .5), ("B4", .5), ("A4", .5), ("G4", 1.5), ("R", .5)]
C1 = [("C5", .5), ("C5", .5), ("E5", .5), ("E5", .5), ("G5", .5), ("G5", .5), ("E5", 1)]  # 빨강 노랑 파랑 초록
C2 = [("F5", .5), ("E5", .5), ("D5", .5), ("C5", .5), ("D5", 1), ("G4", 1)]            # 알록달록 우리 놀이터
B1 = [("G4", 1.5), ("A4", .5), ("G4", 1), ("E4", 1)]                                   # 흔들~ (그네)
B2 = [("A4", .5), ("A4", .5), ("C5", .5), ("A4", .5), ("G4", 1), ("C5", 1)]            # 파랑! 파란 그네
G1 = [("E5", .5), ("R", .5), ("E5", .5), ("R", .5), ("G5", 1), ("E5", 1)]               # 까꿍~ 무슨 색?
G2 = [("D5", .5), ("E5", .5), ("D5", .5), ("C5", .5), ("A4", 1), ("G4", 1)]
G3 = [("A4", .5), ("A4", .5), ("C5", .5), ("A4", .5), ("G4", 1), ("E5", 1)]            # 초록! 초록 터널
E1 = [("E5", .5), ("D5", .5), ("C5", .5), ("D5", .5), ("G4", 1), ("G4", .5), ("R", .5)]  # 한 번 더 타 볼까? (딸림음에서 멈춤)

BARS = [Q1, Q2, A1, A2,          # 마디 1~4  (_1 빨강)
        K1, K2, Y1, Y2,          # 마디 5~8  (_2 노랑)
        C1, C2,                  # 마디 9~10 (후렴 1)
        B1, B2,                  # 마디 11~12 (파랑)
        G1, G2, G3,              # 마디 13~15 (초록)
        C1, C2,                  # 마디 16~17 (후렴 2)
        E1]                      # 마디 18 → 마디 1로 돌아감
CHORDS = "C C F G Am F G G  C C F G C F G G  C F G C  C Am F G  C C F G Am C  C F G C  G G".split()
VOICING = {
    "C": (["C4", "E4", "G4"], "C3"), "F": (["C4", "F4", "A4"], "F2"),
    "G": (["B3", "D4", "G4"], "G2"), "Am": (["C4", "E4", "A4"], "A2"),
}
BOUNCY = (16, 32)   # 마디 5~8 박 범위: 콩콩 리듬


def add(buf, start, sig):
    """원형 버퍼에 더하기: 끝을 넘는 여운은 0초 쪽으로 감겨 루프가 끊기지 않는다."""
    i = int(round(start * SR)) % len(buf)
    k = min(len(sig), len(buf))
    first = min(k, len(buf) - i)
    buf[i:i + first] += sig[:first]
    if k > first:
        buf[:k - first] += sig[first:k]


def env_tone(f, length, decay, partials, attack=0.004):
    t = np.arange(int(length * SR)) / SR
    s = np.zeros_like(t)
    for mult, amp, dmul in partials:
        s += amp * np.sin(2 * np.pi * f * mult * t) * np.exp(-t * decay * dmul)
    a = np.minimum(t / attack, 1.0)
    rel = np.minimum((length - t) / 0.03, 1.0)
    return s * a * rel


def xylophone(f, dur):
    return env_tone(f, min(max(dur, 0.35) + 0.4, 1.6), 4.5,
                    [(1, 1.0, 1), (3.93, 0.22, 3.0), (9.2, 0.06, 6.0)])


def pizz(f):
    return env_tone(f, 0.45, 11.0, [(k, 1.0 / k, 0.5 + 0.6 * k) for k in range(1, 6)], attack=0.003)


def pluck(f, length=0.9):
    return env_tone(f, length, 5.0, [(k, 1.0 / k, 0.6 + 0.5 * k) for k in range(1, 7)], attack=0.002)


def bass(f, length=0.9):
    return env_tone(f, length, 3.0, [(1, 1.0, 1), (2, 0.25, 2)], attack=0.01)


def bell(f):
    return env_tone(f, 1.2, 3.0, [(1, 1.0, 1), (2.76, 0.3, 2.0), (5.4, 0.1, 3.0)], attack=0.003)


def noise_burst(rng, length, decay, smooth=1):
    n = rng.standard_normal(int(length * SR))
    if smooth > 1:
        n = np.convolve(n, np.ones(smooth) / smooth, mode="same")
    else:
        n = np.diff(n, prepend=0)
    t = np.arange(len(n)) / SR
    return n * np.exp(-t * decay)


def synth_bgm():
    rng = np.random.default_rng(20261119)
    lead, uke, low, perc, spark = (np.zeros(N) for _ in range(5))

    t = 0.0
    for bi, bar in enumerate(BARS):
        bt = 0.0
        for note in bar:
            name, beats = note[0], note[1]
            inst = note[2] if len(note) > 2 else "x"
            d = beats * BEAT
            if name != "R":
                f = hz(midi(name))
                if inst == P:
                    add(lead, t, 1.1 * pizz(f))
                    add(lead, t, 0.5 * xylophone(f * 2, 0.2))
                else:
                    add(lead, t, xylophone(f, d))
                    add(lead, t, 0.35 * xylophone(f * 2, d))
            t += d
            bt += beats
        assert bt == 4, (bi, bt)
    assert abs(t - DUR) < 1e-6, t
    assert len(CHORDS) * 2 == TOTAL_BEATS, len(CHORDS)

    for ci, ch in enumerate(CHORDS):
        tones, root = VOICING[ch]
        b0 = ci * 2
        bouncy = BOUNCY[0] <= b0 < BOUNCY[1]
        for b in range(2):
            tb = (b0 + b) * BEAT
            gain = 1.0 if b == 0 else 0.7
            for k, nm in enumerate(tones):
                add(uke, tb + 0.012 * k, gain * pluck(hz(midi(nm))))
            add(uke, tb + BEAT / 2, 0.35 * pluck(hz(midi(tones[-1])), 0.5))
        if bouncy:   # 콩콩: 반박마다 통통 튀는 베이스
            for q in range(4):
                add(low, b0 * BEAT + q * BEAT / 2, (0.8 if q % 2 == 0 else 0.55) * bass(hz(midi(root)), 0.25))
        else:
            add(low, b0 * BEAT, bass(hz(midi(root))))
            add(low, (b0 + 1) * BEAT, 0.6 * bass(hz(midi(root) + 7), 0.5))

    clap = noise_burst(rng, 0.12, 35, smooth=3)
    clap /= np.abs(clap).max()
    tamb = noise_burst(rng, 0.09, 45)
    tamb /= np.abs(tamb).max()
    for b in range(TOTAL_BEATS):
        tb = b * BEAT
        if b % 2 == 1:                       # 2·4박 손뼉
            add(perc, tb, 0.8 * clap)
        add(perc, tb + BEAT / 2, 0.35 * tamb)  # 엇박 탬버린

    # 색 이름이 나오는 순간 부드러운 벨 (반박 단위로 맞춤)
    for tt in REVEALS:
        tb = round(tt / (BEAT / 2)) * (BEAT / 2)
        add(spark, tb, bell(hz(midi("C6"))))
        add(spark, tb + BEAT / 2, 0.6 * bell(hz(midi("G6"))))

    nz = lambda x: x / (np.abs(x).max() + 1e-9)
    mix = 0.36 * nz(lead) + 0.20 * nz(uke) + 0.24 * nz(low) + 0.10 * nz(perc) + 0.08 * nz(spark)
    left = mix + 0.04 * nz(uke)
    right = mix + 0.04 * nz(lead)
    st = np.stack([left, right], 1)
    return st / np.abs(st).max() * 0.9


def write_wav(path, stereo):
    data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def read_clip_audio():
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(RAW), "-t", f"{DUR:.4f}", "-f", "s16le",
                        "-ac", "2", "-ar", str(SR), "-"], capture_output=True, check=True)
    a = np.frombuffer(p.stdout, "<i2").astype(np.float64).reshape(-1, 2) / 32768
    out = np.zeros((N, 2))
    out[: min(len(a), N)] = a[:N]
    return out


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def limit(x, thr):
    env = np.abs(x).max(axis=1)
    g = np.minimum(1.0, thr / (env + 1e-12))
    k = int(0.005 * SR)
    gp = np.pad(g, (k, k), mode="edge")
    gmin = np.min(np.lib.stride_tricks.sliding_window_view(gp, 2 * k + 1), axis=1)
    sm = np.convolve(gmin, np.ones(2 * k) / (2 * k), mode="same")
    return x * np.minimum(sm, 1.0)[:, None]


def build_audio():
    bgm = synth_bgm()
    write_wav(BGM, bgm)
    sfx = read_clip_audio()
    r = int(0.015 * SR)
    for tc in AUDIO_CUTS:  # 이음매 ±15ms 페이드
        c = int(round(tc * SR))
        sfx[c - r:c] *= np.linspace(1, 0, r)[:, None]
        sfx[c:c + r] *= np.linspace(0, 1, r)[:, None]
    sfx[:r] *= np.linspace(0, 1, r)[:, None]
    sfx[-r:] *= np.linspace(1, 0, r)[:, None]
    bgm_g = 10 ** ((-20 - rms_db(bgm)) / 20)
    sfx_g = 10 ** ((-26 - rms_db(sfx)) / 20)
    sfx = limit(sfx * sfx_g, 10 ** (-12 / 20))
    mix = bgm * bgm_g + sfx
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    write_wav(MIX, mix)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(MIX), "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = json.loads(r.stderr[r.stderr.rfind("{"): r.stderr.rfind("}") + 1])
    return ("loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:"
            f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}")


# ───────────────────────── 3) 화면 손질: AI가 그린 글자 흐림 ─────────────────────────
# (클립 번호, 클립 안 시작초, 끝초, (x0, y0, x1, y1) 720x1280 기준) — 프레임 단위 실측 + 앞뒤 여유(글자 페이드 포함)
BLURS = [
    (0, 0.25, 4.00, (120, 1140, 610, 1240)),   # _1 "Whee~ What color?"
    (0, 4.15, 7.10, (95, 1025, 690, 1235)),    # _1 깨진 한글 + "RE?ED / The red slide"
    (0, 5.85, 7.94, (445, 80, 720, 370)),      # _1 오른쪽 위 깨진 한글 "마악!! 과 하"
    (1, 7.10, 7.94, (510, 465, 720, 590)),     # _2 "Wom!"
    (4, 0.00, 0.90, (190, 1035, 640, 1100)),   # _5 작은 깨진 글자 "Red, yello 와 blue..."
    (4, 0.00, 2.30, (75, 1135, 705, 1252)),    # _5 자막 상자 "Red, yellow, blue and green/" · 깨진 한글
    (4, 4.65, 7.94, (75, 1135, 705, 1252)),    # _5 자막 상자 "토보로 에 였아 / One more time?"
]
BLUR_RAMP = 0.12


def feather_mask(w, h, pad):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((pad, pad, w - pad, h - pad), radius=pad * 2, fill=255)
    return m.filter(ImageFilter.GaussianBlur(pad / 2))


def blur_frame(i, img):
    k = max(j for j in range(len(SEGS)) if SEG_START[j] <= i)
    ci, src0, nf = SEGS[k]
    t = src0 + (i - SEG_START[k]) / FPS
    t_seg0, t_seg1 = src0, src0 + nf / FPS
    for c, t0, t1, (x0, y0, x1, y1) in BLURS:
        if c != ci or not (t0 <= t < t1):
            continue
        a = 1.0
        if t0 > t_seg0:
            a = min(a, (t - t0) / BLUR_RAMP + 0.3)
        if t1 < t_seg1:
            a = min(a, (t1 - t) / BLUR_RAMP + 0.3)
        a = max(0.0, min(1.0, a))
        pad = 10
        full = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        box = (max(0, full[0]), max(0, full[1]), min(W, full[2]), min(H, full[3]))
        region = img.crop(box)
        bl = region.filter(ImageFilter.GaussianBlur(16)).filter(ImageFilter.GaussianBlur(16))
        ext = 3 * pad
        fx0 = full[0] - (ext if full[0] <= 0 else 0)
        fy0 = full[1] - (ext if full[1] <= 0 else 0)
        fx1 = full[2] + (ext if full[2] >= W else 0)
        fy1 = full[3] + (ext if full[3] >= H else 0)
        fm = feather_mask(fx1 - fx0, fy1 - fy0, pad)
        mask = fm.crop((box[0] - fx0, box[1] - fy0, box[2] - fx0, box[3] - fy0))
        if a < 1.0:
            mask = mask.point(lambda v: int(v * a))
        img.paste(bl, box[:2], mask)
    return img


# ───────────────────────── 4) 가사 자막 ─────────────────────────
TF = skia.Typeface.MakeFromFile(str(FONT_PATH)) if FONT_PATH.exists() else None
if TF is None:
    TF = skia.Typeface("Apple SD Gothic Neo", skia.FontStyle.Bold())
WHITE = skia.Color(255, 255, 255)
OUTLINE = skia.Color(52, 36, 92)          # 진한 보라 테두리 (봄이 멜빵 색 계열)
SHADOW = skia.Color(20, 10, 40, 150)
COLORS = {"r": skia.Color(240, 48, 48), "y": skia.Color(255, 212, 0),
          "b": skia.Color(40, 132, 255), "g": skia.Color(40, 196, 72)}
MAX_W = 580
CX = 320
HIGH_TOP = 160      # 세로 12.5%
LOW_BOTTOM = 830    # 세로 65%


def parse(text):
    """'{r:빨강}! 빨간' → [('빨강', 빨강색), ('! 빨간', 흰색)]"""
    out = []
    for m in re.finditer(r"\{(\w):([^}]*)\}|([^{]+)", text):
        if m.group(1):
            out.append((m.group(2), COLORS[m.group(1)]))
        else:
            out.append((m.group(3), WHITE))
    return out


def plain(text):
    return "".join(s for s, _ in parse(text))


def draw_rich(canvas, text, size, baseline, stroke):
    parts = parse(text)
    font = skia.Font(TF, size)
    w = font.measureText(plain(text))
    if w > MAX_W:
        font = skia.Font(TF, size * MAX_W / w)
        stroke = stroke * MAX_W / w
        w = font.measureText(plain(text))
    x0 = CX - w / 2
    blobs, x = [], x0
    for s, col in parts:
        blobs.append((skia.TextBlob.MakeFromString(s, font), x, col))
        x += font.measureText(s)
    sh = skia.Paint(AntiAlias=True, Color=SHADOW, Style=skia.Paint.kStrokeAndFill_Style,
                    StrokeWidth=stroke, StrokeJoin=skia.Paint.kRound_Join,
                    MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 5))
    ol = skia.Paint(AntiAlias=True, Color=OUTLINE, Style=skia.Paint.kStroke_Style,
                    StrokeWidth=stroke, StrokeJoin=skia.Paint.kRound_Join, StrokeCap=skia.Paint.kRound_Cap)
    for b, bx, _ in blobs:
        canvas.drawTextBlob(b, bx + 3, baseline + 4, sh)
    for b, bx, _ in blobs:
        canvas.drawTextBlob(b, bx, baseline, ol)
    for b, bx, col in blobs:
        canvas.drawTextBlob(b, bx, baseline, skia.Paint(AntiAlias=True, Color=col))


def lyric(ko_lines, en_lines, pos):
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.Color(0, 0, 0, 0))
    lines = [(t, 54, 12, 56 if i == 0 else 64) for i, t in enumerate(ko_lines)]
    lines += [(t, 32, 8, 46 if i == 0 else 40) for i, t in enumerate(en_lines)]
    total = sum(step for *_, step in lines) + 14
    y = HIGH_TOP if pos == "high" else LOW_BOTTOM - total
    y0 = y
    for t, size, stroke, step in lines:
        y += step
        draw_rich(c, t, size, y, stroke)
    arr = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType,
                                            alphaType=skia.kUnpremul_AlphaType)
    top, bot = int(max(0, y0 - 20)), int(min(H, y + 30))
    assert y0 >= 0.12 * H - 1 and y + 14 <= 0.65 * H + 1, (ko_lines, y0, y)
    return (0, top, arr[top:bot].astype(np.float32) / 255.0)


CH_KO = ["{r:빨강} {y:노랑} {b:파랑} {g:초록}", "알록달록 우리 놀이터"]
CH_EN = ["{r:Red}, {y:yellow}, {b:blue} and {g:green}", "Our colorful playground!"]
ARMS_UP = O[6] + round((5.80 - SEGS[6][1]) * FPS) / FPS   # _5 원본 5.8초: 두 손 번쩍
# (시작, 끝, 한국어 줄, 영어 줄, 위치) — 위치는 봄이 얼굴을 피해서 고름
LYRICS = [
    (0.0, 4.0, ["슈웅~ 무슨 색?"], ["Whee~ What color?"], "low"),                     # 꼭대기·활강: 얼굴이 위쪽
    (4.0, O[1], ["{r:빨강}! 빨간 미끄럼틀"], ["{r:RED}! The red slide"], "high"),       # 착지·가리킴: 위쪽은 지붕
    (O[1], O[1] + 3.0, ["콩콩~ 무슨 색?"], ["Boing~ What color?"], "low"),            # 병아리로 달려감·올라탐
    (O[1] + 3.0, O[2], ["{y:노랑}! 노란 병아리"], ["{y:YELLOW}! The yellow chick"], "low"),
    (O[2], O[2] + 3.4, CH_KO, CH_EN, "high"),                                         # 와이드: 위쪽은 하늘
    (O[2] + 3.4, O[3], ["흔들~ {b:파랑}! 파란 그네"], ["Swing~ {b:BLUE}! The blue swing"], "low"),
    (O[3], O[4], ["까꿍~ 무슨 색?"], ["Peekaboo~ What color?"], "low"),               # 터널 얼굴: 위쪽
    (O[4], O[5], ["{g:초록}! 초록 터널"], ["{g:GREEN}! The green tunnel"], "high"),     # 서 있는 와이드
    (O[5], ARMS_UP, CH_KO, CH_EN, "low"),
    (ARMS_UP, DUR, ["한 번 더 타 볼까?"], ["One more time?"], "low"),
]
REVEALS = [4.0, O[1] + 3.0, O[2] + 3.4, O[4]]   # 색 이름이 나오는 순간 (벨)
FADE = 0.15


def build_overlays():
    items = []
    rows = [(s, e, lyric(k, en, p)) for s, e, k, en, p in LYRICS]
    starts = {round(r[0], 3) for r in rows}
    ends = {round(r[1], 3) for r in rows}
    for s, e, ov in rows:
        fi = s > 0 and round(s, 3) not in ends
        fo = e < DUR - 1e-6 and round(e, 3) not in starts
        items.append((s, e, ov, fi, fo))
    return items


def composite(frame, overlays, t):
    for s, e, (x0, y0, rgba), fi, fo in overlays:
        if not (s <= t < e):
            continue
        a_in = min(1.0, (t - s) / FADE) if fi else 1.0
        a_out = min(1.0, (e - t) / FADE) if fo else 1.0
        a = max(0.0, min(a_in, a_out))
        if a <= 0:
            continue
        h, w = rgba.shape[:2]
        reg = frame[y0:y0 + h, x0:x0 + w].astype(np.float32)
        al = rgba[..., 3:4] * a
        frame[y0:y0 + h, x0:x0 + w] = (reg * (1 - al) + rgba[..., :3] * 255 * al + 0.5).astype(np.uint8)
    return frame


LOOP_BLEND = 6   # 0.2초


# ───────────────────────── 5) 실행 ─────────────────────────
def main():
    print("font:", FONT_PATH if FONT_PATH.exists() else "Apple SD Gothic Neo (대체)")
    print(f"길이 {DUR:.3f}초 ({NFRAMES}프레임), 박 {BEAT:.4f}초 ({60 / BEAT:.2f} BPM)")
    print("구간 시작:", [round(o, 3) for o in O], "두 손 번쩍:", round(ARMS_UP, 3))
    nraw = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                               "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(RAW)],
                              capture_output=True, text=True, check=True).stdout.strip())
    assert nraw == NFRAMES, f"raw 프레임 수 {nraw} ≠ 구간 합 {NFRAMES}: edit.json과 SEGS를 맞출 것"
    af = build_audio()
    overlays = build_overlays()
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(RAW), "-frames:v", str(NFRAMES),
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(MIX),
        "-map", "0:v", "-map", "1:a", "-af", af + f",aresample=48000,apad=whole_dur={DUR:.4f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{DUR:.4f}", "-movflags", "+faststart",
        str(OUT),
    ], stdin=subprocess.PIPE)
    size = W * H * 3
    first = None
    for i in range(NFRAMES):
        buf = dec.stdout.read(size)
        if len(buf) < size:
            raise SystemExit(f"raw 프레임 부족: {i}")
        frame = np.array(blur_frame(i, Image.frombuffer("RGB", (W, H), buf).copy()))
        if i == 0:
            first = frame.copy()
        k = i - (NFRAMES - LOOP_BLEND)
        if k >= 0:
            w = (k + 1) / (LOOP_BLEND + 1)
            w = 0.5 - 0.5 * np.cos(np.pi * w)
            frame = (frame.astype(np.float32) * (1 - w) + first.astype(np.float32) * w + 0.5).astype(np.uint8)
        frame = composite(frame, overlays, i / FPS)
        enc.stdin.write(frame.tobytes())
    dec.stdout.close()
    dec.wait()
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit("인코딩 실패")
    MIX.unlink(missing_ok=True)
    print("완성:", OUT)


if __name__ == "__main__":
    main()
