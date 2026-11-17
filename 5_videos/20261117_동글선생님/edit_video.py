#!/usr/bin/env python3
"""
20261117_동글선생님 후처리 (scripts/assemble_video.py가 만든 _raw.mp4 → 최종본)

  1) 반주 합성: 새로 만든 멜로디(120BPM, F장조, 40초 = 4/4 20마디)를 실로폰·우쿨렐레풍 뜯는 소리·
     베이스·셰이커·작은 박수로 numpy 합성 → bgm_synth.wav (노래 목소리 없음, 원본 멜로디 아님)
     루프 구조: 40초 버퍼를 원형으로 써서 끝(39초대) 음의 여운이 0초로 이어진다. 끝 페이드 없음.
     마디선은 홀수 초(1, 3, 5 …)에 있고, 39~41초 마디가 루프 이음매를 가로지른다
     ("또 똑똑똑?"(39.0~40.0) → 다음 재생 0.7초 클립 노크 → 1~3초 전주 → 3초 후렴).
  2) 소리 섞기: 클립 효과음(노크·끼익·뿅·웃음·손뼉) + 반주 → loudnorm 2패스(-14 LUFS, TP -1.5)
  3) 화면 손질 (프레임 번호 기준, 30fps, 총 1200프레임)
     - 0~74 (0.0~2.5초, 클립 _1 첫 클로즈업): 1.20배 확대에서 1.0배로 천천히 빠지는 줌.
       클립 _5 끝 클로즈업(얼굴이 더 크게 잡힘)과 0.0초 프레임의 얼굴 크기를 가깝게 맞춰 루프 이음매를 부드럽게 한다.
       AI 생성 표시(오른쪽 아래 반짝이)는 확대 중에도 화면 안에 남게 한다.
  4) 자막: 한글 한 줄 + 영어 한 줄(작게). 제목은 상단 13~22%. 가사는 샷마다 콩이 얼굴을 피해
     위(13~22%) 또는 아래(55~64%)에 둔다. "씩씩해요!"는 스티커 클로즈업 샷에서만.
     부드러운 페이드(0.2초)만 사용, 깜박임 없음. 0초 제목과 40초 끝 가사는 루프 이음매라 페이드 없음.
  5) 인코딩: 1080x1920, 30fps, H.264 + AAC, +faststart

다시 실행해도 같은 결과가 나온다 (난수 시드 고정).
실행: .venv/bin/python 5_videos/20261117_동글선생님/edit_video.py
"""

import json
import subprocess
import wave
from pathlib import Path

import numpy as np
import skia
from PIL import Image

FONT_PATH = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Pretendard-ExtraBold.otf"

HERE = Path(__file__).resolve().parent
BASE = "20261117_동글선생님"
RAW = HERE / f"{BASE}_raw.mp4"
OUT = HERE / f"{BASE}.mp4"
BGM = HERE / "bgm_synth.wav"
MIX = HERE / "mix_tmp.wav"
W, H, FPS, DUR = 1080, 1920, 30, 40.0
NFRAMES = int(DUR * FPS)
SR = 48000
N = int(DUR * SR)
AUDIO_CUTS = (8.0, 16.0, 24.0, 32.0)  # edit.json 클립 길이 8초 x 5

# ───────────────────────── 1) 반주 합성 ─────────────────────────
BPM = 120
BEAT = 60 / BPM
NOTE_IDX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(name):
    base = NOTE_IDX[name[0]]
    if name[1] == "b":
        base -= 1
    return 12 * (int(name[-1]) + 1) + base


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


# 후렴 네 줄 (각 4박). 음, 박
CH1 = [("C5", .5), ("C5", .5), ("C5", .5), ("A4", .5), ("A4", .5), ("A4", .5), ("G4", .5), ("C5", .5)]   # 똑똑똑 똑똑똑 누구세요?
CH2 = [("D5", .5), ("D5", .5), ("C5", .5), ("Bb4", .5), ("A4", .5), ("G4", .5), ("A4", 1)]              # 동글동글 선생님 왔어요!
CH3 = [("F4", .5), ("A4", .5), ("F4", .5), ("A4", .5), ("C5", .5), ("A4", .5), ("G4", 1)]               # 콩닥콩닥 내 마음, 하나 둘 셋
CH4 = [("A4", .5), ("G4", .5), ("A4", .5), ("G4", .5), ("F4", .5), ("G4", .5), ("F4", 1)]               # 괜찮아 괜찮아 웃어 봐요!


