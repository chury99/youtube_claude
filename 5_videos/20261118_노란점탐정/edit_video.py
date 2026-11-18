#!/usr/bin/env python3
"""
20261118_노란점탐정 후처리 (scripts/assemble_video.py가 만든 _raw.mp4 → 최종본)

  [36초 버전] 생성 오류 구간을 잘라 35.77초(1073프레임)로 줄였다 (edit.json 7개 구간):
     _2 6.625~6.667초(오리가 사라지는 디졸브 1프레임) 제거, _3 6.417초~끝(컵→치약 튜브 변신·"Solsol" 튜브) 제거,
     _5 3.708~6.042초(사람 아기가 옥수수를 건네는 구간) 제거. _4 오른쪽 끝 사람 손은 흐림 처리.
  1) 반주 합성: 새로 만든 멜로디(G장조, 4/4 기준 72박 = 영상길이/72 ≈ 0.497초/박 ≈ 121BPM)를
     실로폰·피치카토(뜯는 현)·우쿨렐레풍 화음·베이스·셰이커로 numpy 합성 → bgm_synth.wav
     (노래 목소리 없음, 원본 영상 멜로디 아님, 외부 음원 없음)
     - 구간별 박 수: 클립1 16박 / 클립2 16박(살금살금 피치카토) / 클립3 13박(4+4+5박) / 클립4 16박(치카치카 후렴 2회)
       / 클립5 11박(4+4+3박). 40초 버전의 11마디·18마디를 빼고 끝 마디를 줄였다.
     - 루프: 버퍼를 원형으로 써서 끝 음의 여운이 0초로 감긴다. 마지막 마디 끝 "어? 어?"(D5 두 번)가
       1마디 첫 소절 "어? 어?"(D5 두 번)로 돌림노래처럼 이어진다. 페이드아웃 없음.
  2) 소리 섞기: 클립 효과음 + 반주 → 효과음 피크 리미터 → loudnorm 2패스(-14 LUFS, TP -1.5)
  3) 화면 손질 (출력 30fps 기준, 구간 프레임 수는 raw 실측)
     - AI가 화면에 그려 넣은 글자 흐림 처리: 캐릭터 이름 글자(Alkong, Quacky, Solsol, Allkong, Norong),
       실제 치약 상표와 비슷하게 생긴 치약 튜브 글자(클립 _1), "Solsol" 치약 튜브 글자(클립 _3),
       볼에 희미하게 그려진 글자·오른쪽 끝 사람 손(클립 _4). Veo 워터마크(오른쪽 아래 "Veo")는 건드리지 않는다.
     - 루프 마감: 마지막 0.2초 동안 완성본 0프레임(흐림 처리·제목 포함 전) 그림으로 서서히 겹쳐
       끝 프레임이 첫 프레임과 거의 같아지게 한다. 암전·페이드아웃 없음.
  4) 자막: Pretendard ExtraBold, 한국어 위(크게)·영어 아래(작게). 세로 12~65% 안, 가로 중앙.
     가사는 대부분 위(13~22%), 0~3초만 제목이 위에 있어 가사를 아래(55~64%)에.
     용의자 이름표와 "범인은 나?!"는 작은 알약 모양. 부드러운 0.15초 페이드만, 깜박임 없음.
  5) 인코딩: 720x1280, 30fps, H.264 + AAC 48kHz, +faststart

다시 실행해도 같은 결과가 나온다 (난수 시드 고정).
실행: .venv/bin/python 5_videos/20261118_노란점탐정/edit_video.py
"""

import json
import subprocess
import wave
from pathlib import Path

import numpy as np
import skia
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
FONT_PATH = ROOT / "assets" / "fonts" / "Pretendard-ExtraBold.otf"

