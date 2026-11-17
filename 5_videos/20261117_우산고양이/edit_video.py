#!/usr/bin/env python3
"""20261117_우산고양이 후처리 / 최종 렌더

scripts/assemble_video.py 의 _raw.mp4 는 기본(bicubic) 업스케일이라 참고용으로만 두고,
이 스크립트는 edit.json 의 같은 구간을 원본 클립에서 다시 읽어
  1) 360x640 -> 1080x1920 lanczos 업스케일 + 약한 언샤프
  2) 클립 _3 구간 색 보정 (다른 클립보다 주황빛·밝은 낮 톤 -> 블루아워 톤에 맞춤)
  3) 연결 지점 오디오 짧은 페이드(클릭 방지), 클립별 음량 맞춤
  4) numpy 로 합성한 잔잔한 피아노 배경음 (10초 부근 페이드 인, 30초 이후 줄임)
  5) skia 로 그린 자막 PNG overlay
  6) 2-pass loudnorm (-14 LUFS, TP -1.5)
을 한다. 같은 입력이면 항상 같은 결과가 나온다.

실행: .venv/bin/python 5_videos/20261117_우산고양이/edit_video.py
"""
import json
import re
import subprocess
import wave
from pathlib import Path

import numpy as np
import skia

EP = Path(__file__).resolve().parent
NAME = "20261117_우산고양이"
W, H, FPS = 1080, 1920, 30
SR = 48000
AXF = 0.12  # 연결 지점 오디오 크로스페이드 길이(초)
WORK = EP / "work"
WORK.mkdir(exist_ok=True)

cfg = json.loads((EP / "edit.json").read_text(encoding="utf-8"))
CLIPS = cfg["clips"]
FADE_OUT = float(cfg.get("fade_out", 0.6))

# 클립별 색 보정 (파일 이름 일부로 지정). 클립 _3(Boy_touching...)만 낮 톤이라 보정.
GRADE = {
    "Boy_touching_giant_cat_tail": "eq=saturation=0.70:brightness=-0.05:gamma=0.95,"
       "colorbalance=rs=-0.04:bs=0.05:rm=-0.04:gm=0.0:bm=0.04:rh=-0.03:bh=0.02",
}

# 자막: (시작, 끝, 줄 목록, 세로 중심 위치 비율)
SUBS = [
    (0.15, 3.2, ["퇴근길,", "갑자기 소나기가 쏟아졌다"], 0.40),
    (3.5, 7.0, ["…근데 저건 뭐야?"], 0.22),
    (17.4, 21.7, ["고양이는", "물을 싫어하는데"], 0.22),
    (22.0, 24.55, ["꾹 참는 중…"], 0.20),
    (29.6, 32.0, ["우산고양이 몽실이", "#1 버스정류장편"], 0.22),
]


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def seg_loudness(path, start, end):
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", str(start), "-to", str(end), "-i", str(path),
         "-vn", "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    return float(m[-1]) if m else -23.0


# ---------------- 자막 PNG ----------------
def make_sub_png(lines, out):
    tf = skia.Typeface("Apple SD Gothic Neo", skia.FontStyle.Bold())
    size = 66
    font = skia.Font(tf, size)
    line_h = size * 1.32
    surf = skia.Surface(W, int(line_h * len(lines) + 60))
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    stroke = skia.Paint(AntiAlias=True, Color=skia.Color(20, 20, 30, 235),
                        Style=skia.Paint.kStroke_Style, StrokeWidth=12,
                        StrokeJoin=skia.Paint.kRound_Join)
    shadow = skia.Paint(AntiAlias=True, Color=skia.Color(0, 0, 0, 120),
                        MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 8))
    fill = skia.Paint(AntiAlias=True, Color=skia.Color(255, 255, 255))
    for i, t in enumerate(lines):
        tw = font.measureText(t)
        assert tw < 760, f"자막이 너무 깁니다: {t} ({tw:.0f}px)"
        x = (W - tw) / 2 - 40  # 오른쪽 15% UI 영역을 피하려고 살짝 왼쪽으로
        y = 30 + size + i * line_h
        c.drawString(t, x + 3, y + 5, font, shadow)
        c.drawString(t, x, y, font, stroke)
        c.drawString(t, x, y, font, fill)
    surf.makeImageSnapshot().save(str(out), skia.kPNG)
    return surf.height()


