"""Local tool host: executes agent tools on the user's machine."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from app.config import DESKTOP_ROOT, REPO_ROOT


class ToolHostError(RuntimeError):
    pass


def _tools_root() -> Path:
    candidates = [
        REPO_ROOT / "tools",
        DESKTOP_ROOT / "tools",
        DESKTOP_ROOT.parent / "tools",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return REPO_ROOT / "tools"


def _ensure_path(subdir: str) -> Path:
    root = _tools_root() / subdir
    path = str(root)
    if path not in sys.path:
        sys.path.insert(0, path)
    return root


def invoke_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    _SERVER_ONEC = {
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.odata_post",
        "onec.odata_patch",
        "onec.attach_file",
        "onec.sql_query",
        "onec.erp_tasks_current",
        "onec.erp_tasks_period",
        "onec.erp_subordinate_tasks",
        "onec.docflow_tasks",
    }
    _SERVER_CONSTRUCTOR = {
        "users.current",
        "users.subordinates",
        "data.process",
    }
    if name.startswith("imap."):
        raise ToolHostError(
            f"Инструмент {name} выполняется на сервере (IMAP), не на desktop."
        )
    if name in _SERVER_ONEC:
        raise ToolHostError(
            f"Инструмент {name} выполняется на сервере (1С OData/SQL), не на desktop."
        )
    if name in _SERVER_CONSTRUCTOR:
        raise ToolHostError(
            f"Инструмент {name} выполняется на сервере Constructor, не на desktop."
        )
    handler = _HANDLERS.get(name)
    if handler is not None:
        return handler(args)
    from app.tools.ac.dispatch import AcToolError, invoke_ac_tool

    try:
        return invoke_ac_tool(name, args)
    except AcToolError as exc:
        raise ToolHostError(str(exc)) from exc


def _web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolHostError("Пустой query")
    _ensure_path("web_search_tool")
    try:
        from websearch.engine import search, search_and_extract  # type: ignore
    except ImportError as exc:
        raise ToolHostError(f"web_search_tool не найден: {exc}") from exc

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
        raise ToolHostError(f"Ошибка web_search: {exc}") from exc

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
        raise ToolHostError("Пустой url")
    _ensure_path("site_browser_tool")
    try:
        from sitebrowser.browser import SiteBrowserError, browse  # type: ignore
    except ImportError as exc:
        raise ToolHostError(
            f"site_browser_tool не найден: {exc}. "
            "Установите: pip install -r tools/site_browser_tool/requirements.txt "
            "&& python -m playwright install chromium"
        ) from exc

    action = str(arguments.get("action") or "open").strip().lower() or "open"
    try:
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
        raise ToolHostError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ToolHostError(f"Ошибка site_browser: {exc}") from exc
_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "web_search": _web_search,
    "site_browser": _site_browser,
}
