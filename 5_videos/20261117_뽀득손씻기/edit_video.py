#!/usr/bin/env python3
"""
20261117_뽀득손씻기 후처리 (scripts/assemble_video.py가 만든 _raw.mp4 → 최종본)

  1) 반주 합성: 기획안 [8] 가사 멜로디(120BPM, C장조)를 실로폰·우쿨렐레풍 뜯는 소리·베이스·
     셰이커·작은 박수로 numpy 합성 → bgm_synth.wav (노래 목소리 없음)
  2) 소리 섞기: 클립 효과음(뽕·졸졸·뽀득) + 반주 → loudnorm 2패스(-14 LUFS, TP -1.5)
  3) 화면 손질 (프레임 번호 기준, 30fps, 총 900프레임)
     - 240~284 (8.0~9.5초, 클립 _2 첫 샷): 왼쪽 가장자리 아이 머리카락 → 1.1배 확대(오른쪽 기준)
     - 480~678 (16.0~22.6초, 클립 _3): 오른쪽 위 아이 얼굴 → 1.32배 확대(왼쪽 아래 기준)
     - 679~738 (22.6~24.6초, 클립 _4 앞부분): 비누에 새겨진 가짜 글자 → 타원 영역 부드러운 블러
  4) 자막: 한글 한 줄 + 영어 한 줄(작게). 가사는 세로 55~65%, 단계 표시는 상단 13% 근처.
     부드러운 페이드(0.2초)만 사용, 깜박임 없음.
  5) 인코딩: 1080x1920, 30fps, H.264 + AAC, +faststart

다시 실행해도 같은 결과가 나온다 (난수 시드 고정).
실행: .venv/bin/python 5_videos/20261117_뽀득손씻기/edit_video.py
"""

import json
import subprocess
import wave
from pathlib import Path

import numpy as np
import skia
from PIL import Image, ImageDraw, ImageFilter

# ── 폰트: 이 파일이 있으면 쓰고, 없으면 Apple SD Gothic Neo(ExtraBold)로 대체 ──
FONT_PATH = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Pretendard-ExtraBold.otf"

HERE = Path(__file__).resolve().parent
BASE = "20261117_뽀득손씻기"
RAW = HERE / f"{BASE}_raw.mp4"
OUT = HERE / f"{BASE}.mp4"
BGM = HERE / "bgm_synth.wav"
MIX = HERE / "mix_tmp.wav"
W, H, FPS, DUR = 1080, 1920, 30, 30.0
NFRAMES = int(DUR * FPS)
SR = 48000
AUDIO_CUTS = (8.0, 16.0, 22.6)  # edit.json 클립 길이 8 + 8 + 6.6 + 7.4

# ───────────────────────── 1) 반주 합성 ─────────────────────────
BPM = 120
BEAT = 60 / BPM
NOTE_IDX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(name):
    return 12 * (int(name[-1]) + 1) + NOTE_IDX[name[0]]


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


