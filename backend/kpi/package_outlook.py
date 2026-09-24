"""Своевременность пакета СД+РК по протоколу.

  py -m kpi.package_outlook --month 2026-08 --events august.json --protocols protocols.json
  py -m kpi.package_outlook --month 2026-08 --outlook --odata
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from kpi.dpi_outlook import load_events, read_outlook_subjects
from kpi.protocol_outlook import fetch_odata_protocols, month_bounds
from kpi.sources.sd_rk_packages import format_report, score_package_kpi


def load_protocols(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("protocols") or payload.get("value") or []
        return [row for row in rows if isinstance(row, dict)]
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Своевременность пакета СД+РК: предыдущий закрытый протокол к следующему Outlook"
    )
    parser.add_argument("--month", help="Период YYYY-MM")
    parser.add_argument("--from", dest="date_from")
    parser.add_argument("--to", dest="date_to")
    parser.add_argument("--as-of", dest="as_of", help="Дата расчёта YYYY-MM-DD")
    parser.add_argument("--events", type=Path, help="JSON встреч Outlook")
    parser.add_argument("--outlook", action="store_true", help="Календарь Outlook «Совещания»")
    parser.add_argument("--protocols", type=Path, help="JSON протоколов OData")
    parser.add_argument("--odata", action="store_true", help="Протоколы Document_ТД_Протокол")
    parser.add_argument("--out", type=Path, help="UTF-8 отчёт в файл")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Печатать JSON отчёта")
    parser.add_argument("--save-events", type=Path, help="Сохранить сырые встречи Outlook в JSON")
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
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    if args.protocols:
        protocols = load_protocols(args.protocols)
        protocol_source = str(args.protocols)
    elif args.odata:
        protocols = fetch_odata_protocols(date_from - timedelta(days=31), date_to)
        protocol_source = "OData Document_ТД_Протокол"
    else:
        protocols = []
        protocol_source = "протоколы не читали"

    if args.events:
        events = load_events(args.events)
        event_source = str(args.events)
    elif args.outlook:
        events = read_outlook_subjects(date_from, date_to)
        event_source = "outlook COM, папка Совещания"
    else:
        events = []
        event_source = "календарь не читали, план по протоколам"
    if args.save_events and events:
        args.save_events.write_text(
            json.dumps(events, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    report = score_package_kpi(
        events,
        protocols,
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
    )
    header = (
        f"Своевременность пакета СД+РК  {date_from} — {date_to}  на {as_of}\n"
        f"План: {event_source}. Факт: {protocol_source} (предыдущий Закрыт/НаИсполнении.Date ≤ T−2)\n"
    )
    body = json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else format_report(report)
    text = f"{header}\n{body}\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
