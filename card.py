"""Рисует расчётный лист в PNG: шапка, блок на каждую точку, общий итог."""
import io
import os
from PIL import Image, ImageDraw, ImageFont

from payroll import POINTS, Person

COMPANY = os.getenv("COMPANY_NAME", "EYEPhoto")

HERE = os.path.dirname(os.path.abspath(__file__))


def _font_path(name):
    for d in (os.path.join(HERE, "fonts"), "/usr/share/fonts/truetype/dejavu"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(name)


REG = _font_path("DejaVuSans.ttf")
BOLD = _font_path("DejaVuSans-Bold.ttf")

W = 1020
BG = "#f2f2f2"
DARK = "#0c0d11"
GRAY = "#9a9aa0"
LABEL = "#3a3a3c"
VALUE = "#1c1c1e"
GREEN = "#16a34a"
RED = "#c0392b"
LINE = "#d0d0d4"

M = 16                     # отступ карточки от края картинки
LEFT, RIGHT = 70, W - 70
HEADER_H = 300
ROW = 58
R = 48

_cache = {}


def F(path, size):
    k = (path, size)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(path, size)
    return _cache[k]


def money(v: float) -> str:
    v = round(v, 2)
    neg = v < 0
    v = abs(v)
    s = f"{v:,.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
    return ("−" if neg else "") + s.replace(",", " ").replace(".", ",") + " ₽"


def num(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def _rows(e):
    rows = [
        ("Часы × ставка", f"{num(e.hours)} × {num(e.rate)}", VALUE),
        ("Зарплата", money(e.salary), VALUE),
        ("Продажи", money(e.sales), VALUE),
        ("КПИ", ("+" if e.kpi > 0 else "") + money(e.kpi), GREEN if e.kpi > 0 else VALUE),
    ]
    if e.option > 0:
        rows.append(("Штраф", money(-e.option), RED))
    elif e.option < 0:
        rows.append(("Премия", "+" + money(-e.option), GREEN))
    if e.ofzp:
        rows.append(("Офиц. зп (удержано)", money(-e.ofzp), RED))
    return rows


def _section_h(e):
    return 40 + 54 + 60 + len(_rows(e)) * ROW + 20 + 70 + 62 + 30


def render(p: Person, period: str) -> bytes:
    multi = len(p.entries) > 1
    body_h = sum(_section_h(e) for e in p.entries) + 30
    footer_h = 190 if multi else 0
    H = M + HEADER_H + body_h + footer_h + M
    if not multi:
        H += 20

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = M, M, W - M, H - M

    d.rounded_rectangle((x0, y0, x1, y1), R, fill="white")
    d.rounded_rectangle((x0, y0, x1, y0 + HEADER_H), R, fill=DARK, corners=(True, True, False, False))

    total = money(p.payout)
    points = ", ".join(dict.fromkeys(POINTS[e.point][0] for e in p.entries))

    # шапка
    d.text((LEFT, y0 + 62), f"{COMPANY} • {period}", font=F(REG, 26), fill=GRAY, anchor="ls")
    amount_font = F(BOLD, 58)
    aw = d.textlength(total, font=amount_font)
    size = 66
    while size > 30 and d.textlength(p.name, font=F(BOLD, size)) > RIGHT - LEFT - aw - 50:
        size -= 2
    d.text((LEFT, y0 + 152), p.name, font=F(BOLD, size), fill="white", anchor="ls")
    d.text((LEFT, y0 + 215), f"{num(p.hours)} ч • {points}", font=F(REG, 30), fill="#e6e6ea", anchor="ls")
    d.text((RIGHT, y0 + 128), "К ВЫПЛАТЕ", font=F(REG, 24), fill="#e6e6ea", anchor="rs")
    d.text((RIGHT, y0 + 205), total, font=amount_font, fill="white", anchor="rs")

    # блоки по точкам
    y = y0 + HEADER_H
    lab = F(REG, 29)
    for e in p.entries:
        label, bg, fg = POINTS[e.point]
        ty = y + 40
        tf = F(BOLD, 25)
        tw = d.textlength(label, font=tf)
        d.rounded_rectangle((LEFT, ty, LEFT + max(tw + 40, 112), ty + 54), 14, fill=bg)
        d.text((LEFT + 20, ty + 27), label, font=tf, fill=fg, anchor="lm")
        ry = ty + 54 + 60
        for name, value, color in _rows(e):
            d.text((LEFT, ry), name, font=lab, fill=LABEL, anchor="ls")
            d.text((RIGHT, ry), value, font=lab, fill=color, anchor="rs")
            ry += ROW
        ly = ry - 20
        d.line((LEFT, ly, RIGHT, ly), fill=LINE, width=3)
        ry = ly + 70
        d.text((LEFT, ry), "Итого", font=F(BOLD, 29), fill=VALUE, anchor="ls")
        d.text((RIGHT, ry), money(e.total), font=F(BOLD, 31), fill=VALUE, anchor="rs")
        ry += 62
        d.text((LEFT, ry), "К выплате", font=lab, fill=VALUE, anchor="ls")
        d.text((RIGHT, ry), money(e.payout), font=F(BOLD, 31), fill=VALUE, anchor="rs")
        y += _section_h(e)

    # общий итог
    if multi:
        fy = y1 - footer_h
        d.rounded_rectangle((x0, fy, x1, y1), R, fill=DARK, corners=(False, False, True, True))
        d.text((LEFT, fy + footer_h // 2 + 12), "Итого к выплате", font=F(REG, 34), fill="white", anchor="ls")
        d.text((RIGHT, fy + footer_h // 2 + 22), total, font=F(BOLD, 60), fill="white", anchor="rs")

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
