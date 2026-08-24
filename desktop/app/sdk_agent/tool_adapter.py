from __future__ import annotations

from typing import Any

from app.tools import ToolHostError, invoke_tool
from app.tools.catalog import list_desktop_tools

ASK_QUESTION_NAME = "askQuestion"

ASK_QUESTION_SPEC: dict[str, Any] = {
    "name": ASK_QUESTION_NAME,
    "description": (
        "Задать пользователю один уточняющий вопрос и дождаться ответа. "
        "В одном вызове спрашивай только один параметр: расписание, период, "
        "получатель или критерий успеха. Не объединяй несколько вопросов. "
        "Не вызывай повторно, если ответ по этой теме уже получен. "
        "Это Constructor customTool, не проектный MCP."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Один вопрос про один параметр, без списка из нескольких вопросов",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Варианты ответа, 2-6 пунктов",
            },
        },
        "required": ["question"],
    },
}


def is_ask_question(name: str) -> bool:
    folded = (name or "").strip().casefold()
    return folded in {"askquestion", "ask_question"}


def sdk_design_tool_specs() -> list[dict[str, Any]]:
    return [dict(ASK_QUESTION_SPEC)]


def sdk_tool_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [dict(ASK_QUESTION_SPEC)]
    for item in list_desktop_tools():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        schema = item.get("inputSchema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        description = str(item.get("description") or name).strip()
        specs.append(
            {
                "name": name,
                "description": description,
                "inputSchema": schema,
            }
        )
    return specs


def invoke_sdk_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    try:
        result = invoke_tool(name, arguments if isinstance(arguments, dict) else {})
    except ToolHostError:
        raise
    if isinstance(result, dict):
        return result
    return {"value": result}
