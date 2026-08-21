from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.models import ChatCommand, UiAction, UiSpec


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(\{.*?\})\s*```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Пустой ответ агента")

    for match in _JSON_BLOCK_RE.finditer(raw):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(raw[start : end + 1])
        if isinstance(data, dict):
            return data

    raise ValueError("Не найден JSON в ответе агента")


def parse_ui_spec(text: str) -> UiSpec:
    data = extract_json_object(text)
    try:
        return UiSpec.model_validate(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def clarifications_to_text(answers: dict[str, str]) -> str:
    if not answers:
        return ""
    lines = ["Ответы пользователя на уточнения:"]
    for key, value in answers.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def fallback_ui_spec(regulation_text: str, file_name: str = "") -> UiSpec:
    title = (file_name or "Агент по регламенту").rsplit(".", 1)[0]
    excerpt = regulation_text[:2000]
    return UiSpec(
        title=title[:120],
        summary="Черновик (Cursor API недоступен)",
        rules_prompt=excerpt,
        actions=[
            UiAction(
                id="summarize",
                label="Кратко по регламенту",
                hint="Обзор",
                prompt="Кратко опиши ключевые правила регламента.",
            ),
            UiAction(
                id="check_calendar",
                label="Проверить календарь",
                hint="Outlook",
                prompt="Проверь календарь Outlook на ближайшую неделю.",
                tools_hint=["outlook.read_calendar"],
            ),
        ],
        chat_commands=[
            ChatCommand(command="/help", description="Список команд"),
            ChatCommand(command="/calendar", description="Календарь Outlook"),
        ],
    )