# 가사 멜로디 (음, 박). 0.5박 = 한 글자
MELODY = [
    # 0~6초 뽀득뽀득 손 씻자, 거품 친구 나와라
    ("G4", .5), ("E4", .5), ("G4", .5), ("E4", .5), ("C5", 1), ("A4", .5), ("G4", 1.5), ("R", 1),
    ("A4", .5), ("A4", .5), ("G4", .5), ("E4", .5), ("D4", 1), ("E4", .5), ("C4", 1.5), ("R", 1),
    # 6~10초 물을 묻혀 졸졸졸, 비누 거품 몽글몽글
    ("E4", .5), ("G4", .5), ("A4", .5), ("G4", .5), ("E4", .5), ("E4", .5), ("D4", 1),
    ("F4", .5), ("F4", .5), ("A4", .5), ("G4", .5), ("E4", .5), ("D4", .5), ("E4", .5), ("C4", .5),
    # 10~13초 손바닥을 싹싹싹
    ("C5", .5), ("C5", .5), ("A4", .5), ("G4", .5), ("E4", 1), ("E4", 1), ("G4", 1), ("R", 1),
    # 13~16초 손등도 쓱쓱쓱
    ("D5", .5), ("C5", .5), ("A4", 1), ("G4", 1), ("G4", 1), ("C5", 1), ("R", 1),
    # 16~20초 손가락 사이사이 꼼꼼하게 뽀득뽀득
    ("E4", .5), ("G4", .5), ("A4", .5), ("C5", .5), ("A4", .5), ("G4", .5), ("E4", 1),
    ("D4", .5), ("E4", .5), ("F4", .5), ("A4", .5), ("G4", .5), ("E4", .5), ("G4", .5), ("C5", .5),
    # 20~24초 물로 헹궈 쏴아아, 흙먼지야 안녕
    ("C5", .5), ("A4", .5), ("G4", .5), ("E4", .5), ("G4", .5), ("A4", .5), ("G4", 1),
    ("F4", .5), ("F4", .5), ("E4", .5), ("D4", .5), ("E4", 1), ("C4", 1),
    # 24~30초 수건으로 톡톡톡, 깨끗한 손 짝짝짝 (+ 마무리 음)
    ("G4", .5), ("G4", .5), ("E4", .5), ("G4", .5), ("C5", .5), ("C5", .5), ("C5", 1),
    ("A4", .5), ("A4", .5), ("G4", .5), ("E4", .5), ("D4", .5), ("E4", .5), ("C4", 1),
    ("C5", 4),
]
# 1초(2박)마다 화음 30개
CHORDS = ("C C F F G C  C Am F C  F C C  Dm C C  Am C Dm C  Am C G C  C F Am G C C").split()
VOICING = {
    "C": (["C4", "E4", "G4"], "C3"), "F": (["A3", "C4", "F4"], "F2"),
    "G": (["G3", "B3", "D4"], "G2"), "Am": (["A3", "C4", "E4"], "A2"),
    "Dm": (["A3", "D4", "F4"], "D3"),
}


def add(buf, start, sig):
    i = int(round(start * SR))
    j = min(len(buf), i + len(sig))
    if j > i:
        buf[i:j] += sig[: j - i]


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


def pluck(f, length=0.9):
    return env_tone(f, length, 5.0, [(k, 1.0 / k, 0.6 + 0.5 * k) for k in range(1, 7)], attack=0.002)


def bass(f, length=0.9):
    return env_tone(f, length, 3.0, [(1, 1.0, 1), (2, 0.25, 2)], attack=0.01)


def noise_burst(rng, length, decay, smooth):
    n = rng.standard_normal(int(length * SR))
    if smooth > 1:  # 간단한 대역 필터: 고주파 빼고 저주파 빼기
        k = np.ones(smooth) / smooth
        lo = np.convolve(n, k, mode="same")
        n = lo - np.convolve(lo, np.ones(smooth * 6) / (smooth * 6), mode="same")
    else:
        n = np.diff(n, prepend=0)
    t = np.arange(len(n)) / SR
    return n * np.exp(-t * decay)


def clap(rng):
    out = np.zeros(int(0.25 * SR))
    for k, d in enumerate([0.0, 0.008, 0.017]):
        add(out, d, noise_burst(rng, 0.2, 35 if k == 2 else 120, 3))
    return out / (np.abs(out).max() + 1e-9)


