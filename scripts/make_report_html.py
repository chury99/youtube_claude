#!/usr/bin/env python3
"""
분석가의 채널 리포트 txt를 스마트폰에서 보기 좋은 HTML 한 파일로 바꾼다. 표준 라이브러리만 사용한다.
텔레그램으로 받아 휴대폰에서 바로 열 수 있도록 외부 파일·글꼴·스크립트 없이 한 파일에 모두 담는다.

- 한 줄 너비(최대 560px), 큰 글씨, 다크 모드 지원
- 표(a | b | c)는 휴대폰에서 가로 스크롤 대신 행마다 카드로 보여 준다
- 섹션은 눌러서 접고 펴는 방식. [1] 요약과 [7] 전략은 처음부터 펼침
- 같은 폴더의 channel_data*.json이 있으면 상단에 핵심 숫자 카드를 붙인다

사용 예:
    python3 scripts/make_report_html.py 6_reports/20261117_채널분석/채널분석.txt
    python3 scripts/make_report_html.py <리포트.txt> --data <channel_data.json> --out <리포트.html>
"""

import argparse
import html
import json
import re
from pathlib import Path

OPEN_SECTIONS = {"1", "7"}          # 처음부터 펼칠 섹션
HIGHLIGHT_SECTIONS = {"1": "hl-summary", "7": "hl-strategy"}

CSS = """
:root{--bg:#f4f6fa;--card:#fff;--text:#1d2330;--muted:#6b7385;--line:#e3e7ef;--accent:#3b6cf6;
--accent-soft:#eaf0ff;--good:#10a37f;--good-soft:#e6f7f1;--warn:#d97706;--warn-soft:#fff4e0;--chip:#f0f2f7}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#181c24;--text:#e8ebf2;--muted:#9aa3b5;--line:#2a303c;
--accent:#7c9cff;--accent-soft:#1d2741;--good:#3ccf9e;--good-soft:#14302a;--warn:#f0a43a;--warn-soft:#33270f;--chip:#222836}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Pretendard","Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif;
word-break:keep-all;overflow-wrap:anywhere}
.wrap{max-width:560px;margin:0 auto;padding:16px 14px 48px}
header{padding:8px 4px 14px}
header .kicker{font-size:13px;color:var(--accent);font-weight:700;letter-spacing:.02em}
header h1{font-size:24px;line-height:1.3;margin:4px 0 6px}
header .meta{font-size:13px;color:var(--muted)}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:4px 0 14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px}
.kpi .v{font-size:22px;font-weight:800;line-height:1.2}
.kpi .l{font-size:12px;color:var(--muted);margin-top:2px}
.videos{margin:0 0 14px}
.video{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:8px}
.video .t{font-weight:700;font-size:15px;line-height:1.4}
.video .tags{margin-top:6px;display:flex;flex-wrap:wrap;gap:6px}
.tag{font-size:12px;background:var(--chip);border-radius:999px;padding:2px 9px;color:var(--muted)}
.tag.on{background:var(--accent-soft);color:var(--accent)}
details.sec{background:var(--card);border:1px solid var(--line);border-radius:16px;margin:0 0 12px;overflow:hidden}
details.sec>summary{list-style:none;cursor:pointer;padding:14px 16px;font-weight:800;font-size:17px;display:flex;gap:10px;align-items:center}
details.sec>summary::-webkit-details-marker{display:none}
details.sec>summary .n{flex:none;min-width:28px;height:28px;border-radius:9px;background:var(--accent-soft);color:var(--accent);
display:flex;align-items:center;justify-content:center;font-size:14px}
details.sec>summary .chev{margin-left:auto;color:var(--muted);transition:transform .2s;font-size:14px}
details.sec[open]>summary .chev{transform:rotate(90deg)}
.body{padding:0 16px 14px}
.hl-summary{border-color:var(--accent)}
.hl-summary>summary{background:var(--accent-soft)}
.hl-strategy{border-color:var(--good)}
.hl-strategy>summary{background:var(--good-soft)}
.hl-strategy>summary .n{background:var(--good);color:#fff}
h3{font-size:15px;margin:16px 0 6px;color:var(--accent)}
p{margin:6px 0}
ul,ol{margin:6px 0;padding-left:20px}
li{margin:5px 0}
li.sub{list-style:none;margin-left:-4px;color:var(--muted);font-size:15px}
b.lb{color:var(--text)}
.ref{font-size:12px;color:var(--muted);background:var(--chip);border-radius:6px;padding:0 5px;white-space:nowrap}
.rows{display:flex;flex-direction:column;gap:8px;margin:8px 0}
.row{border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.row .h{font-weight:700;margin-bottom:4px;font-size:15px}
.row dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:2px 10px;font-size:14px}
.row dt{color:var(--muted);white-space:nowrap}
.row dd{margin:0}
.src{font-size:13px;color:var(--muted)}
.foot{font-size:12px;color:var(--muted);text-align:center;margin-top:20px}
"""


