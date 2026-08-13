from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


class LocalMcpError(RuntimeError):
    pass


_TOOLS_WEBSEARCH = Path(__file__).resolve().parents[3] / "tools" / "web_search_tool"


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "web_search",
            "description": "Ищет информацию в интернете и возвращает краткие результаты.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5},
                    "fetch_top": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        }
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != "web_search":
        raise LocalMcpError(f"Неизвестный инструмент: {name}")
    return _web_search(arguments)


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
            results, extracted = search_and_extract(query, max_results=max_results)
        else:
            results = search(query, max_results=max_results)
            extracted = ""
    except Exception as exc:  # noqa: BLE001
        raise LocalMcpError(f"Ошибка web_search: {exc}") from exc
    return {
        "query": query,
        "results": [
            {"title": item.title, "url": item.url, "snippet": item.snippet}
            for item in results
        ],
        "extracted_text": extracted or "",
    }