HERE = Path(__file__).resolve().parent
BASE = "20261118_노란점탐정"
RAW = HERE / f"{BASE}_raw.mp4"
OUT = HERE / f"{BASE}.mp4"
BGM = HERE / "bgm_synth.wav"
MIX = HERE / "mix_tmp.wav"
W, H, FPS = 720, 1280, 30
# edit.json 구간: (클립 번호 0~4 = 프롬프트 _1~_5, 원본 시작초, raw 안 프레임 수) — 프레임 수는 raw 장면 전환 실측
SEGS = [
    (0, 0.0, 238),       # _1 전체
    (1, 0.0, 199),       # _2 0~6.625 (오리 사라지는 디졸브 프레임 앞까지)
    (1, 6.6667, 38),     # _2 6.667~끝
    (2, 0.0, 193),       # _3 0~6.417 (컵이 치약 튜브로 바뀌기 전까지)
    (3, 0.0, 238),       # _4 전체
    (4, 0.0, 111),       # _5 0~3.708 (사람 아기 등장 전까지)
    (4, 6.0417, 56),     # _5 6.042~끝 (아기 팔이 빠진 뒤 "냠" → 노란 점)
]
SEG_START = [sum(n for *_, n in SEGS[:k]) for k in range(len(SEGS))]
NFRAMES = sum(n for *_, n in SEGS)     # 1073
DUR = NFRAMES / FPS                    # 35.767초
CLIP_START_F = {}
for (ci, _, _), f0 in zip(SEGS, SEG_START):
    CLIP_START_F.setdefault(ci, f0)
OFF = [CLIP_START_F[k] / FPS for k in range(5)]   # 각 클립이 시작하는 완성본 시각
EAT = SEG_START[6] / FPS                           # _5 "냠" 구간 시작
SR = 48000
N = int(round(DUR * SR))
AUDIO_CUTS = [f / FPS for f in SEG_START[1:]]

# ───────────────────────── 1) 반주 합성 ─────────────────────────
TOTAL_BEATS = 72
BEAT = DUR / TOTAL_BEATS
BAR = 4 * BEAT
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


CHORUS_B1 = [("G4", .5), ("B4", .5), ("G4", .5), ("B4", .5), ("C5", .5), ("E5", .5), ("D5", 1)]   # 치카치카 위아래, 동글동글 앞뒤로
CHORUS_B2 = [("D5", .5), ("D5", .5), ("E5", .5), ("D5", .5), ("B4", .5), ("A4", .5), ("G4", 1)]   # 뽀글뽀글 하나 둘 셋, 노란 점 안녕!

