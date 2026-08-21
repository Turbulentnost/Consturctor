from __future__ import annotations

import json
from typing import Any, Callable

from cursor_sdk import CustomTool, CustomToolContext

from app.tools.registry import ToolError, invoke_tool, list_tool_definitions

ConfirmCallback = Callable[[str, dict[str, Any]], bool]

_confirm_callback: ConfirmCallback | None = None

_WRITE_TOOLS = frozenset({"outlook.create_event"})


def set_confirm_callback(callback: ConfirmCallback | None) -> None:
    global _confirm_callback
    _confirm_callback = callback


def _needs_confirm(name: str) -> bool:
    return name in _WRITE_TOOLS


def _execute_tool(args: dict[str, Any], context: CustomToolContext) -> str:
    name = str(args.get("tool") or args.get("name") or "").strip()
    if not name:
        return json.dumps({"ok": False, "error": "tool name required"}, ensure_ascii=False)
    payload = args.get("arguments")
    if not isinstance(payload, dict):
        payload = {k: v for k, v in args.items() if k not in {"tool", "name"}}
    if _needs_confirm(name):
        cb = _confirm_callback
        if cb is None or not cb(name, payload):
            return json.dumps(
                {"ok": False, "error": "отклонено человеком"},
                ensure_ascii=False,
            )
    try:
        result = invoke_tool(name, payload)
        return json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str)
    except ToolError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def _schema_for_tool(defn) -> dict[str, Any]:
    schema = dict(defn.input_schema or {"type": "object", "properties": {}})
    if "properties" not in schema:
        schema["properties"] = {}
    return schema


def build_custom_tools() -> dict[str, CustomTool]:
    tools: dict[str, CustomTool] = {}
    for defn in list_tool_definitions():
        key = defn.name.replace(".", "_")
        tools[key] = CustomTool(
            description=f"{defn.title}. {defn.description} (вызов: tool={defn.name})",
            input_schema={
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "const": defn.name},
                    "arguments": _schema_for_tool(defn),
                },
                "required": ["arguments"],
            },
            execute=_execute_tool,
        )
    return tools


def build_unified_custom_tool() -> CustomTool:
    """Single entry point for all 1C/Outlook tools."""

    lines = [
        "Вызов 1C или Outlook на этом компьютере.",
        "Поручения (Документ.ТД_Поручения): tool=onec.docflow_tasks — OData, не COM и не shell.",
        "Доступные инструменты:",
    ]
    for defn in list_tool_definitions():
        lines.append(f"- {defn.name}: {defn.description}")

    properties: dict[str, Any] = {
        "tool": {
            "type": "string",
            "enum": [d.name for d in list_tool_definitions()],
            "description": "Имя инструмента",
        },
        "arguments": {"type": "object", "description": "Аргументы инструмента"},
    }

    return CustomTool(
        description="Вызов 1C или Outlook на этом компьютере.\n" + "\n".join(lines),
        input_schema={
            "type": "object",
            "properties": properties,
            "required": ["tool", "arguments"],
        },
        execute=_execute_tool,
    )