def esc(t):
    return html.escape(t, quote=False)


def inline(t):
    """한 줄 안의 꾸밈: [채널] 같은 출처 표시, '근거:' 같은 라벨 굵게."""
    t = esc(t)
    t = re.sub(r"\[(채널|CSV[^\]]*|기획안[^\]]*|편집 기록[^\]]*)\]", r'<span class="ref">\1</span>', t)
    t = re.sub(r"^((?:[가-힣A-Za-z0-9·/ ]{1,14})):\s", r'<b class="lb">\1:</b> ', t)
    return t


def table_rows(lines):
    head = [c.strip() for c in lines[0].split("|")]
    out = ['<div class="rows">']
    for ln in lines[1:]:
        cells = [c.strip() for c in ln.split("|")]
        out.append('<div class="row">')
        out.append(f'<div class="h">{inline(cells[0])}</div><dl>')
        for k, v in zip(head[1:], cells[1:]):
            if v:
                out.append(f"<dt>{esc(k)}</dt><dd>{inline(v)}</dd>")
        out.append("</dl></div>")
    out.append("</div>")
    return out


def render_body(lines):
    out, i, mode = [], 0, None  # mode: ul / ol

    def close():
        nonlocal mode
        if mode:
            out.append(f"</{mode}>")
            mode = None

    while i < len(lines):
        raw = lines[i].rstrip()
        s = raw.strip()
        if not s:
            close(); i += 1; continue
        # 표: 연속된 ' | ' 줄 (2줄 이상)
        if " | " in s:
            block = []
            while i < len(lines) and " | " in lines[i]:
                block.append(lines[i].strip()); i += 1
            close()
            out += table_rows(block) if len(block) >= 2 else [f"<p>{inline(block[0])}</p>"]
            continue
        m_num = re.match(r"^(\d+)\.\s+(.*)", s)
        if s.startswith("- "):
            if mode != "ul":
                close(); out.append("<ul>"); mode = "ul"
            out.append(f"<li>{inline(s[2:])}</li>")
        elif m_num and not raw.startswith(" "):
            if mode != "ol":
                close(); out.append("<ol>"); mode = "ol"
            out.append(f"<li>{inline(m_num.group(2))}</li>")
        elif raw.startswith((" ", "\t")) and (s.startswith(("·", "(", "-")) or mode):
            if not mode:
                out.append("<ul>"); mode = "ul"
            out.append(f'<li class="sub">{inline(s.lstrip("·- "))}</li>')
        elif len(s) <= 40 and not s.endswith((".", "다", "요")):
            close(); out.append(f"<h3>{inline(s)}</h3>")
        else:
            close(); out.append(f"<p>{inline(s)}</p>")
        i += 1
    close()
    return out


def parse(txt):
    lines = txt.splitlines()
    title, meta, pre, sections, cur = "", "", [], [], None
    for ln in lines:
        if re.match(r"^=+$", ln.strip()):
            continue
        m = re.match(r"^\[(\d+)\]\s*(.*)", ln.strip())
        if m:
            cur = {"n": m.group(1), "title": m.group(2), "lines": []}
            sections.append(cur)
            continue
        if cur is None:
            if not title and ln.strip():
                title = ln.strip()
            elif not meta and ln.strip() and ("작성일" in ln or "기간" in ln):
                meta = ln.strip()
            else:
                pre.append(ln)
        else:
            cur["lines"].append(ln)
    return title, meta, pre, sections


def fmt_int(n):
    try:
        return f"{int(float(n)):,}"
    except (TypeError, ValueError):
        return "–"


