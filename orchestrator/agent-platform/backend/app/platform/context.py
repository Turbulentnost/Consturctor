"""Контекст модели из хранилища Cursor SDK.

Чекпоинты — это сообщения, которые агент реально держит в ходе:
системный промпт, реплики пользователя, вызовы и полные ответы инструментов.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any


def read_agent_context(path: Path, agent_id: str) -> tuple[str, int]:
    """Текст контекста и число сообщений. Пусто, если хранилища или агента нет."""
    if not agent_id or not path.is_file():
        return "", 0
    parts: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            rendered = _render_row(line, agent_id)
            if rendered:
                parts.append(rendered)
    return "\n\n".join(parts), len(parts)


def _render_row(line: str, agent_id: str) -> str:
    raw_line = line.strip()
    if not raw_line:
        return ""
    try:
        row = json.loads(raw_line)
    except ValueError:
        return ""
    if not isinstance(row, dict) or row.get("agentId") != agent_id:
        return ""
    encoded = row.get("dataBase64")
    if not isinstance(encoded, str) or not encoded:
        return ""
    try:
        blob = base64.b64decode(encoded)
    except ValueError:
        return ""
    if not blob.startswith((b"{", b"[")):
        return ""
    try:
        message = json.loads(blob)
    except ValueError:
        return ""
    if not isinstance(message, dict):
        return ""
    return _render_message(message)


def _render_message(message: dict[str, Any]) -> str:
    role = message.get("role")
    content = message.get("content")
    if role == "system" and isinstance(content, str) and content.strip():
        return f"## Система\n{content.strip()}"
    if role == "user" and isinstance(content, str) and content.strip():
        return f"## Пользователь\n{content.strip()}"
    if role == "assistant" and isinstance(content, list):
        blocks = [block for part in content if (block := _assistant_part(part))]
        return "## Ассистент\n" + "\n\n".join(blocks) if blocks else ""
    if role == "tool" and isinstance(content, list):
        blocks = [block for part in content if (block := _tool_part(part))]
        return "\n\n".join(blocks)
    return ""


def _assistant_part(part: Any) -> str:
    if not isinstance(part, dict):
        return ""
    kind = part.get("type")
    if kind in {"text", "reasoning"}:
        text = part.get("text")
        return text.strip() if isinstance(text, str) and text.strip() else ""
    if kind == "tool-call":
        name = str(part.get("toolName") or "инструмент")
        return f"Вызов {name}\n{_json_text(part.get('args'))}"
    return ""


def _tool_part(part: Any) -> str:
    if not isinstance(part, dict):
        return ""
    name = str(part.get("toolName") or "инструмент")
    return f"## Ответ {name}\n{_json_text(part.get('result'))}"


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, indent=2)