def synth_bgm():
    rng = np.random.default_rng(20261117)
    n = int(DUR * SR)
    lead, uke, low, perc = (np.zeros(n) for _ in range(4))

    t = 0.0
    for name, beats in MELODY:
        d = beats * BEAT
        if name != "R":
            add(lead, t, xylophone(hz(midi(name)), d))
            add(lead, t, 0.35 * xylophone(hz(midi(name) + 12), d))  # 한 옥타브 위 반짝임(작게)
        t += d
    assert abs(t - DUR) < 1e-6, t

    for ci, ch in enumerate(CHORDS):
        tones, root = VOICING[ch]
        for b in range(2):  # 한 화음에 두 박
            tb = ci * 1.0 + b * BEAT
            gain = 1.0 if b == 0 else 0.7
            for k, nm in enumerate(tones):  # 위에서 아래로 살짝 늦게 긁기
                add(uke, tb + 0.012 * k, gain * pluck(hz(midi(nm))))
            add(uke, tb + BEAT / 2, 0.35 * pluck(hz(midi(tones[-1])), 0.5))  # 업스트로크 느낌
        add(low, ci * 1.0, bass(hz(midi(root))))

    shaker = noise_burst(rng, 0.08, 60, 1)
    shaker /= np.abs(shaker).max()
    cl = clap(rng)
    for b in range(int(DUR / BEAT)):
        tb = b * BEAT
        add(perc, tb + BEAT / 2, 0.5 * shaker)
        if tb >= 6.0 and b % 2 == 1 and tb < 29.0:
            add(perc, tb, 0.45 * cl)
    for tc in (27.0, 27.5, 28.0):  # 짝짝짝
        add(perc, tc, 1.0 * cl)

    mix = 0.36 * lead / np.abs(lead).max() + 0.20 * uke / np.abs(uke).max() \
        + 0.24 * low / np.abs(low).max() + 0.10 * perc / np.abs(perc).max()
    fade = int(0.08 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)
    mix[:200] *= np.linspace(0, 1, 200)
    # 아주 약한 스테레오 폭: 우쿨렐레 왼쪽, 실로폰 살짝 오른쪽
    left = mix + 0.04 * uke / np.abs(uke).max()
    right = mix + 0.04 * lead / np.abs(lead).max()
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
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(RAW), "-t", str(DUR), "-f", "s16le",
                        "-ac", "2", "-ar", str(SR), "-"], capture_output=True, check=True)
    a = np.frombuffer(p.stdout, "<i2").astype(np.float64).reshape(-1, 2) / 32768
    out = np.zeros((int(DUR * SR), 2))
    out[: min(len(a), len(out))] = a[: len(out)]
    return out


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def build_audio():
    bgm = synth_bgm()
    write_wav(BGM, bgm)
    sfx = read_clip_audio()
    # 클립 이음매(8.0 / 16.0 / 22.6초)에서 효과음이 툭 끊기지 않게 ±10ms 짧은 페이드
    for tc in AUDIO_CUTS:
        c, r = int(tc * SR), int(0.01 * SR)
        sfx[c - r:c] *= np.linspace(1, 0, r)[:, None]
        sfx[c:c + r] *= np.linspace(0, 1, r)[:, None]
    # 반주는 -20 dBFS RMS, 효과음은 그보다 7 dB 작게 (노래 아래에 작게 섞기)
    bgm_g = 10 ** ((-20 - rms_db(bgm)) / 20)
    sfx_g = 10 ** ((-27 - rms_db(sfx)) / 20)
    mix = bgm * bgm_g + sfx * sfx_g
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    write_wav(MIX, mix)
    # loudnorm 2패스
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(MIX), "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    js = r.stderr[r.stderr.rfind("{"): r.stderr.rfind("}") + 1]
    m = json.loads(js)
    return ("loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:"
            f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}")


# ───────────────────────── 3) 화면 손질 ─────────────────────────
def zoom(img, factor, ax, ay):
    """factor배 확대. ax, ay = 0(왼쪽/위)~1(오른쪽/아래) 기준점."""
    cw, chh = W / factor, H / factor
    x0, y0 = (W - cw) * ax, (H - chh) * ay
    return img.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + chh))


SOAP_BOX = (820, 1080, 1080, 1225)  # 비누 위 가짜 글자 (최종 좌표)
_soap_mask = Image.new("L", (SOAP_BOX[2] - SOAP_BOX[0], SOAP_BOX[3] - SOAP_BOX[1]), 0)
ImageDraw.Draw(_soap_mask).ellipse((20, 12, _soap_mask.width - 6, _soap_mask.height - 12), fill=255)
_soap_mask = _soap_mask.filter(ImageFilter.GaussianBlur(10))


def blur_soap(img, strength):
    region = img.crop(SOAP_BOX)
    blurred = region.filter(ImageFilter.GaussianBlur(9))
    mask = _soap_mask.point(lambda v: int(v * strength))
    region.paste(blurred, (0, 0), mask)
    img.paste(region, SOAP_BOX[:2])
    return img