def kpi_block(data):
    c, a, pr = data.get("channel", {}), data.get("analytics", {}), data.get("period", {})
    tot = (a.get("totals", {}).get("rows") or [{}])[0]
    avgp = tot.get("averageViewPercentage")
    cards = [
        (fmt_int(c.get("subscribers")), "구독자"),
        (fmt_int(c.get("total_views")), "총 조회수"),
        (fmt_int(c.get("video_count")), "영상 수"),
        (fmt_int(tot.get("views")), f"기간 조회수 ({pr.get('days', '?')}일)"),
        (f"{float(avgp):.0f}%" if avgp not in (None, "") else "–", "평균 시청률"),
        (fmt_int(tot.get("subscribersGained")), "기간 새 구독"),
    ]
    out = ['<div class="kpis">'] + [f'<div class="kpi"><div class="v">{v}</div><div class="l">{esc(l)}</div></div>'
                                    for v, l in cards] + ["</div>"]
    vids = data.get("videos", [])
    if vids:
        out.append('<div class="videos">')
        for v in vids[:10]:
            kids = {True: "아동용", False: "일반"}.get(v.get("made_for_kids"), "아동용 ?")
            out.append(
                f'<div class="video"><div class="t">{esc(v.get("title") or "")}</div><div class="tags">'
                f'<span class="tag on">조회 {fmt_int(v.get("views"))}</span>'
                f'<span class="tag">{esc(v.get("privacy") or "")}</span>'
                f'<span class="tag">{kids}</span>'
                f'<span class="tag">{v.get("duration_s") or "?"}초</span>'
                f'<span class="tag">{esc((v.get("published") or "")[:10])}</span></div></div>')
        out.append("</div>")
    return out


def find_data(txt_path):
    m = re.search(r"_(\d+)$", txt_path.stem)
    cand = txt_path.with_name(f"channel_data_{m.group(1)}.json" if m else "channel_data.json")
    if cand.exists():
        return cand
    found = sorted(txt_path.parent.glob("channel_data*.json"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def build(txt_path, data_path=None):
    title, meta, pre, sections = parse(txt_path.read_text(encoding="utf-8"))
    name = title.split("—")[-1].strip() if "—" in title else title
    doc = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>",
           "<meta name='color-scheme' content='light dark'>",
           f"<title>{esc(name)} 채널 리포트</title><style>{CSS}</style></head><body><div class='wrap'>",
           f"<header><div class='kicker'>📊 채널 분석 리포트</div><h1>{esc(name)}</h1>"
           f"<div class='meta'>{esc(meta)}</div></header>"]
    if data_path and data_path.exists():
        doc += kpi_block(json.loads(data_path.read_text(encoding="utf-8")))
    for s in sections:
        cls = "sec " + HIGHLIGHT_SECTIONS.get(s["n"], "")
        opened = " open" if s["n"] in OPEN_SECTIONS else ""
        doc.append(f"<details class='{cls.strip()}'{opened}><summary><span class='n'>{s['n']}</span>"
                   f"<span>{esc(s['title'])}</span><span class='chev'>›</span></summary><div class='body'>")
        doc += render_body(s["lines"])
        doc.append("</div></details>")
    pre_lines = [l for l in pre if l.strip()]
    if pre_lines:
        doc.append("<details class='sec'><summary><span class='n'>i</span><span>출처와 데이터</span>"
                   "<span class='chev'>›</span></summary><div class='body src'>")
        doc += render_body(pre_lines)
        doc.append("</div></details>")
    doc.append(f"<div class='foot'>{esc(txt_path.name)} · 분석가 자동 생성</div></div></body></html>")
    return "\n".join(doc)


def main():
    ap = argparse.ArgumentParser(description="채널 리포트 txt → 모바일용 HTML")
    ap.add_argument("report", help="분석가 리포트 txt")
    ap.add_argument("--data", help="channel_data JSON (기본: 같은 폴더에서 찾음)")
    ap.add_argument("--out", help="저장할 HTML (기본: 리포트와 같은 이름 .html)")
    a = ap.parse_args()
    txt = Path(a.report)
    data = Path(a.data) if a.data else find_data(txt)
    out = Path(a.out) if a.out else txt.with_suffix(".html")
    out.write_text(build(txt, data), encoding="utf-8")
    print(f"✅ HTML 리포트: {out} ({out.stat().st_size / 1024:.0f}KB)" + (f" · 데이터 {data.name}" if data else ""))


if __name__ == "__main__":
    main()