# (음, 박, 악기) 악기: x=실로폰, p=피치카토
BARS = [
    # 클립 1 (마디 1~4): 훅 + 후렴 A
    [("D5", .5), ("R", .5), ("D5", .5), ("R", .5), ("B4", .5), ("B4", .5), ("G4", 1)],          # 어? 어? 노란 점!
    [("A4", .5), ("A4", .5), ("B4", .5), ("A4", .5), ("G4", 1), ("R", 1)],                      # 누가 그랬지?
    [("B4", .5), ("B4", .5), ("D5", .5), ("B4", .5), ("A4", .5), ("A4", .5), ("G4", 1)],        # 누구야 누구야 노란 점 누구야?
    [("E5", .5), ("D5", .5), ("B4", .5), ("D5", .5), ("A4", 1), ("D5", 1)],                     # 반짝 손전등, 탐정 또롱이 출동!
    # 클립 2 (마디 5~8): 살금살금 탐정 피치카토 (E단조 느낌)
    [("E4", .5, "p"), ("R", .5), ("G4", .5, "p"), ("R", .5), ("B4", .5, "p"), ("R", .5), ("A4", 1, "p")],
    [("G4", .5, "p"), ("R", .5), ("B4", .5, "p"), ("R", .5), ("D5", .5, "p"), ("R", .5), ("C5", 1, "p")],
    [("B4", .5, "p"), ("R", .5), ("D5", .5, "p"), ("R", .5), ("E5", .5, "p"), ("D5", .5, "p"), ("B4", 1, "p")],
    [("A4", .5, "p"), ("B4", .5, "p"), ("C5", .5, "p"), ("A4", .5, "p"), ("B4", 1.5, "p"), ("R", .5)],  # 그럼 누구지?
    # 클립 3 (13박): 하품 → 반전 "범인은 바로 나~" (40초판 11마디 빼고, 끝 마디를 5박으로)
    [("G4", 1.5), ("A4", .5), ("B4", 1), ("R", 1)],
    [("D5", .5), ("C5", .5), ("B4", .5), ("A4", .5), ("G4", 1), ("E4", 1)],
    [("A4", .5), ("B4", .5), ("C5", .5), ("D5", .5), ("D5", 3)],
    # 클립 4 (마디 13~16): 후렴 B 2회
    CHORUS_B1, CHORUS_B2, CHORUS_B1, CHORUS_B2,
    # 클립 5 (11박): 후렴 A 변형 → 끝 소절 → 첫 소절로 돌림 (40초판 18마디 빼고, 끝 마디를 3박으로)
    [("B4", .5), ("B4", .5), ("D5", .5), ("B4", .5), ("A4", .5), ("B4", .5), ("G4", 1)],        # 범인 찾았다! 치카치카 해결!
    [("D5", 1), ("B4", 1), ("A4", .5), ("B4", .5), ("G4", 1)],                                  # 반짝반짝 내 이, 냠냠
    [("A4", .5), ("G4", .5), ("D5", .5), ("R", .5), ("D5", .5), ("R", .5)],                      # 맛있다~ 어? 어?
]
# 화음 (이름, 박 수)
CHORDS = ([(c, 2) for c in "G G D G G Em C D".split()]                 # 클립 1: 16박
          + [(c, 2) for c in "Em Em Em C Em C Am D".split()]          # 클립 2: 16박 (살금살금)
          + [("G", 2), ("G", 2), ("G", 2), ("Em", 2), ("Am", 2), ("D", 3)]  # 클립 3: 13박
          + [(c, 2) for c in "G C D G G C D G".split()]               # 클립 4: 16박
          + [("G", 2), ("G", 2), ("G", 2), ("G", 2), ("D", 3)])       # 클립 5: 11박
SNEAKY = (16, 32)   # 클립 2 박 범위
SPARK_BEATS = ((61, "G6"), (65, "B6"))   # 클립 5 첫 박, "반짝반짝" 첫 박
VOICING = {
    "G": (["B3", "D4", "G4"], "G2"), "D": (["A3", "D4", "F#4"], "D3"),
    "Em": (["B3", "E4", "G4"], "E2"), "C": (["C4", "E4", "G4"], "C3"),
    "Am": (["A3", "C4", "E4"], "A2"),
}


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


def noise_burst(rng, length, decay):
    n = np.diff(rng.standard_normal(int(length * SR)), prepend=0)
    t = np.arange(len(n)) / SR
    return n * np.exp(-t * decay)


