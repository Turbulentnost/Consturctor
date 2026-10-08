from __future__ import annotations

import argparse
import json
import sys

from .browser import SiteBrowserError, browse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sitebrowser",
        description="Универсальный парсер любого сайта через Playwright Chromium",
    )
    p.add_argument("--json", action="store_true", help="JSON-вывод")
    p.add_argument("--show-browser", action="store_true", help="Видимое окно Chromium")
    sub = p.add_subparsers(dest="cmd", required=True)

    open_p = sub.add_parser("open", help="Открыть URL и извлечь текст/ссылки/карточки")
    open_p.add_argument("url")
    open_p.add_argument("--wait-ms", type=int, default=0)
    open_p.add_argument("--wait-selector", default="")
    open_p.add_argument("--item-selector", default="")
    open_p.add_argument("--max-items", type=int, default=30)

    extract_p = sub.add_parser("extract", help="Извлечь карточки со страницы")
    extract_p.add_argument("url")
    extract_p.add_argument("--item-selector", default="")
    extract_p.add_argument("--title-selector", default="")
    extract_p.add_argument("--link-selector", default="")
    extract_p.add_argument("--max-items", type=int, default=30)
    extract_p.add_argument("--wait-ms", type=int, default=500)

    search_p = sub.add_parser("search", help="Поиск на странице сайта")
    search_p.add_argument("url")
    search_p.add_argument("query")
    search_p.add_argument("--input-selector", default="")
    search_p.add_argument("--submit-selector", default="")
    search_p.add_argument("--item-selector", default="")
    search_p.add_argument("--max-items", type=int, default=30)
    search_p.add_argument("--wait-ms", type=int, default=800)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    headless = not bool(args.show_browser)
    try:
        if args.cmd == "open":
            data = browse(
                action="open",
                url=args.url,
                headless=headless,
                wait_ms=args.wait_ms,
                wait_selector=args.wait_selector or None,
                item_selector=args.item_selector or None,
                max_items=args.max_items,
            )
        elif args.cmd == "extract":
            data = browse(
                action="extract",
                url=args.url,
                headless=headless,
                wait_ms=args.wait_ms,
                item_selector=args.item_selector or None,
                title_selector=args.title_selector or None,
                link_selector=args.link_selector or None,
                max_items=args.max_items,
            )
        else:
            data = browse(
                action="search",
                url=args.url,
                query=args.query,
                headless=headless,
                wait_ms=args.wait_ms,
                input_selector=args.input_selector or None,
                submit_selector=args.submit_selector or None,
                item_selector=args.item_selector or None,
                max_items=args.max_items,
            )
    except SiteBrowserError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"URL: {data.get('url')}")
    print(f"Title: {data.get('title')}")
    print(f"Cards: {data.get('cards_count')} | Links: {len(data.get('links') or [])}")
    print()
    for i, card in enumerate(data.get("cards") or [], 1):
        print(f"{i}. {card.get('title')}")
        if card.get("url"):
            print(f"   {card.get('url')}")
        text = (card.get("text") or "")[:220]
        if text:
            print(f"   {text}")
    if not data.get("cards"):
        print("--- text ---")
        print((data.get("text") or "")[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
