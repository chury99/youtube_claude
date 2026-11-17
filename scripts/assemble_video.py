#!/usr/bin/env python3
"""
AI로 생성한 컷들을 하나의 쇼츠 영상으로 합치는 편집기 (ffmpeg 필요)

에피소드 폴더의 edit.json 설정대로
  1) 각 컷을 세로 720x1280(720p) / 30fps로 맞추고 (비율이 다르면 위아래·좌우 블러 배경으로 채움)
  2) 앞뒤를 잘라 템포를 조절한 뒤
  3) 순서대로 이어 붙이고
  4) 배경음악을 깔고 끝부분을 페이드아웃 한다.

컷에 소리가 없으면 무음으로 채운다. (Veo처럼 소리가 있는 컷은 원래 소리를 유지)

사용 예:
    python3 scripts/assemble_video.py series/pet_human/ep01_vet_day
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def probe(path):
    """영상 길이(초)와 오디오 트랙 유무를 확인한다."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(out.stdout)
    duration = float(info["format"]["duration"])
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    return duration, has_audio


def main():
    if len(sys.argv) != 2:
        sys.exit("사용법: python3 scripts/assemble_video.py <에피소드 폴더>")
    if not shutil.which("ffmpeg"):
        sys.exit("❌ ffmpeg가 없습니다. 설치: brew install ffmpeg")

    ep_dir = Path(sys.argv[1]).resolve()
    cfg_path = ep_dir / "edit.json"
    if not cfg_path.exists():
        sys.exit(f"❌ 설정 파일이 없습니다: {cfg_path}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    w, h, fps = cfg.get("width", 720), cfg.get("height", 1280), cfg.get("fps", 30)

    missing = [c["file"] for c in cfg["clips"] if not (ep_dir / c["file"]).exists()]
    if missing:
        sys.exit("❌ 아직 없는 컷이 있습니다. 아래 위치에 영상을 넣어 주세요:\n   "
                 + "\n   ".join(str(ep_dir / m) for m in missing))

    inputs, filters, concat_inputs = [], [], []
    total = 0.0
    print("🎞️  컷 정보")
    for i, clip in enumerate(cfg["clips"]):
        path = ep_dir / clip["file"]
        duration, has_audio = probe(path)
        start = float(clip.get("start") or 0)
        end = float(clip["end"]) if clip.get("end") is not None else duration
        end = min(end, duration)
        if end <= start:
            sys.exit(f"❌ {clip['file']}: start({start})가 end({end})보다 크거나 같습니다.")
        length = end - start
        total += length
        print(f"   {i + 1}. {clip['file']}  {start:.1f}~{end:.1f}초 ({length:.1f}초)"
              f"{'' if has_audio else '  [소리 없음]'}")

        inputs += ["-i", str(path)]
        # 영상: 블러 배경 위에 원본을 비율 유지해서 올림 → 어떤 비율의 컷이 와도 9:16로 맞춰짐
        filters.append(
            f"[{i}:v]trim={start}:{end},setpts=PTS-STARTPTS,fps={fps},split[b{i}][f{i}];"
            f"[b{i}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2[bg{i}];"
            f"[f{i}]scale={w}:{h}:force_original_aspect_ratio=decrease[fg{i}];"
            f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v{i}]"
        )
        vol = clip.get("volume", 1.0)
        if has_audio:
            filters.append(
                f"[{i}:a]atrim={start}:{end},asetpts=PTS-STARTPTS,"
                f"aresample=48000,aformat=channel_layouts=stereo,volume={vol}[a{i}]"
            )
        else:
            filters.append(
                f"anullsrc=r=48000:cl=stereo,atrim=0:{length},asetpts=PTS-STARTPTS[a{i}]"
            )
        concat_inputs.append(f"[v{i}][a{i}]")

    n = len(cfg["clips"])
    filters.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=1[vcat][acat]")

    fade = float(cfg.get("fade_out", 0) or 0)
    fade_start = max(total - fade, 0)
    vfinal = f"[vcat]fade=t=out:st={fade_start}:d={fade}[vout]" if fade else "[vcat]null[vout]"
    filters.append(vfinal)

    bgm = cfg.get("bgm")
    bgm_path = ep_dir / bgm if bgm else None
    if bgm_path and bgm_path.exists():
        inputs += ["-stream_loop", "-1", "-i", str(bgm_path)]  # 음악이 짧으면 반복
        filters.append(
            f"[{n}:a]atrim=0:{total},asetpts=PTS-STARTPTS,aresample=48000,"
            f"aformat=channel_layouts=stereo,volume={cfg.get('bgm_volume', 0.25)}[bgm]"
        )
        filters.append("[acat][bgm]amix=inputs=2:duration=first:normalize=0[amix]")
        alabel = "amix"
        print(f"🎵 배경음악: {bgm}")
    else:
        alabel = "acat"
        if bgm:
            print(f"ℹ️  배경음악 파일이 없어 생략합니다: {bgm_path}")
    if fade:
        filters.append(f"[{alabel}]afade=t=out:st={fade_start}:d={fade}[aout]")
    else:
        filters.append(f"[{alabel}]anull[aout]")

    output = ep_dir / cfg.get("output", "output.mp4")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(output),
    ]
    print(f"\n⏳ 편집 중... (총 {total:.1f}초)")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit("❌ ffmpeg 편집 실패")
    print(f"✅ 완성: {output}")
    if total > 60:
        print("⚠️  60초를 넘습니다. 쇼츠는 3분까지 가능하지만 이 시리즈는 20~40초를 권장합니다.")


if __name__ == "__main__":
    main()