def faster(line, k=0.75):  # 후렴 3: 같은 음, 리듬만 3/4로 (한 줄 3박)
    return [(n, b * k) for n, b in line]


MELODY = (
    [("R", 2)]                                                                       # 0~1  노크(클립 소리)
    + [("F5", .5), ("C5", .5), ("A4", .5), ("C5", .5), ("F5", 1), ("R", 1)]          # 1~3  전주
    + CH1 + CH2 + CH3 + CH4                                                          # 3~11 후렴 1
    + [("F4", .5), ("G4", .5), ("A4", .5), ("C5", .5), ("A4", 1), ("G4", 1),         # 11~15 청진기로 배를 콕,
       ("A4", .5), ("A4", .5), ("A4", .5), ("R", .5), ("C5", .5), ("C5", .5), ("C5", 1)]  # 간질간질 하하하
    + CH1 + CH2                                                                      # 15~19 후렴 2
    + [("C5", 2), ("A4", .5), ("G4", .5), ("F4", 1),                                 # 19~23 아~ 하고 입을 쩍,
       ("G4", .5), ("A4", .5), ("Bb4", .5), ("A4", .5), ("G4", 2)]                   # 혀가 쏙 나왔네
    + [("A4", .5), ("Bb4", .5), ("C5", .5), ("D5", .5), ("C5", 1), ("A4", 1),        # 23~27 귀를 살짝 들여다봐,
       ("G4", .5), ("G4", .5), ("G4", .5), ("R", .5), ("E5", .5), ("E5", .5), ("E5", 1)]  # 간질간질 히히히
    + [("C5", .5), ("A4", .5), ("C5", .5), ("F5", .5), ("E5", .5), ("D5", .5), ("C5", 1),  # 27~31 씩씩한 콩이에게
       ("D5", .5), ("C5", .5), ("A4", .5), ("G4", .5), ("F5", 2)]                    # 별 하나 반짝!
    + faster(CH1) + faster(CH2) + faster(CH3) + faster(CH4)                          # 31~37 후렴 3
    + [("A4", .5), ("G4", .5), ("F4", .5), ("G4", .5), ("A4", 2)]                    # 37~39 이불 속에 쏙~
    + [("G4", .5), ("C5", .5), ("C5", .5), ("C5", .5)]                               # 39~40 또 똑똑똑? (딸림음, 질문)
)
# 1초마다 화음 40개 (0초 = 루프를 가로지르는 C 마디의 뒷부분)
CHORDS = ("C  F F  F F  Bb F  F C  C F  F F  F C  F F  Bb F  F F  Gm C  Bb F  C C  F C  Gm F"
          "  F F Bb F C F  F F  C").split()
VOICING = {
    "F": (["A3", "C4", "F4"], "F2"), "Bb": (["Bb3", "D4", "F4"], "Bb2"),
    "C": (["G3", "C4", "E4"], "C3"), "Gm": (["G3", "Bb3", "D4"], "G2"),
}


def add(buf, start, sig):
    """원형 버퍼에 더하기: 40초를 넘는 여운은 0초 쪽으로 감겨 루프가 끊기지 않는다."""
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


def pluck(f, length=0.9):
    return env_tone(f, length, 5.0, [(k, 1.0 / k, 0.6 + 0.5 * k) for k in range(1, 7)], attack=0.002)


def bass(f, length=0.9):
    return env_tone(f, length, 3.0, [(1, 1.0, 1), (2, 0.25, 2)], attack=0.01)


def noise_burst(rng, length, decay, smooth):
    n = rng.standard_normal(int(length * SR))
    if smooth > 1:
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
        i = int(d * SR)
        b = noise_burst(rng, 0.2, 35 if k == 2 else 120, 3)
        out[i:i + len(b)] += b[: len(out) - i]
    return out / (np.abs(out).max() + 1e-9)


