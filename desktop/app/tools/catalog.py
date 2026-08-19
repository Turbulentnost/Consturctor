"""Каталог desktop-инструментов для MCP и подсказок агенту."""

from __future__ import annotations

from typing import Any

_LEGACY = (
    (
        "web_search",
        "Быстрый веб-поиск (DuckDuckGo/Wikipedia) без браузера.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
                "fetch_top": {"type": "boolean"},
            },
            "required": ["query"],
        },
    ),
    (
        "site_browser",
        "Парсер сайта через Playwright Chromium.",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["open", "extract", "search"]},
                "url": {"type": "string"},
                "query": {"type": "string"},
                "max_items": {"type": "integer"},
            },
            "required": ["url"],
        },
    ),
    (
        "plan_export",
        "Поиск на ЭТП по ключам и Excel на рабочий стол.",
        {
            "type": "object",
            "properties": {
                "site_url": {"type": "string"},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "columns": {"type": "array", "items": {"type": "string"}},
                "workflow_title": {"type": "string"},
            },
            "required": ["keywords"],
        },
    ),
)


def list_desktop_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, description, schema in _LEGACY:
        seen.add(name)
        tools.append(
            {
                "name": name,
                "description": description,
                "inputSchema": schema,
            }
        )
    from app.tools.ac.dispatch import get_registry

    for definition in get_registry().list_tools():
        name = str(definition.name)
        if name in seen:
            continue
        seen.add(name)
        schema = definition.input_schema if isinstance(definition.input_schema, dict) else {
            "type": "object",
            "properties": {},
        }
        item = {
            "name": name,
            "description": str(definition.description or definition.title or name),
            "inputSchema": schema,
            "execution": "desktop",
        }
        if definition.runtime:
            item["runtime"] = definition.runtime
        tools.append(item)
    return tools
