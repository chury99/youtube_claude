"""
롱폼 모음집의 꾸민 테두리 그림을 만든다 (build_compilation.py가 사용, skia-python 필요).

화면 구성 (1920x1080 기준):
- 배경: 크림색 니트 V 무늬 + 색깔 동그라미
- 가운데: 세로 쇼츠가 들어갈 자리 (흰 테두리, 둥근 모서리, 그림자)
- 왼쪽: "Episode N" 배지, 이야기 제목, 몇 번째 이야기인지 보여 주는 점
- 오른쪽: 채널 이름, 다음 이야기 미리보기(Up next) 또는 마지막이면 "Thanks for watching!"

영상은 배경 그림(bg) 위에 얹고, 그 위에 둥근 모서리 덮개(fg)를 한 번 더 얹는다.
"""

import skia

BG = skia.Color(250, 236, 214)
STITCH = skia.Color(239, 218, 188)
ACC = skia.Color(240, 132, 92)
TEXT = skia.Color(92, 62, 44)
DOT_OFF = skia.Color(226, 198, 165)
CARD = skia.Color(255, 250, 242)
FAMILY = "Arial Rounded MT Bold"


def video_box(W, H):
    """가운데 영상 자리 (x, y, w, h). 크기는 짝수로 맞춘다."""
    vh = int(round(H * 0.926 / 2)) * 2
    vw = int(round(vh * 9 / 16 / 2)) * 2
    return (W - vw) // 2, (H - vh) // 2, vw, vh


def _font(size):
    return skia.Font(skia.Typeface(FAMILY), size)


def _text(c, s, x, y, size, color, center=False):
    f = _font(size)
    if center:
        x -= f.measureText(s) / 2
    c.drawString(s, x, y, f, skia.Paint(Color=color, AntiAlias=True))


def _wrap(s, size, max_w):
    f = _font(size)
    lines, cur = [], ""
    for w in s.split():
        t = (cur + " " + w).strip()
        if cur and f.measureText(t) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def _fit(s, size, max_w, max_lines, min_size=28):
    """max_lines 줄, max_w 폭 안에 들어가도록 글자 크기를 줄인다."""
    while True:
        lines = _wrap(s, size, max_w)
        if len(lines) <= max_lines and all(_font(size).measureText(l) <= max_w for l in lines):
            return lines, size
        if size <= min_size:  # 그래도 길면 마지막 줄을 … 로 줄인다
            lines = lines[:max_lines]
            f = _font(size)
            last = lines[-1] + " …" if len(_wrap(s, size, max_w)) > max_lines else lines[-1]
            while f.measureText(last) > max_w and " " in last.rstrip(" …"):
                last = last.rstrip(" …").rsplit(" ", 1)[0] + " …"
            lines[-1] = last
            return lines, size
        size -= 4