def synth_bgm():
    rng = np.random.default_rng(20261118)
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
                if inst == "p":
                    add(lead, t, 1.1 * pizz(f))
                    add(lead, t, 0.3 * pizz(f * 2))
                else:
                    add(lead, t, xylophone(f, d))
                    add(lead, t, 0.35 * xylophone(f * 2, d))
            t += d
            bt += beats
        assert bt in (3, 4, 5), (bi, bt)
    assert abs(t - DUR) < 1e-6, t
    assert sum(b for _, b in CHORDS) == TOTAL_BEATS

    beat_pos = 0
    for ch, nb in CHORDS:
        tones, root = VOICING[ch]
        t0 = beat_pos * BEAT
        sneaky = SNEAKY[0] <= beat_pos < SNEAKY[1]  # 클립 2: 화음도 짧게 뜯기만
        beat_pos += nb
        for b in range(nb):
            tb = t0 + b * BEAT
            gain = (1.0 if b == 0 else 0.7) * (0.6 if sneaky else 1.0)
            for k, nm in enumerate(tones):
                fn = pizz if sneaky else pluck
                add(uke, tb + 0.012 * k, gain * fn(hz(midi(nm))))
            if not sneaky:
                add(uke, tb + BEAT / 2, 0.35 * pluck(hz(midi(tones[-1])), 0.5))
        if sneaky:  # 살금살금 베이스: 반박마다 짧게
            for q in range(2 * nb):
                add(low, t0 + q * BEAT / 2, (0.8 if q % 2 == 0 else 0.5) * bass(hz(midi(root)), 0.25))
        else:
            add(low, t0, bass(hz(midi(root))))

    shaker = noise_burst(rng, 0.08, 60)
    shaker /= np.abs(shaker).max()
    for b in range(TOTAL_BEATS):
        tb = b * BEAT
        g = 0.25 if SNEAKY[0] <= b < SNEAKY[1] else 0.5
        add(perc, tb + BEAT / 2, g * shaker)

    # 반짝 효과음 (부드러운 벨): 클립 5 첫 박, "반짝반짝" 첫 박
    for b, nm in SPARK_BEATS:
        add(spark, b * BEAT, bell(hz(midi(nm))))
        add(spark, b * BEAT + BEAT / 2, 0.6 * bell(hz(midi(nm) + 7)))

    nz = lambda x: x / (np.abs(x).max() + 1e-9)
    mix = 0.36 * nz(lead) + 0.20 * nz(uke) + 0.24 * nz(low) + 0.09 * nz(perc) + 0.08 * nz(spark)
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
    """간단한 피크 리미터: 순간 피크(박수 등)만 눌러 효과음이 반주 위로 튀지 않게."""
    env = np.abs(x).max(axis=1)
    g = np.minimum(1.0, thr / (env + 1e-12))
    k = int(0.005 * SR)  # 5ms 최소값 필터 → 10ms 이동 평균
    gp = np.pad(g, (k, k), mode="edge")
    gmin = np.min(np.lib.stride_tricks.sliding_window_view(gp, 2 * k + 1), axis=1)
    sm = np.convolve(gmin, np.ones(2 * k) / (2 * k), mode="same")
    return x * np.minimum(sm, 1.0)[:, None]


def build_audio():
    bgm = synth_bgm()
    write_wav(BGM, bgm)
    sfx = read_clip_audio()
    r = int(0.01 * SR)
    for tc in AUDIO_CUTS:  # 클립 이음매 ±10ms 페이드
        c = int(round(tc * SR))
        sfx[c - r:c] *= np.linspace(1, 0, r)[:, None]
        sfx[c:c + r] *= np.linspace(0, 1, r)[:, None]
    sfx[:r] *= np.linspace(0, 1, r)[:, None]   # 루프 이음매(끝→처음)도 효과음만 페이드
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
    js = r.stderr[r.stderr.rfind("{"): r.stderr.rfind("}") + 1]
    m = json.loads(js)
    return ("loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:"
            f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}")


# ───────────────────────── 3) 화면 손질: 글자 흐림 ─────────────────────────
# (클립 번호 0~4 = 프롬프트 _1~_5, 클립 안 시작초, 끝초, (x0, y0, x1, y1) 720x1280 기준)
BLURS = [
    (0, 0.00, 5.55, (12, 278, 385, 358)),     # _1 "Alkong" "Quacky" 글자
    (0, 5.40, 6.80, (35, 245, 450, 335)),     # _1 클로즈업으로 바뀌며 남은 흐린 글자 자국
    (0, 0.00, 5.55, (560, 500, 720, 840)),    # _1 실제 상표처럼 보이는 치약 튜브 글자·로고
    (1, 0.00, 3.75, (22, 838, 165, 908)),     # _2 "Alkong" 글자 (위)
    (1, 0.00, 3.75, (22, 968, 178, 1042)),    # _2 "Alkong" 글자 (아래)
    (2, 6.375, 7.94, (548, 828, 664, 1105)),  # _3 치약 튜브 "Solsol" 글자 (컵이 튜브로 바뀌는 6.375초부터)
    (3, 0.00, 2.50, (580, 288, 720, 368)),    # _4 "Solsol" 글자
    (3, 0.00, 3.60, (182, 612, 302, 682)),    # _4 볼에 희미하게 그려진 글자
    (3, 6.80, 7.94, (232, 232, 612, 302)),    # _4 "Allkong" "Norong" 글자
    (3, 4.00, 7.94, (660, 620, 720, 800)),    # _4 오른쪽 끝에 보이는 사람 손 (쇼츠 UI 영역 안)
    (3, 4.00, 7.94, (674, 840, 720, 1090)),   # _4 오른쪽 끝 치약 튜브의 세로 글자
]
BLUR_RAMP = 0.12