# ---------------- 배경음 합성 ----------------
def make_bgm(total, out):
    rng = np.random.default_rng(1117)
    n = int(total * SR)
    t = np.arange(n) / SR
    music = np.zeros(n)
    bpm = 72
    beat = 60 / bpm
    eighth = beat / 2
    # C major 계열 잔잔한 진행: Cmaj7 - Am7 - Fmaj7 - G(add9)
    chords = [[48, 55, 59, 64, 67], [45, 52, 55, 60, 64], [41, 48, 52, 57, 60], [43, 50, 55, 57, 62]]
    arp = [0, 2, 3, 4, 3, 2, 1, 2]

    def note(midi, dur, amp):
        f = 440 * 2 ** ((midi - 69) / 12)
        m = int(dur * SR)
        tt = np.arange(m) / SR
        env = np.exp(-tt * 2.6) * np.minimum(1, tt / 0.008)
        tone = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * 2 * f * tt)
                + 0.12 * np.sin(2 * np.pi * 3 * f * tt))
        return amp * env * tone

    start = 9.0
    pos = start
    ci = 0
    while pos < total:
        ch = chords[ci % 4]
        # 베이스 + 아르페지오 (한 코드 = 2마디 = 8박)
        for bar in range(2):
            bstart = pos + bar * 4 * beat
            s = int(bstart * SR)
            v = note(ch[0] - 12, 3.0, 0.35)
            e = min(n, s + len(v))
            if s < n:
                music[s:e] += v[:e - s]
            for k, a in enumerate(arp):
                ts = bstart + k * eighth + rng.uniform(-0.008, 0.008)
                s = int(ts * SR)
                if s >= n:
                    break
                v = note(ch[a] + 12, 2.0, 0.16 + 0.03 * (k % 2 == 0))
                e = min(n, s + len(v))
                music[s:e] += v[:e - s]
        pos += 8 * beat
        ci += 1
    # 부드러운 패드
    pad = np.zeros(n)
    pos, ci = start, 0
    while pos < total:
        ch = chords[ci % 4]
        s, e = int(pos * SR), min(n, int((pos + 8 * beat) * SR))
        tt = t[s:e]
        for m in ch[1:4]:
            f = 440 * 2 ** ((m - 69) / 12)
            pad[s:e] += 0.05 * np.sin(2 * np.pi * f * tt)
        pos += 8 * beat
        ci += 1
    music += pad
    # 간단한 리버브 느낌 (지연 합)
    for d, g in [(0.083, 0.30), (0.137, 0.22), (0.211, 0.15), (0.297, 0.10)]:
        k = int(d * SR)
        music[k:] += g * music[:-k]
    # 볼륨 곡선: 0~9초 무음, 9~11.5초 페이드 인, 29.5~31초 0.45까지 줄임
    env = np.interp(t, [0, 9.0, 11.5, 29.5, 31.0, total], [0, 0, 1, 1, 0.45, 0.45])
    music *= env
    music /= max(1e-9, np.abs(music).max())
    music *= 0.5
    stereo = np.stack([music, np.roll(music, int(0.012 * SR))], axis=1)
    pcm = (stereo * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


def main():
    total = sum(float(c["end"]) - float(c["start"]) for c in CLIPS)
    print(f"총 길이 {total:.2f}초")

    bgm = WORK / "bgm_synth.wav"
    make_bgm(total, bgm)

    inputs, filters, cat = [], [], []
    for i, c in enumerate(CLIPS):
        path = (EP / c["file"]).resolve()
        s, e = float(c["start"]), float(c["end"])
        lufs = seg_loudness(path, s, e)
        gain_db = max(-3.0, min(3.0, -23.0 - lufs))  # 조용한 구간 잡음이 커지지 않게 ±3dB 제한
        inputs += ["-i", str(path)]
        grade = "".join("," + g for k, g in GRADE.items() if k in c["file"])
        filters.append(
            f"[{i}:v]trim={s}:{e},setpts=PTS-STARTPTS,fps={FPS},"
            f"scale={W}:{H}:flags=lanczos+accurate_rnd+full_chroma_int,"
            f"unsharp=5:5:0.55:5:5:0.0{grade},setsar=1,format=yuv420p[v{i}]")
        d = e - s
        n = len(CLIPS)
        # 오디오는 다음 클립과 AXF초 겹쳐 acrossfade 하므로 마지막 클립 외에는 AXF초 더 읽는다
        ae = e + (AXF if i < n - 1 else 0.0)
        filters.append(
            f"[{i}:a]atrim={s}:{ae},asetpts=PTS-STARTPTS,aresample={SR},"
            f"aformat=channel_layouts=stereo,volume={gain_db:.2f}dB[a{i}]")
        cat.append(f"[v{i}]")
        print(f"  클립 {i + 1}: {Path(c['file']).name} {s}~{e} ({d:.2f}s) 음량 {lufs:.1f} LUFS -> {gain_db:+.1f} dB")
    filters.append(f"{''.join(cat)}concat=n={n}:v=1:a=0[vcat]")
    # 연결 지점 오디오: 빗소리가 끊기지 않게 0.12초 크로스페이드 (영상은 하드컷)
    alab = "a0"
    for i in range(1, n):
        filters.append(f"[{alab}][a{i}]acrossfade=d={AXF}:c1=tri:c2=tri[ax{i}]")
        alab = f"ax{i}"
    filters.append(f"[{alab}]anull[acat]")

    # 자막 overlay
    vlabel = "vcat"
    idx = n
    for k, (st, en, lines, yc) in enumerate(SUBS):
        png = WORK / f"sub_{k + 1}.png"
        hh = make_sub_png(lines, png)
        y = int(H * yc - hh / 2)
        assert H * 0.12 <= y and y + hh <= H * 0.65, f"자막 {k + 1} 안전 구역 밖"
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.3f}", "-i", str(png)]
        filters.append(f"[{idx}:v]format=rgba,fade=t=in:st={st}:d=0.2:alpha=1,"
                       f"fade=t=out:st={en - 0.2}:d=0.2:alpha=1[s{k}]")
        filters.append(f"[{vlabel}][s{k}]overlay=0:{y}:enable='between(t,{st},{en})'[vs{k}]")
        vlabel = f"vs{k}"
        idx += 1
    fade_st = total - FADE_OUT
    filters.append(f"[{vlabel}]fade=t=out:st={fade_st:.3f}:d={FADE_OUT},format=yuv420p[vout]")

    inputs += ["-i", str(bgm)]
    filters.append(f"[{idx}:a]atrim=0:{total},asetpts=PTS-STARTPTS,volume=0.32[bgm]")
    filters.append(f"[acat][bgm]amix=inputs=2:duration=first:normalize=0,"
                   f"afade=t=out:st={fade_st:.3f}:d={FADE_OUT}[aout]")

    tmp = WORK / "premix.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
         "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "pcm_s16le", str(tmp.with_suffix(".mov"))])
    tmp = tmp.with_suffix(".mov")

    # loudnorm 1차 측정
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(tmp), "-vn", "-af",
                        "loudnorm=I=-14:TP=-2.0:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    meas = json.loads(p.stderr[p.stderr.rindex("{"):p.stderr.rindex("}") + 1])
    ln = ("loudnorm=I=-14:TP=-2.0:LRA=11:"
          f"measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
          f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:"
          f"offset={meas['target_offset']}:linear=true,aresample={SR}")
    out = EP / f"{NAME}.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp),
         "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-af", ln,
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    print(f"완성: {out}")


if __name__ == "__main__":
    main()
