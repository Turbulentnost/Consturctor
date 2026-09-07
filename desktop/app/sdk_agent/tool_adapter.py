from __future__ import annotations

from typing import Any

from app.tools import ToolHostError, invoke_tool
from app.tools.catalog import list_desktop_tools

ASK_QUESTION_NAME = "askQuestion"
DEFAULT_TOOL_TIMEOUT_SECONDS = 90
ASK_QUESTION_TIMEOUT_SECONDS = 15 * 60
WAIT_TOOL_NAME = "agent.wait"
WAIT_TIMEOUT_BUFFER_SECONDS = 60

ASK_QUESTION_SPEC: dict[str, Any] = {
    "name": ASK_QUESTION_NAME,
    "timeoutSeconds": ASK_QUESTION_TIMEOUT_SECONDS,
    "description": (
        "Задать пользователю один уточняющий вопрос про пробел в логике "
        "будущего агента и дождаться ответа. Спрашивай то, чего нет в материалах, "
        "но без чего агент будет додумывать правило работы. "
        "Если нужен исходный документ пользователя, передай needsFile=true "
        "и accept: xlsx, xlsm или docx. Пользователь загрузит Excel или Word. "
        "Файл временный: только для этого шага, не в постоянную базу знаний. "
        "В одном вызове один пробел. Не объединяй несколько вопросов. "
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
                "description": "2-6 конкретных вариантов ответа, если файл не нужен",
            },
            "needsFile": {
                "type": "boolean",
                "description": "true, если пользователь должен приложить Excel или Word",
            },
            "accept": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Разрешенные расширения: xlsx, xlsm, docx",
            },
        },
        "required": ["question"],
    },
}


def is_ask_question(name: str) -> bool:
    folded = (name or "").strip().casefold()
    return folded in {"askquestion", "ask_question"}


def sdk_design_tool_specs() -> list[dict[str, Any]]:
    return sdk_tool_specs()


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
        spec: dict[str, Any] = {
            "name": name,
            "description": description,
            "inputSchema": schema,
        }
        try:
            timeout = int(item.get("timeoutSeconds") or 0)
        except (TypeError, ValueError):
            timeout = 0
        if timeout > 0:
            spec["timeoutSeconds"] = timeout
        specs.append(spec)
    return specs


def tool_timeout_seconds(name: str, arguments: dict[str, Any] | None = None) -> int:
    """How long the SDK bridge may wait for a desktop tool before aborting."""
    folded = (name or "").strip()
    if folded == WAIT_TOOL_NAME:
        requested = 0.0
        if isinstance(arguments, dict):
            try:
                requested = float(arguments.get("seconds") or 0)
            except (TypeError, ValueError):
                requested = 0.0
        if requested < 0:
            requested = 0.0
        from app.tools.ac.wait_tool import MAX_WAIT_SECONDS

        return int(min(requested + WAIT_TIMEOUT_BUFFER_SECONDS, MAX_WAIT_SECONDS + WAIT_TIMEOUT_BUFFER_SECONDS))
    if is_ask_question(folded):
        return ASK_QUESTION_TIMEOUT_SECONDS
    limit = DEFAULT_TOOL_TIMEOUT_SECONDS
    try:
        from app.tools.ac.dispatch import get_registry

        registry = get_registry()
        if registry.has_tool(folded):
            limit = max(limit, int(registry.get(folded).definition.timeout_seconds))
    except Exception:
        pass
    return int(limit)


def invoke_sdk_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    try:
        result = invoke_tool(name, arguments if isinstance(arguments, dict) else {})
    except ToolHostError:
        raise
    if isinstance(result, dict):
        return result
    return {"value": result}