def feather_mask(w, h, pad):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((pad, pad, w - pad, h - pad), radius=pad * 2, fill=255)
    return m.filter(ImageFilter.GaussianBlur(pad / 2))


def blur_frame(i, img):
    k = max(j for j in range(len(SEGS)) if SEG_START[j] <= i)
    ci, src0, nf = SEGS[k]
    t = src0 + (i - SEG_START[k]) / FPS          # 원본 클립 안 시각
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
        bl = region.filter(ImageFilter.GaussianBlur(14)).filter(ImageFilter.GaussianBlur(14))
        # 화면 가장자리에 닿는 상자는 가장자리 쪽 흐림이 옅어지지 않게, 화면 밖까지 늘린 마스크에서 잘라 쓴다
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


# ───────────────────────── 4) 자막 ─────────────────────────
def typeface():
    if FONT_PATH.exists():
        tf = skia.Typeface.MakeFromFile(str(FONT_PATH))
        if tf is not None:
            return tf
    return skia.Typeface("Apple SD Gothic Neo", skia.FontStyle.Bold())


TF = typeface()
WHITE = skia.Color(255, 255, 255)
MINT = skia.Color(22, 140, 150)          # 가사 테두리 (민트, 밝은 벽 위에서도 읽히게 진하게)
NAVY = skia.Color(30, 48, 110)           # 제목 테두리 (또롱이 망토 남색)
SHADOW = skia.Color(10, 40, 60, 150)
PILL = skia.Color(255, 205, 40, 240)     # 이름표 배경 (노랑)
MAX_W = 560                               # 가로 중앙 → 오른쪽 끝 640px (오른쪽 15% 쇼츠 UI 피함)


def fit_font(text, size, max_w):
    f = skia.Font(TF, size)
    w = f.measureText(text)
    if w > max_w:
        f = skia.Font(TF, size * max_w / w)
    return f


def draw_line(canvas, text, font, cx, baseline, stroke, outline=MINT, fill=WHITE):
    w = font.measureText(text)
    x = cx - w / 2
    blob = skia.TextBlob.MakeFromString(text, font)
    sh = skia.Paint(AntiAlias=True, Color=SHADOW, Style=skia.Paint.kStrokeAndFill_Style,
                    StrokeWidth=stroke, StrokeJoin=skia.Paint.kRound_Join,
                    MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 5))
    canvas.drawTextBlob(blob, x + 3, baseline + 4, sh)
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


CX = 320                 # 자막 가로 중심 (0~640 범위의 가운데: 오른쪽 15% UI 피함)
HIGH_TOP = 166           # 세로 13%
LOW_BOTTOM = 820         # 세로 64%


def wrap(text, font_size, max_w, min_size):
    """한 줄로 넣으면 글자가 min_size보다 작아질 때만 쉼표·느낌표·물음표 뒤에서 두 줄로 나눈다."""
    f = skia.Font(TF, font_size)
    if f.measureText(text) * min_size <= max_w * font_size:
        return [text]
    cands = [i + 1 for i, ch in enumerate(text) if ch in ",!?" and i + 1 < len(text) and text[i + 1] == " "]
    if not cands:
        return [text]
    mid = len(text) / 2
    cut = min(cands, key=lambda i: abs(i - mid))
    return [text[:cut].strip(), text[cut:].strip()]


