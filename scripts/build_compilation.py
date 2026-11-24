#!/usr/bin/env python3
"""
쇼츠 여러 편을 이어 붙여 가로 16:9 롱폼 모음집을 만든다 (큐레이터용). ffmpeg만 사용한다.

- 세로(9:16) 쇼츠는 가운데 카드(흰 테두리·둥근 모서리)에 두고, 양옆은 꾸민 테두리로 채운다
  (니트 무늬 배경, 왼쪽 "Episode N"·제목·진행 점, 오른쪽 채널 이름·다음 이야기 미리보기). 그림은 scripts/compilation_frame.py.
  "style": "blur"로 두면 예전처럼 같은 화면을 확대·블러한 배경을 쓴다.
- 구간마다 음량을 먼저 맞춘 뒤(-14 LUFS) 짧은 크로스페이드(영상·소리)로 잇고, 마지막에 전체 음량을 한 번 더 맞춘다.
- 챕터 시작 시각을 chapters.json으로 저장한다 (설명란 타임스탬프용).

사용:
    python3 scripts/build_compilation.py 5_videos/<기본이름>          # 폴더 안의 compile.json을 읽음

compile.json (경로는 compile.json이 있는 폴더 기준):
{
  "output": "<기본이름>.mp4",
  "width": 1920, "height": 1080, "fps": 30,
  "crossfade": 0.5,
  "fade_in": 0.3, "fade_out": 1.5,
  "style": "frame", "channel": "bebePop",
  "segments": [
    {"file": "../20261122_텃밭누가왔나/20261122_텃밭누가왔나.mp4", "start": 0.0, "end": 29.9,
     "chapter": "Who's Here in the Garden?"},
    {"file": "../20261120_딸기씻어냠냠/20261120_딸기씻어냠냠.mp4", "start": 0.0, "end": 12.0,
     "chapter": "Wash the Strawberries"},
    {"file": "../20261120_딸기씻어냠냠/20261120_딸기씻어냠냠.mp4", "start": 14.5, "end": 39.3}
  ]
}
- 한 쇼츠에서 이상한 구간을 빼려면 같은 파일을 구간을 나눠 두 번 넣는다. chapter가 없는 구간은 앞 챕터에 이어진다.
- 꾸민 테두리의 에피소드 번호·제목·다음 이야기는 chapter 순서로 자동으로 정해진다.
- skia가 없는 파이썬으로 실행하면 저장소의 .venv/bin/python으로 다시 실행한다.
- 중간 파일은 <폴더>/_work/에 만든다. 다시 실행하면 같은 결과가 나온다.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    import skia  # noqa: F401
except ImportError:
    venv = ROOT / ".venv" / "bin" / "python"
    if venv.is_file() and not os.environ.get("BUILD_COMPILATION_REEXEC"):
        os.environ["BUILD_COMPILATION_REEXEC"] = "1"
        os.execv(str(venv), [str(venv), *sys.argv])
    skia = None


def fail(msg):
    print(f"❌ {msg}")
    sys.exit(1)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        fail("ffmpeg 실패:\n" + r.stderr[-2000:])
    return r


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(r.stdout.strip())


def has_audio(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", str(path)])
    return bool(r.stdout.strip())


def render_segment(src, start, end, out, W, H, fps, bg=None, fg=None):
    """구간 하나를 16:9, 고정 fps, 음량 맞춤으로 렌더링한다.
    bg/fg 그림이 있으면 꾸민 테두리, 없으면 확대·블러 배경."""
    dur = end - start
    head = f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,fps={fps}"
    inputs = ["-i", str(src)]
    if bg:
        from compilation_frame import video_box
        vx, vy, vw, vh = video_box(W, H)
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(bg),
                   "-loop", "1", "-framerate", str(fps), "-i", str(fg)]
        vf = (f"{head},scale={vw}:{vh},setsar=1[fgv];"
              f"[1:v]format=yuv420p[bgi];[bgi][fgv]overlay={vx}:{vy}:shortest=1[t];"
              f"[t][2:v]overlay=0:0:shortest=1,format=yuv420p,setsar=1[v]")
    else:
        vf = (f"{head},split[a][b];"
              f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:2,eq=brightness=-0.06[bg];"
              f"[b]scale=-2:{H}[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p,setsar=1[v]")
    if has_audio(src):
        af = (f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
              f"aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[au]")
    else:  # 소리가 없으면 무음으로 채운다
        n = 3 if bg else 1
        af = f"[{n}:a]atrim=duration={dur},asetpts=PTS-STARTPTS[au]"
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", vf + ";" + af,
         "-map", "[v]", "-map", "[au]", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(fps),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])


def main():
    if len(sys.argv) != 2:
        fail("사용: python3 scripts/build_compilation.py 5_videos/<기본이름>")
    folder = Path(sys.argv[1]).resolve()
    cfg_path = folder / "compile.json"
    if not cfg_path.is_file():
        fail(f"설정 파일이 없습니다: {cfg_path}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    W, H, fps = int(cfg.get("width", 1920)), int(cfg.get("height", 1080)), int(cfg.get("fps", 30))
    xf = float(cfg.get("crossfade", 0.5))
    fade_in, fade_out = float(cfg.get("fade_in", 0.3)), float(cfg.get("fade_out", 1.5))
    segs = cfg.get("segments") or []
    if len(segs) < 2:
        fail("segments가 2개 이상 필요합니다.")
    if not segs[0].get("chapter"):
        fail("첫 구간에는 chapter가 있어야 합니다 (설명란 00:00 챕터).")

    style = cfg.get("style", "frame")
    channel = cfg.get("channel", "bebePop")
    if style == "frame" and skia is None:
        fail("꾸민 테두리에는 skia-python이 필요합니다 (.venv/bin/python으로 실행하세요).")

    work = folder / "_work"
    work.mkdir(exist_ok=True)
    # 구간마다 원본 경로·구간·챕터 번호를 미리 정한다
    plan, ch_titles, ch_first = [], [], []
    for i, s in enumerate(segs, 1):
        src = (folder / s["file"]).resolve()
        if not src.is_file():
            fail(f"구간 {i} 파일이 없습니다: {s['file']}")
        total = duration(src)
        start, end = float(s.get("start", 0)), float(s.get("end", total))
        end = min(end, total)
        if end - start < max(2 * xf, 1.0):
            fail(f"구간 {i}가 너무 짧습니다 ({end - start:.2f}초).")
        if s.get("chapter"):
            ch_titles.append(s["chapter"])
            ch_first.append((src, start, end))
        plan.append((src, start, end, len(ch_titles)))

    fg = None
    if style == "frame":
        sys.path.insert(0, str(ROOT / "scripts"))
        from compilation_frame import render_bg, render_fg
        fg = work / "frame_fg.png"
        render_fg(fg, W, H)
        for n, title in enumerate(ch_titles, 1):
            nxt, thumb = None, None
            if n < len(ch_titles):
                nxt = ch_titles[n]
                nsrc, ns, ne = ch_first[n]
                thumb = work / f"next_{n:02d}.png"
                run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ns + min(3.0, (ne - ns) / 2):.2f}", "-i", str(nsrc),
                     "-frames:v", "1", "-vf", "scale=250:-2", str(thumb)])
            render_bg(work / f"frame_bg_{n:02d}.png", W, H, n, len(ch_titles), title, channel, nxt, thumb)

    parts, durs = [], []
    for i, (src, start, end, ch) in enumerate(plan, 1):
        out = work / f"seg_{i:02d}.mp4"
        print(f"   구간 {i}/{len(segs)}: {src.name} {start:.2f}~{end:.2f}초")
        bg = work / f"frame_bg_{ch:02d}.png" if fg else None
        render_segment(src, start, end, out, W, H, fps, bg, fg)
        parts.append(out)
        durs.append(duration(out))

    # 크로스페이드 체인
    inputs, vchain, achain = [], [], []
    for p in parts:
        inputs += ["-i", str(p)]
    offset, vprev, aprev = 0.0, "[0:v]", "[0:a]"
    starts = [0.0]
    for i in range(1, len(parts)):
        offset += durs[i - 1] - xf
        starts.append(offset)
        vout, aout = f"[v{i}]", f"[a{i}]"
        vchain.append(f"{vprev}[{i}:v]xfade=transition=fade:duration={xf}:offset={offset:.3f}{vout}")
        achain.append(f"{aprev}[{i}:a]acrossfade=d={xf}:c1=tri:c2=tri{aout}")
        vprev, aprev = vout, aout
    total = starts[-1] + durs[-1]
    vchain.append(f"{vprev}fade=t=in:st=0:d={fade_in},fade=t=out:st={total - fade_out:.3f}:d={fade_out}[vf]")
    achain.append(f"{aprev}afade=t=in:st=0:d={fade_in},afade=t=out:st={total - fade_out:.3f}:d={fade_out},"
                  f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[af]")
    output = folder / cfg.get("output", folder.name + ".mp4")
    print(f"   이어 붙이는 중… (예상 {total:.1f}초)")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(vchain + achain),
         "-map", "[vf]", "-map", "[af]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)])

    chapters = []
    for s, t in zip(segs, starts):
        if s.get("chapter"):
            sec = int(round(t)) if chapters else 0
            chapters.append({"time": f"{sec // 60:02d}:{sec % 60:02d}", "seconds": sec, "title": s["chapter"]})
    (folder / "chapters.json").write_text(json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")
    real = duration(output)
    print(f"✅ 완성: {output} ({real:.1f}초 = {int(real) // 60}분 {int(real) % 60}초, {W}x{H}, {fps}fps)")
    print("   챕터:")
    for c in chapters:
        print(f"   {c['time']} {c['title']}")
    short = [c for a, c in zip(chapters, chapters[1:]) if c["seconds"] - a["seconds"] < 10]
    if len(chapters) < 3 or short:
        print("   ⚠️ 유튜브 챕터 조건(3개 이상, 각 10초 이상)을 확인하세요.")


if __name__ == "__main__":
    main()