def synth_bgm():
    rng = np.random.default_rng(20261117)
    lead, uke, low, perc = (np.zeros(N) for _ in range(4))

    t = 0.0
    for name, beats in MELODY:
        d = beats * BEAT
        if name != "R":
            add(lead, t, xylophone(hz(midi(name)), d))
            add(lead, t, 0.35 * xylophone(hz(midi(name) + 12), d))
        t += d
    assert abs(t - DUR) < 1e-6, t
    assert len(CHORDS) == 40, len(CHORDS)

    for ci, ch in enumerate(CHORDS):
        tones, root = VOICING[ch]
        for b in range(2):
            tb = ci * 1.0 + b * BEAT
            gain = 1.0 if b == 0 else 0.7
            for k, nm in enumerate(tones):
                add(uke, tb + 0.012 * k, gain * pluck(hz(midi(nm))))
            add(uke, tb + BEAT / 2, 0.35 * pluck(hz(midi(tones[-1])), 0.5))
        add(low, ci * 1.0, bass(hz(midi(root))))

    shaker = noise_burst(rng, 0.08, 60, 1)
    shaker /= np.abs(shaker).max()
    cl = clap(rng)
    for b in range(int(DUR / BEAT)):
        tb = b * BEAT
        add(perc, tb + BEAT / 2, 0.5 * shaker)
        # 2·4박(=x.5초) 작은 박수. 0~3초(노크·전주)는 비워 노크가 잘 들리게.
        if tb >= 3.0 and abs(tb % 1.0 - 0.5) < 1e-6:
            add(perc, tb, 0.45 * cl)

    mix = 0.36 * lead / np.abs(lead).max() + 0.20 * uke / np.abs(uke).max() \
        + 0.24 * low / np.abs(low).max() + 0.10 * perc / np.abs(perc).max()
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
    out = np.zeros((N, 2))
    out[: min(len(a), N)] = a[:N]
    return out


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def build_audio():
    bgm = synth_bgm()
    write_wav(BGM, bgm)
    sfx = read_clip_audio()
    r = int(0.01 * SR)
    for tc in AUDIO_CUTS:  # 클립 이음매 ±10ms 페이드
        c = int(tc * SR)
        sfx[c - r:c] *= np.linspace(1, 0, r)[:, None]
        sfx[c:c + r] *= np.linspace(0, 1, r)[:, None]
    # 루프 이음매(40→0)도 효과음만 ±10ms 페이드 (반주는 원형이라 그대로 이어짐)
    sfx[:r] *= np.linspace(0, 1, r)[:, None]
    sfx[-r:] *= np.linspace(1, 0, r)[:, None]
    bgm_g = 10 ** ((-20 - rms_db(bgm)) / 20)
    sfx_g = 10 ** ((-27 - rms_db(sfx)) / 20)
    mix = bgm * bgm_g + sfx * sfx_g
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    write_wav(MIX, mix)
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
    cw, chh = W / factor, H / factor
    x0, y0 = (W - cw) * ax, (H - chh) * ay
    return img.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + chh))


# 0초에 1.2배 → 2.5초에 1.0배. 얼굴 크기를 클립 _5 끝 클로즈업(약 1.3배 큼)에 가깝게 맞춘다.
# 오른쪽 아래 AI 생성 표시(Gemini 반짝이, 원본 좌표 약 x 900 / y 1740)가 확대 중에도 화면 밖으로 잘리지 않게
# 배율을 1.2배로 제한하고 기준점을 아래쪽(ay 0.62)으로 둔다. (1.3배·ay 0.26으로 하면 표시가 잘려서 바꿈)
LOOP_ZOOM, LOOP_ZOOM_END = 1.20, 2.5
LOOP_AX, LOOP_AY = 0.5, 0.62


