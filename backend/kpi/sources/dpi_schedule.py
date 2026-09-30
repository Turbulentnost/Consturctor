from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

MONTHS_RU = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)
WEEKDAYS_RU = {"пн": 1, "вт": 2, "ср": 3, "чт": 4, "пт": 5, "сб": 6, "вс": 7}


@dataclass(frozen=True)
class DpiSeries:
    number: int
    name: str
    participants: str
    owner: str
    rule_text: str
    kind: str
    day: int = 0
    weekday: int = 0
    nth: int = 0
    aliases: tuple[str, ...] = ()

    def search_needles(self) -> tuple[str, ...]:
        needles = (self.name, *self.aliases)
        return tuple(item for item in needles if item)


# Правила листа «2026г. (2)» колонка «Дата проведения/план».
DPI_SERIES_2026: tuple[DpiSeries, ...] = (
    DpiSeries(1, "ДПИ СУП", "Директор по персоналу, сотрудники службы персонала, специалист по охране труда", "Донцова", "5 числа каждого месяца", "dom", day=5, aliases=("ДПИ СУПТЛ",)),
    DpiSeries(2, "ДПИ службы логистики", "начальник ОМТО, директор по персоналу, сотрудники ОМТО и склада", "Мегрелишвили", "7 числа каждого месяца", "dom", day=7, aliases=("ДПИ ОМТО", "ДПИ склад")),
    DpiSeries(3, "ДПИ СР", "Директор по персоналу, главный конструктор, начальник службы развития", "Соломичева", "1 пт месяца", "nth_weekday", weekday=5, nth=1),
    DpiSeries(4, "ДПИ сектора внедрения ИИ (1 пт)", "сотрудники сектора внедрения ИИ", "Соломичева", "1 пт месяца", "nth_weekday", weekday=5, nth=1, aliases=("ДПИ сектора внедрения ИИ",)),
    DpiSeries(5, "ДПИ в службе качества", "Директор по персоналу, исполнительный директор, сотрудники службы качества", "Арсуноев", "12 числа каждого месяца", "dom", day=12, aliases=("ДПИ службы качества",)),
    DpiSeries(6, "ДПИ производство №1, №2", "сотрудники производств №1 и №2", "Целищев", "13 числа каждого месяца", "dom", day=13, aliases=("ДПИ производство",)),
    DpiSeries(7, "День подведения итогов отделов продаж", "операционный директор, директор по персоналу, отделы продаж", "", "во 2 вторник месяца", "nth_weekday", weekday=2, nth=2, aliases=("ДПИ отделов продаж", "ДПИ отдел продаж")),
    DpiSeries(8, "ДПИ отдела сопровождения 1С, службы ИТ", "начальник службы сопровождения 1С, директор по персоналу", "", "8 числа каждого месяца", "dom", day=8, aliases=("ДПИ 1С", "ДПИ ИТ")),
    DpiSeries(9, "ДПИ метрологическая служба", "", "", "10 числа каждого месяца", "dom", day=10, aliases=("ДПИ метрология",)),
    DpiSeries(10, "День подведения итогов КБ Гончаров", "главный конструктор, КБ", "", "13 числа каждого месяца", "dom", day=13, aliases=("ДПИ КБ Гончаров", "ДПИ КБ", "День подведения итогов КБ")),
    DpiSeries(11, "ДПИ СС, ОТП, ОРР", "начальник сервисной службы, директор по персоналу", "Орлов", "15 числа каждого месяца", "dom", day=15),
    DpiSeries(12, "ДПИ производство ЭЦ и БМИ", "", "", "13 числа каждого месяца", "dom", day=13, aliases=("ДПИ производство ЭЦ", "ДПИ производство")),
    DpiSeries(13, "День подведения итогов по проектной деятельности по ГК Ануфриева", "заместитель главного конструктора по проектной деятельности", "", "14 числа каждого месяца", "dom", day=14, aliases=("ДПИ Ануфриев", "ГК Ануфриева", "День подведения итогов по проектной деятельности")),
    DpiSeries(14, "День качества", "директор по качеству", "", "14 числа каждого месяца", "dom", day=14),
    DpiSeries(15, "ДПИ ГСПП", "главный конструктор, КБ", "", "15 числа каждого месяца", "dom", day=15),
    DpiSeries(16, "ДПИ юридический отдел", "", "", "5 числа каждого месяца", "dom", day=5),
    DpiSeries(17, "ДПИ сектора внедрения ИИ (15 числа)", "директор по развитию, отдел ИИ", "", "15 числа каждого месяца", "dom", day=15, aliases=("ДПИ сектора внедрения ИИ",)),
)