def lyric(ko, en, pos="high"):
    """pos: high = 세로 13%부터, mid = 제목 아래 23%부터, low = 세로 64%에서 끝."""
    def fn(c):
        kl = wrap(ko, 52, MAX_W, 42)
        el = wrap(en, 31, MAX_W, 26)
        lines = [(t, 52, 11, 52 if i == 0 else 60) for i, t in enumerate(kl)] + [(t, 31, 7, 36) for t in el]
        total = sum(step for *_, step in lines)
        if pos == "high":
            y = HIGH_TOP + 56 - 52
        elif pos == "mid":
            y = 300
        else:
            y = LOW_BOTTOM - total
        y0 = y
        for t, size, stroke, step in lines:
            y += step
            draw_line(c, t, fit_font(t, size, MAX_W), CX, y - (0 if size == 52 else 4), stroke)
        return (10, int(y0 - 30), W - 10, int(y + 34))
    return render(fn)


def title(ko, en):
    def fn(c):
        top = HIGH_TOP
        fk = fit_font(ko, 66, MAX_W)
        fe = fit_font(en, 36, MAX_W)
        draw_line(c, ko, fk, CX, top + 64, 13, outline=NAVY)
        draw_line(c, en, fe, CX, top + 116, 8, outline=NAVY)
        return (10, top - 14, W - 10, top + 160)
    return render(fn)


def tag(ko, en, cx, top):
    def fn(c):
        fk = fit_font(ko, 34, 300)
        fe = fit_font(en, 24, 300)
        pw = max(fk.measureText(ko), fe.measureText(en)) + 40
        ph = 84
        x0 = min(max(cx - pw / 2, 14), 630 - pw)
        ccx = x0 + pw / 2
        r = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x0, top, pw, ph), 30, 30)
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=SHADOW,
                                  MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 6)))
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=PILL))
        c.drawRRect(r, skia.Paint(AntiAlias=True, Color=WHITE, Style=skia.Paint.kStroke_Style, StrokeWidth=4))
        draw_line(c, ko, fk, ccx, top + 40, 7, outline=NAVY)
        draw_line(c, en, fe, ccx, top + 70, 5, outline=NAVY)
        return (int(max(0, x0 - 20)), int(top - 20), int(min(W, x0 + pw + 20)), int(top + ph + 26))
    return render(fn)