def fix_frame(i, img):
    if 240 <= i <= 284:
        img = zoom(img, 1.10, 1.0, 0.5)
    if 480 <= i <= 678:
        img = zoom(img, 1.32, 0.0, 1.0)
    if 679 <= i <= 738:
        t = i / FPS
        s = 1.0 if t < 24.3 else max(0.0, (24.6 - t) / 0.3)
        img = blur_soap(img, s)
    return img


# ───────────────────────── 4) 자막 ─────────────────────────
def typeface():
    if FONT_PATH.exists():
        tf = skia.Typeface.MakeFromFile(str(FONT_PATH))
        if tf is not None:
            return tf
    return skia.Typeface("Apple SD Gothic Neo", skia.FontStyle(800, 5, skia.FontStyle.kUpright_Slant))


TF = typeface()
WHITE = skia.Color(255, 255, 255)
OUTLINE = skia.Color(36, 86, 140)       # 진한 하늘색(남청) 외곽선
SHADOW = skia.Color(20, 50, 90, 150)
PILL = skia.Color(92, 172, 228, 225)    # 단계 표시 배경 (하늘색)
MAX_W = 820                              # 가로 중앙 기준 → 오른쪽 끝 950px(오른쪽 12%) 안쪽


def fit_font(text, size, max_w):
    f = skia.Font(TF, size)
    w = f.measureText(text)
    if w > max_w:
        f = skia.Font(TF, size * max_w / w)
    return f


def draw_line(canvas, text, font, cx, baseline, stroke):
    w = font.measureText(text)
    x = cx - w / 2
    blob = skia.TextBlob.MakeFromString(text, font)
    sh = skia.Paint(AntiAlias=True, Color=SHADOW, Style=skia.Paint.kStrokeAndFill_Style,
                    StrokeWidth=stroke, StrokeJoin=skia.Paint.kRound_Join,
                    MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 7))
    canvas.drawTextBlob(blob, x + 4, baseline + 6, sh)
    ol = skia.Paint(AntiAlias=True, Color=OUTLINE, Style=skia.Paint.kStroke_Style,
                    StrokeWidth=stroke, StrokeJoin=skia.Paint.kRound_Join, StrokeCap=skia.Paint.kRound_Cap)
    canvas.drawTextBlob(blob, x, baseline, ol)
    canvas.drawTextBlob(blob, x, baseline, skia.Paint(AntiAlias=True, Color=WHITE))


def render(fn):
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.Color(0, 0, 0, 0))
    box = fn(c)
    arr = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType,
                                            alphaType=skia.kUnpremul_AlphaType)
    x0, y0, x1, y1 = box
    return (x0, y0, arr[y0:y1, x0:x1].astype(np.float32) / 255.0)


LYRIC_BOTTOM = 1235  # 세로 64% (아래 25%는 쇼츠 UI)


def lyric(ko, en):
    def fn(c):
        fk = fit_font(ko, 88, MAX_W)
        fe = fit_font(en, 54, MAX_W)
        be = LYRIC_BOTTOM - 22
        bk = be - 54 - 34
        draw_line(c, ko, fk, W / 2, bk, 16)
        draw_line(c, en, fe, W / 2, be, 11)
        return (60, bk - 120, W - 60, LYRIC_BOTTOM + 30)
    return render(fn)


def step(ko, en):
    def fn(c):
        fk = fit_font(ko, 60, 620)
        fe = fit_font(en, 40, 620)
        wk, we = fk.measureText(ko), fe.measureText(en)
        pw = max(wk, we) + 90
        top = 230  # 세로 12%
        ph = 160
        r = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(W / 2 - pw / 2, top, pw, ph), 52, 52)
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=SHADOW,
                                  MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 8)))
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=PILL))
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=WHITE, Style=skia.Paint.kStroke_Style, StrokeWidth=5))
        draw_line(c, ko, fk, W / 2, top + 78, 10)
        draw_line(c, en, fe, W / 2, top + 132, 7)
        return (int(W / 2 - pw / 2 - 30), top - 30, int(W / 2 + pw / 2 + 30), top + ph + 40)
    return render(fn)