def next_workday(value: date) -> date:
    if value.isoweekday() == 6:
        return value + timedelta(days=2)
    if value.isoweekday() == 7:
        return value + timedelta(days=1)
    return value


def nth_weekday_of_month(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.isoweekday()) % 7
    return first + timedelta(days=shift + 7 * (nth - 1))


def planned_date(series: DpiSeries, year: int, month: int, *, shift_weekend: bool = True) -> date:
    if series.kind == "nth_weekday":
        value = nth_weekday_of_month(year, month, series.weekday, series.nth)
    else:
        last = calendar.monthrange(year, month)[1]
        value = date(year, month, min(series.day, last))
    return next_workday(value) if shift_weekend else value


def planned_month(year: int, month: int, *, series: tuple[DpiSeries, ...] = DPI_SERIES_2026) -> list[dict[str, Any]]:
    rows = []
    for item in series:
        due = planned_date(item, year, month)
        rows.append(
            {
                "number": item.number,
                "name": item.name,
                "rule": item.rule_text,
                "owner": item.owner,
                "plan_date": due.isoformat(),
                "participants": item.participants,
            }
        )
    return rows


def parse_rule(text: str) -> dict[str, Any]:
    raw = " ".join(str(text or "").lower().replace("ё", "е").split())
    nth_match = re.search(r"(?:во\s+)?(\d+)\s+(пн|вт|ср|чт|пт|сб|вс)", raw)
    if nth_match:
        return {
            "kind": "nth_weekday",
            "nth": int(nth_match.group(1)),
            "weekday": WEEKDAYS_RU[nth_match.group(2)],
        }
    first_wd = re.search(r"1\s+(пн|вт|ср|чт|пт|сб|вс)", raw)
    if first_wd:
        return {"kind": "nth_weekday", "nth": 1, "weekday": WEEKDAYS_RU[first_wd.group(1)]}
    day_match = re.search(r"(\d{1,2})\s+числа", raw)
    if day_match:
        return {"kind": "dom", "day": int(day_match.group(1))}
    return {"kind": "unknown"}


def _cell_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _marked_red(cell: Any) -> bool:
    """Красная заливка или красный шрифт: строку не берём в план."""
    fill = getattr(cell, "fill", None)
    fill_rgb = getattr(getattr(fill, "fgColor", None), "rgb", None)
    if isinstance(fill_rgb, str) and fill_rgb.upper().endswith("FF0000"):
        return True
    font_rgb = getattr(getattr(getattr(cell, "font", None), "color", None), "rgb", None)
    return isinstance(font_rgb, str) and font_rgb.upper().endswith("FF0000")


def load_workbook_sheet(path: Path, year: int = 2026) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, data_only=False)
    sheet = None
    for name in workbook.sheetnames:
        if str(year) in name:
            sheet = workbook[name]
            break
    if sheet is None:
        sheet = workbook[workbook.sheetnames[0]]
    header = [str(sheet.cell(3, col).value or "").strip().casefold() for col in range(1, 18)]
    month_cols = {MONTHS_RU.index(title) + 1: col + 1 for col, title in enumerate(header) if title in MONTHS_RU}
    rows: list[dict[str, Any]] = []
    for index in range(4, (sheet.max_row or 4) + 1):
        number = sheet.cell(index, 1).value
        name = str(sheet.cell(index, 2).value or "").strip()
        if not name or not isinstance(number, (int, float)):
            continue
        rule_text = str(sheet.cell(index, 5).value or "").strip()
        parsed = parse_rule(rule_text)
        facts = {}
        for month, col in month_cols.items():
            parsed_date = _cell_date(sheet.cell(index, col).value)
            if parsed_date:
                facts[month] = parsed_date.isoformat()
        owner = str(sheet.cell(index, 18).value or sheet.cell(index, 17).value or "").strip()
        excluded = any(_marked_red(sheet.cell(index, col)) for col in range(1, 7))
        rows.append(
            {
                "number": int(number),
                "name": name,
                "participants": str(sheet.cell(index, 3).value or "").strip(),
                "owner": owner,
                "rule": rule_text,
                "excluded": excluded,
                **parsed,
                "excel_fact": facts,
            }
        )
    return rows