def fix_frame(i, img):
    t = i / FPS
    if t < LOOP_ZOOM_END:
        u = t / LOOP_ZOOM_END
        e = 0.5 - 0.5 * np.cos(np.pi * u)  # 부드러운 가감속
        f = LOOP_ZOOM + (1.0 - LOOP_ZOOM) * e
        if f > 1.001:
            img = zoom(img, f, LOOP_AX, LOOP_AY)
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
SKY = skia.Color(44, 128, 200)          # 하늘색 테두리 (밝은 벽에서도 읽히도록 조금 진하게)
ORANGE = skia.Color(232, 110, 40)       # 제목 테두리 (선생님 나비넥타이 색)
SHADOW = skia.Color(20, 50, 90, 150)
PILL = skia.Color(255, 196, 40, 235)    # "씩씩해요!" 배경 (별 노랑)
MAX_W = 820                              # 가로 중앙 기준 → 오른쪽 끝 950px 안쪽


def fit_font(text, size, max_w):
    f = skia.Font(TF, size)
    w = f.measureText(text)
    if w > max_w:
        f = skia.Font(TF, size * max_w / w)
    return f


def draw_line(canvas, text, font, cx, baseline, stroke, outline=SKY, fill=WHITE):
    w = font.measureText(text)
    x = cx - w / 2
    blob = skia.TextBlob.MakeFromString(text, font)
    sh = skia.Paint(AntiAlias=True, Color=SHADOW, Style=skia.Paint.kStrokeAndFill_Style,
                    StrokeWidth=stroke, StrokeJoin=skia.Paint.kRound_Join,
                    MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 7))
    canvas.drawTextBlob(blob, x + 4, baseline + 6, sh)
    ol = skia.Paint(AntiAlias=True, Color=outline, Style=skia.Paint.kStroke_Style,
                    StrokeWidth=stroke, StrokeJoin=skia.Paint.kRound_Join, StrokeCap=skia.Paint.kRound_Cap)
    canvas.drawTextBlob(blob, x, baseline, ol)
    canvas.drawTextBlob(blob, x, baseline, skia.Paint(AntiAlias=True, Color=fill))


def render(fn):
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.Color(0, 0, 0, 0))
    box = fn(c)
    arr = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType,
                                            alphaType=skia.kUnpremul_AlphaType)
    x0, y0, x1, y1 = box
    return (x0, y0, arr[y0:y1, x0:x1].astype(np.float32) / 255.0)


LYRIC_BOTTOM = 1235  # 아래 위치: 세로 64%까지 (아래 25%는 쇼츠 UI)
HIGH_TOP = 250       # 위 위치: 세로 13% (0~3초 제목과 같은 자리)


def lyric(ko, en, pos="low"):
    """pos="low": 세로 55~64%, pos="high": 세로 13~22%. 샷마다 콩이 얼굴을 가리지 않는 쪽을 고른다."""
    def fn(c):
        fk = fit_font(ko, 84, MAX_W)
        fe = fit_font(en, 50, MAX_W)
        if pos == "high":
            bk = HIGH_TOP + 90
            be = bk + 50 + 34
        else:
            be = LYRIC_BOTTOM - 22
            bk = be - 50 - 34
        draw_line(c, ko, fk, W / 2, bk, 16)
        draw_line(c, en, fe, W / 2, be, 11)
        return (60, bk - 120, W - 60, be + 52)
    return render(fn)


def title(ko, en):
    def fn(c):
        top = 250  # 세로 13%
        fk = fit_font(ko, 104, MAX_W)
        fe = fit_font(en, 56, MAX_W)
        draw_line(c, ko, fk, W / 2, top + 100, 20, outline=ORANGE)
        draw_line(c, en, fe, W / 2, top + 180, 12, outline=ORANGE)
        return (40, top - 20, W - 40, top + 240)
    return render(fn)


BRAVE_CX, BRAVE_TOP = 600, 640  # "씩씩해요!" 작은 표시 (가로 56%, 세로 33%: 손등 별 위쪽)


