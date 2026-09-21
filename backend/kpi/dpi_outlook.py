"""Назначение ДПИ: план из колонки месяца в Excel, факт — календарь «Совещания».

  py -m kpi.dpi_outlook --month 2026-08 --outlook
  py -m kpi.dpi_outlook --month 2026-08 --events august.json
"""

from __future__ import annotations

import argparse
import json
import sys
import calendar
from datetime import date, timedelta
from pathlib import Path

from kpi.sources.dpi_schedule import (
    load_workbook_sheet,
    match_outlook_events,
    planned_month,
)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def format_plan(rows: list[dict]) -> str:
    lines = [
        f"{'№':<3} {'Тема':<52} {'правило':<28} {'план':<12} {'факт':<12} {'стоит':<6}",
        "-" * 118,
    ]
    for row in rows:
        lines.append(
            f"{row.get('number', ''):<3} {str(row.get('name') or '')[:52]:<52} "
            f"{str(row.get('rule') or '')[:28]:<28} {str(row.get('plan_date') or ''):<12} "
            f"{str(row.get('fact_date') or '—'):<12} {'да' if row.get('appointed') else 'нет':<6}"
        )
    appointed = sum(1 for row in rows if row.get("appointed"))
    lines.append("-" * 118)
    lines.append(f"Назначено {appointed}/{len(rows)}")
    return "\n".join(lines)


def load_events(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("events") or payload.get("value") or []
        return [row for row in rows if isinstance(row, dict)]
    return []


def try_read_outlook(date_from: date, date_to: date) -> list[dict]:
    """Локальный Outlook через COM, если pywin32 и профиль доступны."""
    try:
        from desktop.app.tools.ac.workers.outlook_com_actions import read_calendar
    except Exception:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop"))
            from app.tools.ac.workers.outlook_com_actions import read_calendar
        except Exception as exc:
            raise RuntimeError(f"outlook COM недоступен: {exc}") from exc
    events: list[dict] = []
    seen: set[str] = set()
    cursor = date_from
    while cursor <= date_to:
        chunk_end = min(cursor + timedelta(days=6), date_to)
        result = read_calendar(
            {
                "date_from": cursor.isoformat(),
                "date_to": chunk_end.isoformat(),
                "folder": "Совещания",
                "max_results": 500,
                "max_scan_items": 2000,
            }
        )
        rows = result.get("events") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(result.get("error") if isinstance(result, dict) else "пустой календарь")
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = "|".join(
                [
                    str(row.get("entry_id") or ""),
                    str(row.get("start") or ""),
                    str(row.get("subject") or ""),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            events.append(row)
        cursor = chunk_end + timedelta(days=1)
    return events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="План назначения ДПИ и сверка с Outlook")
    parser.add_argument("--month", help="Период YYYY-MM")
    parser.add_argument("--from", dest="date_from")
    parser.add_argument("--to", dest="date_to")
    parser.add_argument(
        "--excel",
        type=Path,
        default=Path(r"c:\Users\a.komarkova\Downloads\ДПИ ЗАПОЛНЯТЬ 2024_2025_2026 1.xlsx"),
        help="Таблица ДПИ: план = дата в колонке месяца",
    )
    parser.add_argument("--events", type=Path, help="JSON событий Outlook")
    parser.add_argument("--outlook", action="store_true", help="Календарь Outlook «Совещания»")
    parser.add_argument("--save-events", type=Path, help="Сохранить сырые события Outlook в JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.month:
        year_s, month_s = args.month.split("-", 1)
        date_from, date_to = month_bounds(int(year_s), int(month_s))
    elif args.date_from and args.date_to:
        date_from, date_to = date.fromisoformat(args.date_from), date.fromisoformat(args.date_to)
    else:
        today = date.today()
        date_from, date_to = month_bounds(today.year, today.month)
    year, month = date_from.year, date_from.month

    events: list[dict] = []
    source = "только правила"
    if args.events:
        events = load_events(args.events)
        source = str(args.events)
    elif args.outlook:
        events = try_read_outlook(date_from, date_to)
        source = "outlook COM, папка Совещания"

    excel_rows = load_workbook_sheet(args.excel, year) if args.excel and args.excel.exists() else None
    if args.outlook and args.save_events and events:
        args.save_events.write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if events:
        rows = match_outlook_events(events, year, month, excel_rows=excel_rows)
        source = source
    elif excel_rows:
        rows = match_outlook_events([], year, month, excel_rows=excel_rows)
        source = f"excel {args.excel.name}, календарь не читали"
    else:
        rows = [{**row, "fact_date": "", "appointed": False} for row in planned_month(year, month)]

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Назначение ДПИ  {date_from} — {date_to}")
    print(f"План: колонка месяца в Excel. Факт: {source}")
    print()
    print(format_plan(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
