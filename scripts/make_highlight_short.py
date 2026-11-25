#!/usr/bin/env python3
"""롱폼(16:9)에서 고른 하이라이트 구간으로 세로 쇼츠(720x1280)를 만든다. 크레딧을 쓰지 않는다.

쇼츠 양식 (2026-11-25 사용자 확정, 20261125_요람새친구 v2):
  - 바탕: 크림 #faecd6 + 입체 메리야스 뜨개 무늬(V자 코, 그늘·하이라이트·실 결·옅은 보풀)
  - 위 띠: 화면 제목 2줄 (1줄 코랄 굵게 96px, 2줄 진한 갈색 66px), 영상 내내 고정
  - 영상: 원본 가로 가운데 70%(896x720)를 잘라 720x579로 줄여 y=300~879, 둥근 모서리 + 얇은 갈색 테두리
  - 아래 띠(890~1060): 영어 자막 52px(진한 갈색, {c:강조} 코랄) 위 · 한글 39px 아래, 가운데 정렬
  - 1060~1280: 쇼츠 UI 자리라 글자 없음

사용:
  .venv/bin/python scripts/make_highlight_short.py <spec.json>

spec.json (경로는 spec.json이 있는 폴더 기준):
{
  "source": "../../longform/<롱폼이름>/<롱폼이름>_clean.mp4",   # 자막을 넣기 전 롱폼(소리 포함, 16:9)
  "output": "<쇼츠이름>.mp4",
  "title": ["Birdie Gifts", "for Baby Lamb"],                  # 1~2줄, 줄마다 640px 안 (자동으로 글자 크기 줄임)
  "segments": [                                                # 원본에서 쓸 구간(초). 순서대로 이어 붙임
    {"start": 12.0, "end": 24.5},
    {"start": 40.0, "end": 57.5, "crop_x": 240}                # crop_x: 잘라낼 왼쪽 x (기본 192, 0~384)
  ],
  "captions": [                                                # 쇼츠 시간 기준(초)
    {"start": 0.0, "end": 3.2, "en": ["Kami, Kami,", "what did you bring?"], "ko": "까미야 까미야, 뭐 가져왔니?"}
  ],
  "crossfade": 0.25                                            # 구간 사이 크로스페이드(초), 0이면 그냥 컷
}

출력: 720x1280 30fps H.264 + AAC 48kHz, -14 LUFS. 같은 spec이면 같은 결과.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import skia
from PIL import Image

W, H, FPS = 1280, 720, 30
SW, SH = 720, 1280
CROP_W, CROP_X = 896, 192
VID_Y0, VID_H = 300, 579
VID_Y1 = VID_Y0 + VID_H
TITLE_B1, TITLE_B2 = 182, 258
BAND_Y0, BAND_Y1 = 890, 1060
S_EN, S_KO = 52, 39
FADE = 0.12
RADIUS = 22
CREAM = (0xfa, 0xec, 0xd6)
CORAL = skia.Color(0xf0, 0x84, 0x5c)
CORAL_TXT = skia.Color(0xe0, 0x6a, 0x40)
BROWN = skia.Color(0x3c, 0x2a, 0x1e)
BROWN_KO = skia.Color(0x6b, 0x4a, 0x35)
TF = skia.Typeface("Apple SD Gothic Neo", skia.FontStyle.Bold())
TF_TITLE = skia.Typeface("Apple SD Gothic Neo", skia.FontStyle(900, 5, skia.FontStyle.kUpright_Slant))


def fail(msg):
    print("❌", msg)
    sys.exit(1)


def parse(text, base, accent):
    return [(m.group(1), accent) if m.group(1) is not None else (m.group(2), base)
            for m in re.finditer(r"\{c:([^}]*)\}|([^{]+)", text)]


def plain(text):
    return re.sub(r"\{c:([^}]*)\}", r"\1", text)


def fit_size(text, tf, size, max_w):
    while size > 20 and skia.Font(tf, size).measureText(plain(text)) > max_w:
        size -= 2
    return size


def draw_line(c, text, tf, size, cx, baseline, base, accent, stroke=0, outline=None, shadow=None):
    font = skia.Font(tf, size)
    x = cx - font.measureText(plain(text)) / 2
    blobs = []
    for s, col in parse(text, base, accent):
        blobs.append((skia.TextBlob.MakeFromString(s, font), x, col))
        x += font.measureText(s)
    if shadow is not None:
        sh = skia.Paint(AntiAlias=True, Color=shadow, Style=skia.Paint.kStrokeAndFill_Style,
                        StrokeWidth=max(stroke, 2), StrokeJoin=skia.Paint.kRound_Join,
                        MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 4))
        for b, bx, _ in blobs:
            c.drawTextBlob(b, bx + 2, baseline + 3, sh)
    if stroke and outline is not None:
        ol = skia.Paint(AntiAlias=True, Color=outline, Style=skia.Paint.kStroke_Style, StrokeWidth=stroke,
                        StrokeJoin=skia.Paint.kRound_Join)
        for b, bx, _ in blobs:
            c.drawTextBlob(b, bx, baseline, ol)
    for b, bx, col in blobs:
        c.drawTextBlob(b, bx, baseline, skia.Paint(AntiAlias=True, Color=col))


def snapshot(surf):
    return surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType,
                                            alphaType=skia.kUnpremul_AlphaType).astype(np.float32) / 255.0


def background(title):
    surf = skia.Surface(SW, SH)
    c = surf.getCanvas()
    c.clear(skia.Color(0xec, 0xda, 0xbd))
    rng = np.random.default_rng(7)
    sw, sh = 22, 20
    leg_w, leg_h = sw * 0.46, sh * 1.22
    for y in range(-sh, SH + sh, sh):
        for x in range(-sw, SW + sw, sw):
            cx, cy = x + sw / 2, y + sh / 2
            j = rng.uniform(-4, 4)
            for side in (-1, 1):
                c.save()
                c.translate(cx + side * sw * 0.22, cy)
                c.rotate(side * 30)
                r = skia.Rect.MakeXYWH(-leg_w / 2, -leg_h / 2, leg_w, leg_h)
                c.save(); c.translate(0.8, 1.6)
                c.drawOval(r, skia.Paint(AntiAlias=True, Color=skia.Color(0xd9, 0xc2, 0x9f)))
                c.restore()
                top = skia.Color(int(min(255, 0xfe + j)), int(min(255, 0xf4 + j)), int(min(255, 0xe2 + j)))
                bot = skia.Color(int(0xf1 + j), int(0xdf + j), int(0xc2 + j))
                shd = skia.GradientShader.MakeLinear([(0, -leg_h / 2), (0, leg_h / 2)], [top, bot])
                c.drawOval(r, skia.Paint(AntiAlias=True, Shader=shd))
                fib = skia.Paint(AntiAlias=True, Color=skia.Color(0xe2, 0xcb, 0xa8, 150),
                                 Style=skia.Paint.kStroke_Style, StrokeWidth=0.9)
                for k in (-0.18, 0.18):
                    c.drawLine(leg_w * k - 1.2, -leg_h * 0.3, leg_w * k + 1.2, leg_h * 0.3, fib)
                c.restore()
    img = snapshot(surf)[..., :3] * 255
    img += rng.normal(0, 2.2, img.shape[:2])[..., None]
    surf = skia.Surface(SW, SH)
    c = surf.getCanvas()
    c.drawImage(skia.Image.fromarray(np.dstack([np.clip(img, 0, 255).astype(np.uint8),
                                                np.full(img.shape[:2], 255, np.uint8)]),
                                     colorType=skia.kRGBA_8888_ColorType), 0, 0)
    glow = skia.Paint(AntiAlias=True, Color=skia.Color(*CREAM, 150),
                      MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 18))
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(70, TITLE_B1 - 92, SW - 70, TITLE_B2 + 22), 40, 40), glow)
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(40, BAND_Y0 + 8, SW - 40, BAND_Y1 - 8), 40, 40), glow)
    st = skia.Paint(AntiAlias=True, Color=skia.Color(0xe7, 0xb8, 0x9a), Style=skia.Paint.kStroke_Style,
                    StrokeWidth=3, StrokeCap=skia.Paint.kRound_Cap, PathEffect=skia.DashPathEffect.Make([10, 9], 0))
    for y in (VID_Y0 - 14, VID_Y1 + 14):
        c.drawLine(24, y, SW - 24, y, st)
    lines = list(title)[:2]
    if len(lines) == 1:
        s = fit_size(lines[0], TF_TITLE, 96, 640)
        draw_line(c, lines[0], TF_TITLE, s, SW / 2, (TITLE_B1 + TITLE_B2) / 2 + 10, CORAL, CORAL, 4,
                  skia.Color(255, 250, 240), skia.Color(60, 42, 30, 70))
    else:
        draw_line(c, lines[0], TF_TITLE, fit_size(lines[0], TF_TITLE, 96, 640), SW / 2, TITLE_B1, CORAL, CORAL, 4,
                  skia.Color(255, 250, 240), skia.Color(60, 42, 30, 70))
        draw_line(c, lines[1], TF_TITLE, fit_size(lines[1], TF_TITLE, 66, 640), SW / 2, TITLE_B2, BROWN, BROWN, 0,
                  None, skia.Color(60, 42, 30, 40))
    return (snapshot(surf)[..., :3] * 255).astype(np.float32)


def video_mask_and_border():
    surf = skia.Surface(SW, VID_H)
    c = surf.getCanvas()
    c.clear(skia.Color(0, 0, 0, 0))
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(0, 0, SW, VID_H), RADIUS, RADIUS),
                skia.Paint(AntiAlias=True, Color=skia.Color(255, 255, 255)))
    mask = snapshot(surf)[..., 3:4]
    surf2 = skia.Surface(SW, VID_H)
    c2 = surf2.getCanvas()
    c2.clear(skia.Color(0, 0, 0, 0))
    c2.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(1.5, 1.5, SW - 3, VID_H - 3), RADIUS - 1, RADIUS - 1),
                 skia.Paint(AntiAlias=True, Color=skia.Color(0x8a, 0x5a, 0x3c, 230), Style=skia.Paint.kStroke_Style,
                            StrokeWidth=3))
    return mask, snapshot(surf2)


def caption(en_lines, ko):
    hh = BAND_Y1 - BAND_Y0
    surf = skia.Surface(SW, hh)
    c = surf.getCanvas()
    c.clear(skia.Color(0, 0, 0, 0))
    steps = [56] * (len(en_lines) - 1) + ([50] if ko else [])
    y = (hh - (40 + sum(steps) + 10)) / 2 + 40
    if y - 40 < 0:
        fail(f"자막이 띠에 다 들어가지 않습니다(줄을 줄이세요): {en_lines} / {ko}")
    for i, t in enumerate(en_lines):
        if i:
            y += 56
        draw_line(c, t, TF, fit_size(t, TF, S_EN, 600), SW / 2, y, BROWN, CORAL_TXT)
    if ko:
        y += 50
        draw_line(c, ko, TF, fit_size(ko, TF, S_KO, 600), SW / 2, y, BROWN_KO, BROWN_KO)
    return snapshot(surf)


def main():
    if len(sys.argv) != 2:
        fail("사용: .venv/bin/python scripts/make_highlight_short.py <spec.json>")
    spec_path = Path(sys.argv[1]).resolve()
    base = spec_path.parent
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    src = (base / spec["source"]).resolve()
    out = (base / spec["output"]).resolve()
    if not src.exists():
        fail(f"원본이 없습니다: {src}")
    segs = spec["segments"]
    xf = float(spec.get("crossfade", 0.25))
    nxf = int(round(xf * FPS))

    # 구간별 프레임 읽기 (1280x720으로 맞춤)
    clips = []
    for s in segs:
        n = int(round((s["end"] - s["start"]) * FPS))
        p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{s['start']:.3f}", "-i", str(src), "-t",
                            f"{(s['end'] - s['start']) + 0.2:.3f}", "-vf", f"fps={FPS},scale={W}:{H}",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        fr = np.frombuffer(p, np.uint8).reshape(-1, H, W, 3)[:n]
        if len(fr) < n - 2:
            fail(f"구간을 다 읽지 못했습니다: {s} ({len(fr)}/{n}프레임)")
        clips.append((fr, int(s.get("crop_x", CROP_X))))

    # 이어 붙이기 (크로스페이드는 겹치게 → 길이가 그만큼 줄어듦)
    frames, cx = [], []
    for k, (fr, x0) in enumerate(clips):
        if k and nxf:
            for i in range(nxf):
                w = (i + 1) / (nxf + 1)
                frames[-nxf + i] = ((1 - w) * frames[-nxf + i].astype(np.float32)
                                    + w * fr[i].astype(np.float32)).astype(np.uint8)
                cx[-nxf + i] = int(round((1 - w) * cx[-nxf + i] + w * x0))
            fr = fr[nxf:]
        frames.extend(list(fr))
        cx.extend([x0] * len(fr))
    nfr = len(frames)
    dur = nfr / FPS

    # 소리: 같은 구간을 잘라 이어 붙이고 크로스페이드, -14 LUFS
    with tempfile.TemporaryDirectory() as td:
        parts = []
        for i, s in enumerate(segs):
            pth = Path(td) / f"a{i}.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s['start']:.3f}", "-i", str(src), "-t",
                            f"{s['end'] - s['start']:.3f}", "-vn", "-ac", "2", "-ar", "48000", str(pth)], check=True)
            parts.append(pth)
        mix = Path(td) / "mix.wav"
        if len(parts) == 1:
            subprocess.run(["cp", str(parts[0]), str(mix)], check=True)
        else:
            args, chain, last = [], "", "[0:a]"
            for p in parts:
                args += ["-i", str(p)]
            for i in range(1, len(parts)):
                lab = f"[x{i}]"
                chain += (f"{last}[{i}:a]acrossfade=d={xf}:c1=tri:c2=tri{lab};" if nxf
                          else f"{last}[{i}:a]concat=n=2:v=0:a=1{lab};")
                last = lab
            subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex", chain.rstrip(";"),
                            "-map", last, str(mix)], check=True)
        res = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mix), "-af",
                              "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                             capture_output=True, text=True)
        m = json.loads(res.stderr[res.stderr.rfind("{"): res.stderr.rfind("}") + 1])
        af = ("loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:"
              f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
              f"measured_thresh={m['input_thresh']}:offset={m['target_offset']},"
              f"aresample=48000,apad=whole_dur={dur:.4f}")

        bg = background(spec.get("title", []))
        vmask, border = video_mask_and_border()
        caps = []
        for cpt in spec.get("captions", []):
            caps.append((float(cpt["start"]), min(float(cpt["end"]), dur), caption(cpt["en"], cpt.get("ko", ""))))
        starts = {round(c[0], 3) for c in caps}
        ends = {round(c[1], 3) for c in caps}

        out.parent.mkdir(parents=True, exist_ok=True)
        enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                "-s", f"{SW}x{SH}", "-r", str(FPS), "-i", "-", "-i", str(mix),
                                "-map", "0:v", "-map", "1:a", "-af", af,
                                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{dur:.4f}",
                                "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
        for j in range(nfr):
            t = j / FPS
            x0 = max(0, min(W - CROP_W, cx[j]))
            crop = Image.fromarray(frames[j][:, x0:x0 + CROP_W])
            v = np.asarray(crop.resize((SW, VID_H), Image.LANCZOS)).astype(np.float32)
            v = v * (1 - border[..., 3:4]) + border[..., :3] * 255 * border[..., 3:4]
            f = bg.copy()
            f[VID_Y0:VID_Y1] = f[VID_Y0:VID_Y1] * (1 - vmask) + v * vmask
            for s, e, rgba in caps:
                if not (s <= t < e):
                    continue
                fi = s > 0 and round(s, 3) not in ends
                fo = e < dur - 1e-6 and round(e, 3) not in starts
                a = min(min(1.0, (t - s) / FADE) if fi else 1.0, min(1.0, (e - t) / FADE) if fo else 1.0)
                reg = f[BAND_Y0:BAND_Y1]
                al = rgba[..., 3:4] * a
                f[BAND_Y0:BAND_Y1] = reg * (1 - al) + rgba[..., :3] * 255 * al
            enc.stdin.write(np.clip(f + 0.5, 0, 255).astype(np.uint8).tobytes())
        enc.stdin.close()
        if enc.wait() != 0:
            fail("인코딩 실패")
    print(f"완성: {out} ({dur:.2f}초, {nfr}프레임)")


if __name__ == "__main__":
    main()