def brave(ko, en):
    def fn(c):
        fk = fit_font(ko, 56, 420)
        fe = fit_font(en, 36, 420)
        pw = max(fk.measureText(ko), fe.measureText(en)) + 70
        ph = 136
        r = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(BRAVE_CX - pw / 2, BRAVE_TOP, pw, ph), 48, 48)
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=SHADOW,
                                  MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 8)))
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=PILL))
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=WHITE, Style=skia.Paint.kStroke_Style, StrokeWidth=5))
        draw_line(c, ko, fk, BRAVE_CX, BRAVE_TOP + 66, 10, outline=ORANGE)
        draw_line(c, en, fe, BRAVE_CX, BRAVE_TOP + 114, 7, outline=ORANGE)
        return (int(BRAVE_CX - pw / 2 - 30), BRAVE_TOP - 30, int(BRAVE_CX + pw / 2 + 30), BRAVE_TOP + ph + 40)
    return render(fn)


K1 = ("똑똑똑 똑똑똑 누구세요?", "Knock knock, knock knock, who's there?")
K2 = ("동글동글 선생님 왔어요!", "Round little Doctor Dongle is here!")
K3 = ("콩닥콩닥 내 마음, 하나 둘 셋", "Thump-thump goes my heart, one, two, three")
K4 = ("괜찮아 괜찮아 웃어 봐요!", "It's okay, it's okay, let's smile!")
# 반주 마디(2초)에 맞춘 가사 시점. 편집자 메모 표와의 차이는 편집 기록 [4]에 적음.
LYRICS = [
    # 3~11초 (문틈 → 와이드, 콩이 얼굴이 화면 아래쪽 55~60%) → 위
    (3.0, 5.0, *K1, "high"), (5.0, 7.0, *K2, "high"), (7.0, 9.0, *K3, "high"), (9.0, 11.0, *K4, "high"),
    # 11~16초 (곰인형 옆 미디엄·클로즈업, 얼굴이 위쪽) → 아래
    (11.0, 15.0, "청진기로 배를 콕, 간질간질 하하하", "A stethoscope boop on my tummy, tickle-tickle, ha-ha-ha!", "low"),
    (15.0, 16.0, *K1, "low"),
    # 16~23초 (침대에 셋이 앉은 와이드, 콩이 얼굴 55~60%) → 위. 같은 줄도 16초 컷에서 자리를 옮김
    (16.0, 17.0, *K1, "high"),
    (17.0, 19.0, *K2, "high"),
    (19.0, 23.0, "아~ 하고 입을 쩍, 혀가 쏙 나왔네", 'Say "Ahh" and open wide, out pops my tongue!', "high"),
    # 23~31초 (귀·이마·스티커, 얼굴이 위쪽) → 아래
    (23.0, 27.0, "귀를 살짝 들여다봐, 간질간질 히히히", "A little peek inside my ear, tickle-tickle, hee-hee-hee!", "low"),
    (27.0, 31.0, "씩씩한 콩이에게 별 하나 반짝!", "A shiny star for brave Kongi!", "low"),
    # 31~40초 (손뼉 와이드, 콩이 얼굴 55~60% / 끝 클로즈업은 고래 그림 위) → 위
    (31.0, 32.5, *K1, "high"), (32.5, 34.0, *K2, "high"), (34.0, 35.5, *K3, "high"), (35.5, 37.0, *K4, "high"),
    (37.0, 40.0, "이불 속에 쏙~ 또 똑똑똑?", "Back under the blanket... knock knock again?", "high"),
]
TITLES = [(0.0, 3.0, "똑똑똑! 동글 선생님", "Knock Knock! Doctor Dongle")]
# 별 스티커 클로즈업 샷(26.97~28.97초) 안에서만 표시. 다음 미디엄 샷에선 콩이 머리를 가려서 뺌.
BRAVES = [(27.5, 28.95, "씩씩해요!", "So brave!")]
FADE = 0.2


def build_overlays():
    items = []
    for table, make in ((LYRICS, lyric), (TITLES, title), (BRAVES, brave)):
        starts = {round(row[0], 3) for row in table}
        ends = {round(row[1], 3) for row in table}
        for s, e, *args in table:
            # 바로 이어지는 자막끼리는 글자만 바꿈(깜박임 방지). 위↔아래 자리가 바뀌는 곳도 컷 지점이라 그대로 바꿈.
            fi = s > 0 and round(s, 3) not in ends
            fo = e < DUR and round(e, 3) not in starts
            items.append((s, e, make(*args), fi, fo))
    return items


def alpha_at(t, s, e, fade_in, fade_out):
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
