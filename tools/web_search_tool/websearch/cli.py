"""CLI инструмента веб-поиска.

Примеры:
    python -m websearch search "закупки росэлторг" -n 5
    python -m websearch search "новости ростов" --extract
    python -m websearch fetch https://ru.wikipedia.org/wiki/Python
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from .engine import (
    DEFAULT_TIMEOUT_S,
    fetch_page,
    format_results,
    search,
    search_and_extract,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="websearch",
        description="Веб-поиск (DuckDuckGo → Wikipedia) и извлечение текста страниц.",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="таймаут, сек")
    parser.add_argument("--json", action="store_true", help="вывод в формате JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="поиск в интернете")
    p_search.add_argument("query", help="поисковый запрос")
    p_search.add_argument("-n", "--max-results", type=int, default=5, help="сколько результатов")
    p_search.add_argument(
        "--extract",
        action="store_true",
        help="дополнительно загрузить текст первой доступной страницы",
    )

    p_fetch = sub.add_parser("fetch", help="загрузить страницу и извлечь текст")
    p_fetch.add_argument("url", help="адрес страницы")

    return parser


def _cmd_search(args: argparse.Namespace) -> int:
    if args.extract:
        data = search_and_extract(
            args.query, max_results=args.max_results, timeout=args.timeout
        )
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(data["summary"])
            print()
            print(data["text"])
        return 0

    results, engine = search(args.query, max_results=args.max_results, timeout=args.timeout)
    if args.json:
        print(json.dumps(
            {"query": args.query, "engine": engine, "results": [r.to_dict() for r in results]},
            ensure_ascii=False,
            indent=2,
        ))
    else:
        print(format_results(args.query, results, engine))
    return 0 if results else 1


def _cmd_fetch(args: argparse.Namespace) -> int:
    page = fetch_page(args.url, timeout=args.timeout)
    if args.json:
        print(json.dumps(page.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"URL:   {page.url}")
        print(f"Title: {page.title}")
        print(f"Source: {page.source}")
        print()
        print(page.text)
    return 1 if page.blocked else 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "search":
            return _cmd_search(args)
        if args.command == "fetch":
            return _cmd_fetch(args)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