A1 = ("누구야 누구야 노란 점 누구야?", "Who, who, who made the yellow spots?")
A2 = ("반짝 손전등, 탐정 또롱이 출동!", "Flashlight on! Detective Torongi, go!")
B1 = ("치카치카 위아래, 동글동글 앞뒤로", "Brush brush up and down, round and round, front and back")
B2 = ("뽀글뽀글 하나 둘 셋, 노란 점 안녕!", "Bubble bubble one two three, bye-bye spots!")
O1, O2, O3, O4 = OFF[1], OFF[2], OFF[3], OFF[4]
BARL = BAR
M4 = 45 * BEAT                                   # 반주 클립 4 구간(후렴 B) 시작
M5B = 65 * BEAT                                  # 반주 "반짝반짝 내 이" 마디 시작
SPOT = EAT + round((6.6 - SEGS[6][1]) * FPS) / FPS   # _5 원본 6.6초: 이마에 노란 점이 다시 생김
# (시작, 끝, 한국어, 영어, 위치) — 시점은 반주 마디(약 1.983초)와 클립 화면에 맞춤
LYRICS = [
    (0.3, 2 * BARL, "어? 어? 노란 점! 누가 그랬지?", "Huh? Huh? Yellow spots! Who did this?", "mid"),
    (2 * BARL, 3 * BARL, *A1, "high"),
    (3 * BARL, O1, *A2, "high"),
    (O1, O1 + 1.5, "옥수수? \"나 아니야~\"", "Corn? \"Not me~\"", "high"),
    (O1 + 1.5, O1 + 3.0, "노른자? \"나 아니야~\"", "Yolk? \"Not me~\"", "high"),
    (O1 + 3.0, O1 + 6.5, "오리? \"꽥! 나 아니야~\"", "Duck? \"Quack! Not me~\"", "high"),
    (O1 + 6.5, O2, "그럼 누구지?", "Then who?", "high"),
    (O2, O2 + 3.0, "어젯밤 치카치카… 깜빡했네!", "Last night's brushing… I forgot!", "high"),
    (O2 + 3.0, O3, "범인은 바로 나~", "The culprit is… me~", "high"),
    (O3, M4 + BARL, *B1, "high"),
    (M4 + BARL, M4 + 2 * BARL, *B2, "high"),
    (M4 + 2 * BARL, M4 + 3 * BARL, *B1, "high"),
    (M4 + 3 * BARL, O4, *B2, "high"),
    (O4, M5B, "범인 찾았다! 치카치카 해결!", "Found it! Brushing solved it!", "high"),
    (M5B, SPOT, "반짝반짝 내 이, 냠냠 맛있다~", "Sparkly teeth, yum yum~", "high"),
    (SPOT, DUR, "어? 어?", "Huh? Huh?", "high"),
]
TITLES = [(0.0, 2 * BARL, "누가 내 이에 노란 점?!", "Who put yellow spots on me?!")]
# 이름표: 해당 캐릭터 가까이, 세로 65% 안쪽
TAGS = [
    (O1 + 0.1, O1 + 1.5, "알콩이", "Corn", 110, 742),
    (O1 + 1.5, O1 + 3.0, "노롱이", "Yolk", 225, 790),
    (O1 + 3.2, O1 + 6.4, "꽥꽥이", "Duck", 110, 690),
    (O2 + 3.1, O2 + 5.1, "범인은 나?!", "It was me?!", 540, 400),
]
FADE = 0.15


def build_overlays():
    items = []
    rows = [(s, e, lyric(ko, en, p)) for s, e, ko, en, p in LYRICS]
    rows += [(s, e, title(ko, en)) for s, e, ko, en in TITLES]
    starts = {round(r[0], 3) for r in rows}
    ends = {round(r[1], 3) for r in rows}
    for s, e, ov in rows:
        # 바로 이어지는 자막끼리는 글자만 바꿈(깜박임 방지). 0초·끝(루프 이음매)은 페이드 없음.
        fi = s > 0 and round(s, 3) not in ends
        fo = e < DUR - 1e-6 and round(e, 3) not in starts
        items.append((s, e, ov, fi, fo))
    for s, e, ko, en, cx, top in TAGS:
        items.append((s, e, tag(ko, en, cx, top), True, True))
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


# 루프 마감: 마지막 LOOP_BLEND 프레임 동안 0프레임(글자 흐림 적용, 자막 전) 그림으로 서서히 겹침
LOOP_BLEND = 6   # 0.2초: 메모 권장(0.1~0.2초). 0.4초로 했더니 크기 다른 두 그림이 겹쳐 보여 줄임


# ───────────────────────── 5) 실행 ─────────────────────────
def main():
    print("font:", FONT_PATH if FONT_PATH.exists() else "Apple SD Gothic Neo (대체)")
    print(f"길이 {DUR:.3f}초 ({NFRAMES}프레임), 박 {BEAT:.4f}초 ({60 / BEAT:.2f} BPM)")
    print("클립 시작:", [round(o, 3) for o in OFF], "냠:", round(EAT, 3), "노란 점:", round(SPOT, 3))
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
        "-map", "0:v", "-map", "1:a", "-af", af + ",aresample=48000",
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
        img = blur_frame(i, Image.frombuffer("RGB", (W, H), buf).copy())
        frame = np.array(img)
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