# (시작, 끝, 그림)  ─ 기획안 [8] 가사 시점 그대로, 긴 가사는 노래 프레이즈 단위로 반씩 나눔
LYRICS = [
    (0.0, 3.0, "뽀득뽀득 손 씻자", "Scrub, scrub, wash!"),
    (3.0, 6.0, "거품 친구 나와라!", "Bubble friends, come out!"),
    (6.0, 8.0, "물을 묻혀 졸졸졸", "Wet hands, drip drop!"),
    (8.0, 10.0, "비누 거품 몽글몽글", "Fluffy soap bubbles!"),
    (10.0, 13.0, "손바닥을 싹싹싹", "Rub, rub, palms!"),
    (13.0, 16.0, "손등도 쓱쓱쓱", "Backs of hands, too!"),
    (16.0, 18.0, "손가락 사이사이", "In between fingers,"),
    (18.0, 20.0, "꼼꼼하게 뽀득뽀득", "scrub, squeaky clean!"),
    (20.0, 22.0, "물로 헹궈 쏴아아", "Rinse with water!"),
    (22.0, 24.0, "흙먼지야 안녕~", "Bye-bye, dust!"),
    (24.0, 27.0, "수건으로 톡톡톡", "Pat, pat, pat dry!"),
    (27.0, 30.0, "손 씻기 끝! 짝짝짝", "All clean! Clap, clap!"),
]
STEPS = [
    (10.0, 13.0, "1 손바닥", "1 Palms"),
    (13.0, 16.0, "2 손등", "2 Backs"),
    (16.0, 20.0, "3 손가락 사이", "3 Fingers"),
    (20.0, 24.0, "4 헹구기", "4 Rinse"),
    (24.0, 30.0, "5 닦기", "5 Dry"),
]
FADE = 0.2


def build_overlays():
    items = []
    for table, make in ((LYRICS, lyric), (STEPS, step)):
        starts = {round(s, 3) for s, *_ in table}
        ends = {round(e, 3) for _, e, *_ in table}
        for s, e, k, en in table:
            fi = s > 0 and round(s, 3) not in ends
            fo = e < DUR and round(e, 3) not in starts
            items.append((s, e, make(k, en), fi, fo))
    return items


def alpha_at(t, s, e, fade_in, fade_out):
    # 바로 이어지는 자막끼리는 글자만 바꾸고(깜박임 방지), 앞뒤가 비어 있을 때만 페이드.
    # 처음(0초)과 끝(30초)은 루프 이음매라 페이드 없이 그대로 둔다.
    a_in = min(1.0, (t - s) / FADE) if fade_in else 1.0
    a_out = min(1.0, (e - t) / FADE) if fade_out else 1.0
    return max(0.0, min(a_in, a_out))


def composite(frame, overlays, t):
    for s, e, (x0, y0, rgba), fi, fo in overlays:
        if not (s <= t < e):
            continue
        a = alpha_at(t, s, e, fi, fo)
        if a <= 0:
            continue
        h, w = rgba.shape[:2]
        reg = frame[y0:y0 + h, x0:x0 + w].astype(np.float32)
        al = rgba[..., 3:4] * a
        frame[y0:y0 + h, x0:x0 + w] = (reg * (1 - al) + rgba[..., :3] * 255 * al + 0.5).astype(np.uint8)
    return frame


# ───────────────────────── 5) 실행 ─────────────────────────
def main():
    print("font:", FONT_PATH if FONT_PATH.exists() else "Apple SD Gothic Neo (대체)")
    af = build_audio()
    overlays = build_overlays()
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(RAW), "-frames:v", str(NFRAMES),
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(MIX),
        "-map", "0:v", "-map", "1:a", "-af", af + ",aresample=48000",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", str(DUR), "-movflags", "+faststart", str(OUT),
    ], stdin=subprocess.PIPE)
    size = W * H * 3
    for i in range(NFRAMES):
        buf = dec.stdout.read(size)
        if len(buf) < size:
            raise SystemExit(f"raw 프레임 부족: {i}")
        img = Image.frombuffer("RGB", (W, H), buf)
        img = fix_frame(i, img.copy())
        frame = np.array(img)
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