def normalize_event_title(title: str) -> str:
    return " ".join(str(title or "").casefold().replace("ё", "е").split())


def _canon_title(title: str) -> str:
    text = normalize_event_title(title)
    text = text.replace("день подведения итогов", "дпи")
    text = text.replace("дня подведения итогов", "дпи")
    return re.sub(r"\([^)]*\)", "", text).strip()


def _stems(text: str) -> set[str]:
    skip = {"по", "и", "в", "с", "для"}
    stems: set[str] = set()
    for tok in re.findall(r"[а-яa-z0-9№]+", text):
        if tok in skip:
            continue
        stems.add(tok[:5] if len(tok) >= 5 else tok)
    return stems


def title_matches_dpi(plan_name: str, event_title: str) -> bool:
    plan = _canon_title(plan_name)
    hay = _canon_title(event_title)
    if not plan or not hay:
        return False
    if plan == "день качества" or plan_name.strip().casefold() == "день качества":
        return "день качества" in normalize_event_title(event_title)
    if plan in hay:
        return True
    if hay in plan and (hay.startswith("дпи") or len(hay) >= 12):
        return True
    plan_stems = _stems(plan)
    hay_stems = _stems(hay)
    if "дпи" not in plan_stems and "качес" not in plan_stems:
        return False
    return bool(plan_stems) and plan_stems <= hay_stems


def event_matches_series(series: DpiSeries, title: str) -> bool:
    if title_matches_dpi(series.name, title):
        return True
    return any(title_matches_dpi(alias, title) for alias in series.aliases)


def _event_when(event: dict[str, Any]) -> date | None:
    raw = str(event.get("start") or event.get("date") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).date()
    except ValueError:
        return None


def match_outlook_events(
    events: list[dict[str, Any]],
    year: int,
    month: int,
    *,
    series: tuple[DpiSeries, ...] = DPI_SERIES_2026,
    excel_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """План — дата месяца из Excel, факт — встреча в календаре «Совещания»."""
    start, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    window = []
    for event in events:
        when = _event_when(event)
        if when is None or not (start <= when <= last):
            continue
        window.append((when, event))

    plans: list[dict[str, Any]] = []
    if excel_rows:
        for row in excel_rows:
            plan_raw = (row.get("excel_fact") or {}).get(month)
            plans.append(
                {
                    "number": row.get("number"),
                    "name": row.get("name"),
                    "rule": row.get("rule"),
                    "owner": row.get("owner") or "",
                    "plan_date": plan_raw or "",
                }
            )
    else:
        for item in series:
            plans.append(
                {
                    "number": item.number,
                    "name": item.name,
                    "rule": item.rule_text,
                    "owner": item.owner,
                    "plan_date": planned_date(item, year, month).isoformat(),
                }
            )

    used: set[int] = set()
    rows = []
    for plan in plans:
        due = None
        if plan["plan_date"]:
            due = date.fromisoformat(str(plan["plan_date"]))
        best: tuple[int, int, int, date, dict[str, Any]] | None = None
        for idx, (when, event) in enumerate(window):
            if idx in used:
                continue
            title = str(event.get("subject") or event.get("title") or "")
            names = [str(plan["name"])]
            for item in series:
                if item.number == plan.get("number"):
                    names.extend(item.search_needles())
            if not any(title_matches_dpi(name, title) for name in names):
                continue
            delta = abs((when - due).days) if due else 30
            score = 100 if due and when == due else max(0, 40 - delta)
            candidate = (score, -delta, idx, when, event)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        hit = None
        if best is not None:
            used.add(best[2])
            hit = (best[3], best[4])
        rows.append(
            {
                **plan,
                "fact_date": hit[0].isoformat() if hit else "",
                "fact_title": str((hit[1].get("subject") or hit[1].get("title") or "") if hit else ""),
                "appointed": bool(hit),
            }
        )
    return rows
