"""Назначение ДПИ помощника руководителя.

План — правило с листа «2026» файла «ДПИ ЗАПОЛНЯТЬ»: «5 числа», «1 пт месяца».
Если день выпадает на субботу или воскресенье, план сдвигается на ближайший рабочий день.
Факт — встреча с тем же названием в календаре Outlook «Совещания».
Оценка = сколько из плана уже стоит в календаре.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from kpi.sources.dpi_schedule import (
    DPI_SERIES_2026,
    DpiSeries,
    load_workbook_sheet,
    match_outlook_events,
    parse_rule,
)

WEIGHT = 10
FOLDER = "Совещания"
DEFAULT_XLSX = Path(r"C:\Users\a.komarkova\Downloads\ДПИ ЗАПОЛНЯТЬ 2024_2025_2026 1.xlsx")
_KNOWN = {item.number: item for item in DPI_SERIES_2026}

SOURCE = {
    "kind": "files",
    "loader": "files",
    "file": str(DEFAULT_XLSX),
    "folder": FOLDER,
}
FACT_SOURCE = {"kind": "outlook", "loader": "outlook", "folder": FOLDER}


def _as_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _bounds(ctx: Any, date_from: date | None, date_to: date | None) -> tuple[date | None, date | None]:
    start = date_from or getattr(ctx, "date_from", None)
    end = date_to or getattr(ctx, "date_to", None)
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()
    if start and end and end < start:
        start, end = end, start
    return start, end


def series_from_rules(rows: list[dict[str, Any]]) -> tuple[DpiSeries, ...]:
    """Правило из Excel важнее зашитого списка. Псевдонимы для календаря берём по номеру."""
    series: list[DpiSeries] = []
    for row in rows:
        if row.get("excluded"):
            continue
        parsed = parse_rule(str(row.get("rule") or ""))
        if parsed.get("kind") == "unknown":
            continue
        number = int(row.get("number") or 0)
        known = _KNOWN.get(number)
        series.append(
            DpiSeries(
                number=number,
                name=str(row.get("name") or (known.name if known else "")).strip(),
                participants=str(row.get("participants") or ""),
                owner=str(row.get("owner") or ""),
                rule_text=str(row.get("rule") or ""),
                kind=str(parsed["kind"]),
                day=int(parsed.get("day") or 0),
                weekday=int(parsed.get("weekday") or 0),
                nth=int(parsed.get("nth") or 0),
                aliases=known.aliases if known else (),
            )
        )
    return tuple(series)


def _excel_rows(ctx: Any, year: int) -> list[dict[str, Any]]:
    extra = dict(SOURCE)
    more = ctx.extra_for() if hasattr(ctx, "extra_for") else {}
    if isinstance(more, dict):
        extra.update(more)
    preset = extra.get("rows")
    if isinstance(preset, list) and preset:
        return _as_rows(preset)
    loaded: list[dict[str, Any]] = []
    load = getattr(ctx, "load_for", None)
    if callable(load):
        loaded = _as_rows(load({**extra, "loader": "files"}))
    if any(row.get("rule") for row in loaded):
        return loaded
    path = Path(str(extra.get("file") or DEFAULT_XLSX))
    if path.exists():
        return load_workbook_sheet(path, year)
    return []


def load_dpi_appointment_rows(
    ctx: Any,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    start, _end = _bounds(ctx, date_from, date_to)
    year = start.year if start else date.today().year
    rules = _excel_rows(ctx, year)
    events: list[dict[str, Any]] = []
    load = getattr(ctx, "load_for", None)
    if callable(load):
        events = _as_rows(load(dict(FACT_SOURCE)))
    return [{"role": "plan", **row} for row in rules] + [{"role": "fact", **row} for row in events]


def _split(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plans: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for row in rows:
        role = str(row.get("role") or "")
        if role == "fact" or row.get("subject") or row.get("start"):
            events.append(row)
            continue
        plans.append(row)
    return plans, events


def score_dpi_appointment_kpi(
    rows: list[dict[str, Any]] | None,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    plans, events = _split(_as_rows(rows))
    anchor = date_from or as_of
    year, month = anchor.year, anchor.month
    series = series_from_rules(plans)
    matched = match_outlook_events(events, year, month, series=series) if series else []
    total = len(matched)
    covered = sum(1 for row in matched if row.get("appointed"))
    if total:
        fact = round(100.0 * covered / total, 1)
        contrib = round(fact * WEIGHT / 100.0, 1)
    else:
        fact = None
        contrib = None
    return {
        "as_of": as_of.isoformat() if isinstance(as_of, date) else str(as_of or ""),
        "date_from": date_from.isoformat() if isinstance(date_from, date) else "",
        "date_to": date_to.isoformat() if isinstance(date_to, date) else "",
        "plan_total": total,
        "in_calendar": covered,
        "fact_pct": fact,
        "score_pct": fact,
        "weight": WEIGHT,
        "contrib_pct": contrib,
        "rows": matched,
    }


def compute_dpi_appointment_kpi(
    ctx: Any,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    start, end = _bounds(ctx, date_from, date_to)
    rows = load_dpi_appointment_rows(ctx, date_from=start, date_to=end)
    return score_dpi_appointment_kpi(rows, as_of=as_of, date_from=start, date_to=end)


def format_report(report: dict[str, Any]) -> str:
    total = report.get("plan_total") or 0
    if not total:
        return "Правил ДПИ за период нет."
    lines = [f"{'№':<4} {'план':<12} {'факт':<12} {'стоит':<6} название"]
    for row in report.get("rows") or []:
        lines.append(
            f"{str(row.get('number') or ''):<4} "
            f"{str(row.get('plan_date') or ''):<12} "
            f"{str(row.get('fact_date') or '—'):<12} "
            f"{'да' if row.get('appointed') else 'нет':<6} "
            f"{row.get('name') or ''}"
        )
    lines.append(
        f"В календаре {report.get('in_calendar')}/{total}, факт {report.get('fact_pct')}%."
    )
    return "\n".join(lines)
