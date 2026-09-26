"""Точки, расчёт и разбор входных данных (текст и Excel/CSV)."""
import csv
import io
import math
import re
from dataclasses import dataclass

KPI_PERCENT = 4          # КПИ = 4% от продаж
ROUND_TO = 100           # «К выплате» округляется вверх до сотни

# code: (полное название, город)
POINTS = {
    "ЛЕС": ("Лесная", "msk"),
    "ДЗ": ("Дизайн завод", "msk"),
    "3В": ("Три вокзала", "msk"),
    "СЕВ": ("Севкабель", "spb"),
    "ПИК": ("Пик", "spb"),
    "ВКЗ": ("Вокзал", "spb"),
}

_ALIASES = {
    "ЛЕС": ["лес", "лесная"],
    "ДЗ": ["дз", "дизайнзавод", "дизайн", "завод"],
    "3В": ["3в", "тривокзала", "3вокзала", "трёхвокзалов"],
    "СЕВ": ["сев", "севкабель", "ск", "севкабельпорт"],
    "ПИК": ["пик"],
    "ВКЗ": ["вкз", "вокзал", "спбвокзал", "вокзалспб"],
}


def _norm(s: str) -> str:
    return re.sub(r"[\s.\-_«»\"']", "", s.lower().replace("ё", "е"))


ALIAS_MAP = {_norm(a): code for code, al in _ALIASES.items() for a in al}
for _code, (_name, _) in POINTS.items():
    ALIAS_MAP[_norm(_code)] = _code
    ALIAS_MAP[_norm(_name)] = _code


def find_point(s: str):
    return ALIAS_MAP.get(_norm(s))


@dataclass
class Row:
    name: str
    point: str      # код точки
    hours: float
    rate: float
    sales: float

    @property
    def salary(self) -> float:
        return self.hours * self.rate

    @property
    def kpi(self) -> float:
        return self.sales * KPI_PERCENT / 100

    @property
    def total(self) -> float:
        return self.salary + self.kpi

    @property
    def payout(self) -> int:
        return int(math.ceil(round(self.total, 2) / ROUND_TO) * ROUND_TO)


class ParseError(Exception):
    pass


def to_num(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).replace(" ", "").replace(" ", "").replace("₽", "").replace("р", "").replace(",", ".")
    if not t:
        raise ValueError("пусто")
    return float(t)


PERIOD_RE = re.compile(r"(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s*[-–—]\s*(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)")


def find_period(text: str):
    m = PERIOD_RE.search(text or "")
    return f"{m.group(1)} – {m.group(2)}" if m else None


def parse_line(line: str) -> Row:
    """«Стас ДЗ 55 340 66300» или «Стас; Дизайн завод; 55; 340; 66 300»."""
    if re.search(r"[;\t|]", line):
        f = [x.strip() for x in re.split(r"[;\t|]", line) if x.strip()]
        if len(f) != 5:
            raise ParseError("нужно 5 полей: имя; точка; часы; ставка; продажи")
        name, pt, h, r, s = f
        code = find_point(pt) or find_point(name)
        if code and not find_point(pt):
            name, pt = pt, name
        if not code:
            raise ParseError(f"не знаю точку «{pt}»")
        return Row(name, code, to_num(h), to_num(r), to_num(s))

    tok = line.split()
    if len(tok) < 5:
        raise ParseError("нужно: имя точка часы ставка продажи")
    try:
        h, r, s = (to_num(x) for x in tok[-3:])
    except ValueError:
        raise ParseError("последние три значения должны быть числами (часы ставка продажи)")
    words = tok[:-3]
    # точка в конце (1–2 слова) или в начале
    for n in (2, 1):
        if len(words) > n and find_point(" ".join(words[-n:])):
            return Row(" ".join(words[:-n]), find_point(" ".join(words[-n:])), h, r, s)
        if len(words) > n and find_point(" ".join(words[:n])):
            return Row(" ".join(words[n:]), find_point(" ".join(words[:n])), h, r, s)
    raise ParseError("не нашёл точку. Точки: " + ", ".join(f"{c} ({n})" for c, (n, _) in POINTS.items()))


def parse_text(text: str):
    rows, errors = [], []
    period = None
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        p = find_period(line)
        if p and not re.search(r"\d+\s+\d+\s+\d+\s*$", line):
            period = p
            continue
        try:
            rows.append(parse_line(line))
        except (ParseError, ValueError) as e:
            errors.append(f"Строка {i} «{line}»: {e}")
    return period, rows, errors


# ---------- таблицы ----------
_COLS = {
    "name": ("имя", "фио", "сотрудник", "работник"),
    "point": ("точка", "локац", "магазин"),
    "hours": ("час",),
    "rate": ("ставк",),
    "sales": ("продаж", "выручк"),
    "period": ("период",),
}


def _read_grid(filename: str, data: bytes):
    fn = filename.lower()
    if fn.endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        return [["" if v is None else v for v in row] for row in ws.iter_rows(values_only=True)]
    if fn.endswith((".csv", ".txt")):
        text = data.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=";,\t") if text.strip() else csv.excel
        return [row for row in csv.reader(io.StringIO(text), dialect)]
    raise ParseError("пришли .xlsx или .csv")


def parse_table(filename: str, data: bytes):
    grid = _read_grid(filename, data)
    period, header_idx, cols = None, None, {}
    for i, row in enumerate(grid[:15]):
        cells = [str(c).strip().lower() for c in row]
        found = {}
        for key, keys in _COLS.items():
            for j, c in enumerate(cells):
                if any(k in c for k in keys) and key not in found:
                    found[key] = j
        if {"name", "point", "hours", "rate", "sales"} <= found.keys():
            header_idx, cols = i, found
            break
        for c in row:
            period = period or find_period(str(c))
    if header_idx is None:
        raise ParseError("не нашёл заголовки. Нужны колонки: Имя, Точка, Часы, Ставка, Продажи")

    rows, errors = [], []
    for i, row in enumerate(grid[header_idx + 1:], header_idx + 2):
        get = lambda k: row[cols[k]] if cols[k] < len(row) else ""
        if not str(get("name")).strip():
            continue
        if "period" in cols and not period:
            period = find_period(str(get("period")))
        try:
            code = find_point(str(get("point")))
            if not code:
                raise ParseError(f"не знаю точку «{get('point')}»")
            rows.append(Row(str(get("name")).strip(), code,
                            to_num(get("hours")), to_num(get("rate")), to_num(get("sales"))))
        except (ParseError, ValueError) as e:
            errors.append(f"Строка {i} ({get('name')}): {e}")
    return period, rows, errors


def make_template() -> bytes:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Выписка"
    ws.append(["Период:", "1.08 – 14.08"])
    ws.append([])
    ws.append(["Имя", "Точка", "Часы", "Ставка", "Продажи"])
    for c in ws[3]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="EEEEEE")
    ws.append(["Стас", "Дизайн завод", 55, 340, 66300])
    ws.append(["Аня", "Севкабель", 48, 360, 52000])
    ws.append(["Миша", "Лесная", 60, 340, 71500])
    for col, w in zip("ABCDE", (22, 18, 10, 10, 14)):
        ws.column_dimensions[col].width = w
    ws["G3"] = "Точки:"
    ws["G3"].font = Font(bold=True)
    for k, (code, (name, city)) in enumerate(POINTS.items(), 4):
        ws[f"G{k}"] = f"{name} ({code}) — {'Москва' if city == 'msk' else 'Питер'}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
