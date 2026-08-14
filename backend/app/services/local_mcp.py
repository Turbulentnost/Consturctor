"""Каталог схем инструментов для агента.

Исполнение desktop-tools — на клиенте (SSE tool_request).
IMAP — только на сервере (см. agent_runtime._invoke_imap_server).
"""

from __future__ import annotations

from typing import Any


class LocalMcpError(RuntimeError):
    pass


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "web_search",
            "description": (
                "Быстрый веб-поиск (DuckDuckGo/Wikipedia) без браузера. "
                "Исполняется на desktop пользователя."
            ),
            "execution": "desktop",
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
                "Исполняется на desktop пользователя."
            ),
            "execution": "desktop",
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
        {
            "name": "plan_export",
            "description": (
                "Поиск на ЭТП по ключам из плана агента и сохранение Excel на Desktop. "
                "Исполняется на desktop пользователя."
            ),
            "execution": "desktop",
            "input_schema": {
                "type": "object",
                "properties": {
                    "site_url": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "columns": {"type": "array", "items": {"type": "string"}},
                    "destination": {"type": "string", "default": "desktop"},
                    "export_format": {"type": "string", "default": "xlsx"},
                    "workflow_title": {"type": "string"},
                },
                "required": ["keywords"],
            },
        },
        {
            "name": "imap.list_unread",
            "description": "Список непрочитанных писем (сервер, IMAP).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                    "user": {"type": "string"},
                    "query": {"type": "string"},
                },
            },
        },
        {
            "name": "imap.search",
            "description": "Поиск писем по критериям (сервер, IMAP).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "user": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        },
        {
            "name": "imap.fetch_message",
            "description": "Загрузить письмо по uid (сервер, IMAP).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "uid": {"type": "integer"},
                    "message_id": {"type": "integer"},
                    "user": {"type": "string"},
                },
            },
        },
        {
            "name": "imap.fetch_attachments",
            "description": "Список вложений письма по uid (сервер, IMAP).",
            "execution": "server",
            "input_schema": {
                "type": "object",
                "properties": {
                    "uid": {"type": "integer"},
                    "message_id": {"type": "integer"},
                    "user": {"type": "string"},
                },
            },
        },
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = arguments
    raise LocalMcpError(
        f"Инструмент «{name}» больше не исполняется на backend. "
        "Desktop-tools идут через SSE tool_request; IMAP — через серверный сервис."
    )
