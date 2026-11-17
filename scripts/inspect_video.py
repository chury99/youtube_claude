#!/usr/bin/env python3
"""
완성한 영상을 검수하기 위한 자료를 만든다. (ffmpeg, Pillow 필요 → .venv/bin/python으로 실행)

  1) 기본 정보: 해상도, fps, 길이, 오디오 유무, 세로 9:16 여부
  2) 콘택트 시트: N초 간격 프레임을 시간 표시와 함께 한 장에 모은 PNG (Read 도구로 열어서 직접 확인)
  3) 소리 크기: 통합 음량(LUFS)과 최대 피크(dBTP)
  4) 깜빡임: 밝기가 급격히 바뀌는 횟수가 1초에 3번을 넘는 구간 (광과민성 발작 위험)

사용 예:
    .venv/bin/python scripts/inspect_video.py 5_videos/xxx.mp4 --out 5_videos/xxx_review --every 0.5
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/Helvetica.ttc"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def basic_info(video):
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "format=duration:stream=codec_type,width,height,r_frame_rate",
               "-of", "json", str(video)])
    if out.returncode != 0:
        sys.exit(f"❌ 영상을 읽을 수 없습니다: {out.stderr.strip()}")
    data = json.loads(out.stdout)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if not v:
        sys.exit("❌ 영상 트랙이 없습니다.")
    num, den = v["r_frame_rate"].split("/")
    w, h = v["width"], v["height"]
    return {
        "width": w, "height": h,
        "fps": round(int(num) / int(den), 2),
        "duration": round(float(data["format"]["duration"]), 2),
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
        "vertical_9_16": abs(w / h - 9 / 16) < 0.01,
    }


def contact_sheets(video, out_dir, every, duration, per_sheet=12, cols=6):
    with tempfile.TemporaryDirectory() as tmp:
        r = run(["ffmpeg", "-v", "error", "-i", str(video), "-vf",
                 f"fps=1/{every},scale=270:-2", str(Path(tmp) / "f_%04d.png")])
        if r.returncode != 0:
            sys.exit(f"❌ 프레임 추출 실패: {r.stderr.strip()}")
        frames = sorted(Path(tmp).glob("f_*.png"))
        font = ImageFont.truetype(FONT, 22)
        sheets = []
        for s in range(0, len(frames), per_sheet):
            group = frames[s:s + per_sheet]
            imgs = [Image.open(f).convert("RGB") for f in group]
            fw, fh = imgs[0].size
            rows = -(-len(imgs) // cols)
            sheet = Image.new("RGB", (cols * (fw + 6) + 6, rows * (fh + 36) + 6), (30, 30, 30))
            d = ImageDraw.Draw(sheet)
            for i, im in enumerate(imgs):
                x, y = 6 + (i % cols) * (fw + 6), 6 + (i // cols) * (fh + 36)
                sheet.paste(im, (x, y + 30))
                t = (s + i) * every + every / 2  # fps 필터는 각 구간의 가운데 프레임을 뽑는다
                d.text((x + 4, y + 2), f"{t:.1f}s", font=font, fill=(255, 230, 80))
            path = out_dir / f"sheet_{len(sheets) + 1:02d}.png"
            sheet.save(path)
            sheets.append(str(path))
    return sheets


def loudness(video):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
             "-af", "ebur128=peak=true", "-f", "null", "-"])
    summary = r.stderr[r.stderr.rfind("Summary:"):]
    lufs = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    return {
        "integrated_lufs": float(lufs.group(1)) if lufs else None,
        "true_peak_dbtp": float(peak.group(1)) if peak and peak.group(1) != "-inf" else None,
    }


def flashes(video, fps):
    r = run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf",
             "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"])
    yavg = [float(x) for x in re.findall(r"YAVG=([\d.]+)", r.stdout)]
    # 프레임 사이 밝기 변화가 화면 평균 기준 20% 이상이면 '급변'으로 센다
    jumps = [i for i in range(1, len(yavg)) if abs(yavg[i] - yavg[i - 1]) > 255 * 0.2]
    win = max(int(round(fps)), 1)
    risky = sorted({round(j / fps, 1) for j in jumps
                    if sum(1 for k in jumps if j <= k < j + win) > 3})
    return {"brightness_jumps": len(jumps), "risky_seconds": risky}


def main():
    p = argparse.ArgumentParser(description="영상 검수 자료(정보, 콘택트 시트, 음량, 깜빡임)를 만듭니다.")
    p.add_argument("video")
    p.add_argument("--out", help="콘택트 시트 저장 폴더 (기본: <영상이름>_review)")
    p.add_argument("--every", type=float, default=0.5, help="프레임 간격(초), 기본 0.5")
    args = p.parse_args()

    video = Path(args.video)
    out_dir = Path(args.out) if args.out else video.with_name(video.stem + "_review")
    out_dir.mkdir(parents=True, exist_ok=True)

    info = basic_info(video)
    report = {
        "video": str(video),
        "info": info,
        "contact_sheets": contact_sheets(video, out_dir, args.every, info["duration"]),
        "loudness": loudness(video) if info["has_audio"] else None,
        "flashes": flashes(video, info["fps"]),
    }

    warnings = []
    if not info["vertical_9_16"]:
        warnings.append("세로 9:16이 아닙니다 (기본 720x1280).")
    if info["duration"] > 180:
        warnings.append("3분을 넘어 쇼츠로 올라가지 않습니다.")
    if not info["has_audio"]:
        warnings.append("소리가 없습니다.")
    lo = report["loudness"] or {}
    if lo.get("true_peak_dbtp") is not None and lo["true_peak_dbtp"] > -1:
        warnings.append(f"피크가 {lo['true_peak_dbtp']} dBFS로 높아 찢어질 수 있습니다 (-1 이하 권장).")
    if lo.get("integrated_lufs") is not None and not -20 <= lo["integrated_lufs"] <= -10:
        warnings.append(f"음량 {lo['integrated_lufs']} LUFS (유튜브 기준 -14 근처 권장).")
    if report["flashes"]["risky_seconds"]:
        warnings.append(f"1초에 3번 넘게 번쩍이는 구간: {report['flashes']['risky_seconds']}초")
    report["warnings"] = warnings

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
