"""Рисует карточку выписки в PNG (повторяет исходный макет)."""
import io
import os
from PIL import Image, ImageDraw, ImageFont

from payroll import POINTS, Row

COMPANY = os.getenv("COMPANY_NAME", "EYEPHOTO")

HERE = os.path.dirname(os.path.abspath(__file__))
def _font_path(name):
    for d in (os.path.join(HERE, "fonts"), "/usr/share/fonts/truetype/dejavu"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(name)


REG = _font_path("DejaVuSans.ttf")
BOLD = _font_path("DejaVuSans-Bold.ttf")

W, H = 1020, 960
BG = "#e5e5e5"
DARK = "#1c1c1e"
GRAY = "#8e8e93"
LABEL = "#6e6e73"
VALUE = "#3a3a3c"
GREEN = "#16a34a"
LINE = "#d9d9d9"

CARD = (32, 20, 989, 940)
HEADER_H = 300
LEFT, RIGHT = 85, 935

TAG_COLORS = {             # (фон, текст)
    "msk": ("#fdeee3", "#c2570c"),
    "spb": ("#e6effc", "#1d5fc4"),
}


def _f(path, size):
    return ImageFont.truetype(path, size)


def money(v: float) -> str:
    v = round(v, 2)
    s = f"{v:,.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
    return s.replace(",", " ").replace(".", ",") + " ₽"


def num(v: float) -> str:
    return (f"{v:g}").replace(".", ",")


def _fit(draw, text, path, size, max_w):
    while size > 20 and draw.textlength(text, font=_f(path, size)) > max_w:
        size -= 2
    return _f(path, size)


def render(row: Row, period: str) -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = CARD
    r = 56

    # карточка + тёмная шапка
    d.rounded_rectangle(CARD, r, fill="white")
    d.rounded_rectangle((x0, y0, x1, y0 + HEADER_H), r, fill=DARK, corners=(True, True, False, False))

    city = POINTS[row.point][1]
    payout = money(row.payout)

    # шапка
    d.text((LEFT, y0 + 72), f"{COMPANY} · {period}", font=_f(REG, 26), fill=GRAY, anchor="ls")
    amount_font = _f(BOLD, 56)
    amount_w = d.textlength(payout, font=amount_font)
    name_font = _fit(d, row.name, BOLD, 64, RIGHT - LEFT - amount_w - 60)
    d.text((LEFT, y0 + 175), row.name, font=name_font, fill="white", anchor="ls")
    d.text((LEFT, y0 + 228), f"{num(row.hours)} ч · {row.point}", font=_f(REG, 28), fill=GRAY, anchor="ls")
    d.text((RIGHT - amount_w, y0 + 138), "к выплате", font=_f(REG, 22), fill=GRAY, anchor="ls")
    d.text((RIGHT, y0 + 222), payout, font=amount_font, fill="white", anchor="rs")

    # плашка точки
    bg, fg = TAG_COLORS[city]
    tag_font = _f(BOLD, 24)
    tw = d.textlength(row.point, font=tag_font)
    ty = y0 + HEADER_H + 35
    d.rounded_rectangle((LEFT, ty, LEFT + tw + 42, ty + 53), 14, fill=bg)
    d.text((LEFT + 21, ty + 27), row.point, font=tag_font, fill=fg, anchor="lm")

    # строки расчёта
    lab, val = _f(REG, 28), _f(REG, 28)
    rows = [
        ("Часы × ставка", f"{num(row.hours)} × {num(row.rate)}", VALUE),
        ("Зарплата", money(row.salary), VALUE),
        ("Продажи", money(row.sales), VALUE),
        (f"КПИ", ("+" if row.kpi > 0 else "") + money(row.kpi), GREEN if row.kpi > 0 else VALUE),
    ]
    y = y0 + 465
    for label, value, color in rows:
        d.text((LEFT, y), label, font=lab, fill=LABEL, anchor="ls")
        d.text((RIGHT, y), value, font=val, fill=color, anchor="rs")
        y += 62

    # пунктир
    ly = y - 20
    for x in range(LEFT, RIGHT, 22):
        d.line((x, ly, min(x + 12, RIGHT), ly), fill=LINE, width=2)

    y = ly + 75
    for label, value in (("Итог", money(row.total)), ("К выплате", payout)):
        d.text((LEFT, y), label, font=lab, fill=LABEL, anchor="ls")
        d.text((RIGHT, y), value, font=_f(BOLD, 30), fill=DARK, anchor="rs")
        y += 60

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
