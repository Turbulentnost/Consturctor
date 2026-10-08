"""Командный интерфейс: поиск тендеров и выгрузка Excel-отчёта."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from . import config
from .excel_export import export
from .search_rules import build_queries


def _default_output() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"roseltorg_tenders_{stamp}.xlsx"


def _print_queries(queries: list[str]) -> None:
    print(f"Ключевых запросов: {len(queries)}")
    for q in queries:
        print(f"  • {q}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="roseltorg_tender_search",
        description="Поиск тендеров на Росэлторг (223-ФЗ) по ключевым словам и выгрузка в Excel.",
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Запустить поиск и выгрузить отчёт")
    run.add_argument("-o", "--output", default=None, help="Путь к .xlsx (по умолчанию с датой)")
    run.add_argument("--acceptance", action="store_true",
                     help="Приёмочная подвыборка (5 разнотипных запросов)")
    run.add_argument("--show-browser", action="store_true", help="Показать окно браузера")
    run.add_argument("--dry-run", action="store_true",
                     help="Только показать список запросов, без обращения к сайту")

    sub.add_parser("keywords", help="Показать итоговый список поисковых запросов")

    args = parser.parse_args(argv)

    if args.command == "keywords":
        _print_queries(build_queries())
        return 0

    if args.command != "run":
        parser.print_help()
        return 1

    queries = config.ACCEPTANCE_QUERIES if args.acceptance else build_queries()

    if args.dry_run:
        _print_queries(queries)
        return 0

    from . import roseltorg_client  # ленивый импорт (требует playwright)

    def _progress(i: int, total: int, query: str, found: int) -> None:
        print(f"[{i}/{total}] {query} — найдено новых: {found}", flush=True)

    print("Запуск поиска на Росэлторг…", flush=True)
    try:
        tenders = roseltorg_client.search(
            queries, headless=not args.show_browser, on_progress=_progress
        )
    except RuntimeError as exc:
        print(f"\nОшибка: {exc}", file=sys.stderr)
        return 2

    output = args.output or _default_output()
    path = export(tenders, output)
    print(f"\nГотово. Найдено закупок (без дублей): {len(tenders)}")
    print(f"Отчёт сохранён: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