def render_bg(out, W, H, episode, total, title, channel, next_title=None, next_thumb=None):
    s = W / 1920.0
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(BG)
    c.save()
    c.scale(s, s)
    W0, H0 = 1920, 1080

    # 니트 무늬
    p = skia.Paint(Color=STITCH, AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7,
                   StrokeCap=skia.Paint.kRound_Cap)
    for y in range(-20, H0 + 40, 34):
        for x in range(-20, W0 + 40, 40):
            c.drawLine(x, y, x + 16, y + 22, p)
            c.drawLine(x + 32, y, x + 16, y + 22, p)
    for x, y, r, col in [(140, 140, 46, (255, 205, 120)), (520, 930, 34, (150, 205, 225)),
                         (1780, 960, 50, (255, 180, 170)), (1420, 120, 30, (170, 215, 160)),
                         (300, 1010, 26, (255, 180, 170)), (1840, 420, 24, (255, 205, 120))]:
        c.drawCircle(x, y, r, skia.Paint(Color=skia.Color(*col), AntiAlias=True))

    # 영상 카드 (그림자 + 흰 테두리)
    vx, vy, vw, vh = [v / s for v in video_box(W, H)]
    card = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(vx - 12, vy - 12, vw + 24, vh + 24), 40, 40)
    shadow = skia.Paint(Color=skia.Color(120, 80, 50, 90), AntiAlias=True,
                        MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 18))
    c.save(); c.translate(0, 10); c.drawRRect(card, shadow); c.restore()
    c.drawRRect(card, skia.Paint(Color=skia.ColorWHITE, AntiAlias=True))

    # 왼쪽: 에피소드 배지, 제목, 진행 점
    LX = 120
    left_w = vx - 12 - LX - 50
    lines, size = _fit(title, 72, left_w, 4)
    lh = size * 1.14
    block = 64 + 40 + lh * len(lines) + 50 + 26
    top = (H0 - block) / 2
    label = f"Episode {episode}"
    bw = _font(36).measureText(label) + 70
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(LX, top, bw, 64), 32, 32),
                skia.Paint(Color=ACC, AntiAlias=True))
    _text(c, label, LX + bw / 2, top + 45, 36, skia.ColorWHITE, center=True)
    y = top + 64 + 40 + size * 0.9
    for line in lines:
        _text(c, line, LX, y, size, TEXT)
        y += lh
    gap = min(44, left_w / max(total, 1))
    dy = y - lh + size * 0.3 + 60
    for i in range(total):
        on = i == episode - 1
        c.drawCircle(LX + 14 + i * gap, dy, 13 if on else min(10, gap * 0.3),
                     skia.Paint(Color=ACC if on else DOT_OFF, AntiAlias=True))

    # 오른쪽: 채널 이름, 다음 이야기
    RX = vx + vw + 12 + 110
    right_w = W0 - RX - 100
    c.drawCircle(RX + 34, 200, 34, skia.Paint(Color=ACC, AntiAlias=True))
    _text(c, channel[:1].lower(), RX + 34, 216, 46, skia.ColorWHITE, center=True)
    cname, csize = _fit(channel, 50, right_w - 84, 1)
    _text(c, cname[0], RX + 84, 218, csize, TEXT)
    box = skia.Rect.MakeXYWH(RX, 470, right_w, 300)
    c.drawRRect(skia.RRect.MakeRectXY(box, 28, 28), skia.Paint(Color=CARD, AntiAlias=True))
    if next_title:
        _text(c, "Up next", RX + 30, 530, 34, ACC)
        tx = RX + 30
        if next_thumb:
            th = skia.Rect.MakeXYWH(RX + 30, 555, 125, 190)
            img = skia.Image.open(str(next_thumb))
            c.save(); c.clipRRect(skia.RRect.MakeRectXY(th, 16, 16), doAntiAlias=True)
            c.drawImageRect(img, th, skia.SamplingOptions(skia.FilterMode.kLinear)); c.restore()
            tx = RX + 180
        nl, ns = _fit(next_title, 44, RX + right_w - 24 - tx, 4)
        ny = 650 - (len(nl) - 1) * ns * 1.18 / 2 + ns * 0.35
        for line in nl:
            _text(c, line, tx, ny, ns, TEXT)
            ny += ns * 1.18
    else:
        for i, line in enumerate(["Thanks for", "watching!"]):
            _text(c, line, RX + right_w / 2, 600 + i * 70, 56, TEXT, center=True)
        _text(c, "See you next time", RX + right_w / 2, 735, 32, ACC, center=True)
    c.restore()
    surf.makeImageSnapshot().save(str(out), skia.kPNG)


def render_fg(out, W, H):
    """영상 네 모서리를 둥글게 덮는 흰 조각 (나머지는 투명)."""
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    vx, vy, vw, vh = video_box(W, H)
    r = 30 * W / 1920.0
    path = skia.Path()
    path.addRect(skia.Rect.MakeXYWH(vx, vy, vw, vh))
    path.addRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(vx, vy, vw, vh), r, r))
    path.setFillType(skia.PathFillType.kEvenOdd)
    c.drawPath(path, skia.Paint(Color=skia.ColorWHITE, AntiAlias=True))
    surf.makeImageSnapshot().save(str(out), skia.kPNG)
