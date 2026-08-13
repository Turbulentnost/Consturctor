from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


class LocalMcpError(RuntimeError):
    pass


_TOOLS_ROOT = Path(__file__).resolve().parents[3] / "tools"
_TOOLS_WEBSEARCH = _TOOLS_ROOT / "web_search_tool"
_TOOLS_SITE_BROWSER = _TOOLS_ROOT / "site_browser_tool"


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "web_search",
            "description": (
                "Быстрый веб-поиск (DuckDuckGo/Wikipedia) без браузера. "
                "Не подходит для JS-площадок вроде roseltorg."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5},
                    "fetch_top": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        },
        {
            "name": "site_browser",
            "description": (
                "Универсальный парсер любого сайта через Playwright Chromium. "
                "Открывает URL, умеет поиск на странице и извлечение карточек/списков "
                "(в том числе JS-rendered)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "extract", "search"],
                        "default": "open",
                    },
                    "url": {"type": "string"},
                    "query": {"type": "string"},
                    "wait_ms": {"type": "integer", "default": 0},
                    "wait_selector": {"type": "string"},
                    "input_selector": {"type": "string"},
                    "submit_selector": {"type": "string"},
                    "item_selector": {"type": "string"},
                    "title_selector": {"type": "string"},
                    "link_selector": {"type": "string"},
                    "max_items": {"type": "integer", "default": 30},
                    "headless": {"type": "boolean", "default": True},
                },
                "required": ["url"],
            },
        },
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "web_search":
        return _web_search(arguments)
    if name == "site_browser":
        return _site_browser(arguments)
    raise LocalMcpError(f"Неизвестный инструмент: {name}")


def _web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise LocalMcpError("Пустой query")
    path = str(_TOOLS_WEBSEARCH)
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        from websearch.engine import search, search_and_extract  # type: ignore
    except ImportError as exc:
        raise LocalMcpError(f"web_search_tool не найден: {exc}") from exc
    max_results = int(arguments.get("max_results") or 5)
    fetch_top = bool(arguments.get("fetch_top"))
    try:
        if fetch_top:
            payload = search_and_extract(query, max_results=max_results)
            raw_results = list(payload.get("results") or [])
            extracted = str(payload.get("text") or payload.get("extracted_text") or "")
            engine = str(payload.get("engine") or "")
        else:
            raw_results, engine = search(query, max_results=max_results)
            extracted = ""
    except Exception as exc:  # noqa: BLE001
        raise LocalMcpError(f"Ошибка web_search: {exc}") from exc

    results: list[dict[str, str]] = []
    for item in raw_results:
        if hasattr(item, "title"):
            results.append(
                {
                    "title": str(item.title or ""),
                    "url": str(item.url or ""),
                    "snippet": str(getattr(item, "snippet", "") or ""),
                }
            )
        elif isinstance(item, dict):
            results.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("snippet") or ""),
                }
            )
    return {
        "query": query,
        "engine": engine,
        "results": results,
        "extracted_text": extracted or "",
    }


def _site_browser(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url") or "").strip()
    if not url:
        raise LocalMcpError("Пустой url")
    path = str(_TOOLS_SITE_BROWSER)
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        from sitebrowser.browser import SiteBrowserError, browse  # type: ignore
    except ImportError as exc:
        raise LocalMcpError(
            f"site_browser_tool не найден: {exc}. "
            "Установите: pip install -r tools/site_browser_tool/requirements.txt "
            "&& python -m playwright install chromium"
        ) from exc

    action = str(arguments.get("action") or "open").strip().lower() or "open"
    try:
        # Always headless: end-user must never see a browser/terminal window.
        return browse(
            action=action,
            url=url,
            query=str(arguments.get("query") or ""),
            headless=True,
            wait_ms=int(arguments.get("wait_ms") or 0),
            wait_selector=str(arguments.get("wait_selector") or "") or None,
            input_selector=str(arguments.get("input_selector") or "") or None,
            submit_selector=str(arguments.get("submit_selector") or "") or None,
            item_selector=str(arguments.get("item_selector") or "") or None,
            title_selector=str(arguments.get("title_selector") or "") or None,
            link_selector=str(arguments.get("link_selector") or "") or None,
            max_items=int(arguments.get("max_items") or 30),
        )
    except SiteBrowserError as exc:
        raise LocalMcpError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise LocalMcpError(f"Ошибка site_browser: {exc}") from exc
