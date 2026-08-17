"""Инструменты планирования запуска агента."""

from __future__ import annotations

from app.tools.ac.base import BaseTool
from app.tools.ac.registry import ToolRegistry
from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.runtime_api import request


def _current_workflow_id(input_data: dict) -> str:
    return str(
        input_data.get("workflow_id")
        or (input_data.get("runtime_context") or {}).get("workflow_id")
        or (input_data.get("runtime_context") or {}).get("agent_id")
        or input_data.get("agent_id")
        or ""
    ).strip()


class AgentScheduleTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name="agent.schedule",
                title="Запланировать агента",
                description=(
                    "Ставит запуск агента на время, через N секунд или по свободному условию. "
                    "condition — любой текст: «когда изменится файл X», «когда придёт письмо от Ивана». "
                    "Пустой workflow_id — запустить текущего агента. "
                    "once=false — повторять после срабатывания с паузой."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "id агента; пусто = текущий",
                        },
                        "message": {"type": "string", "description": "Задача при старте"},
                        "at": {"type": "string", "description": "ISO-время запуска"},
                        "after_seconds": {"type": "number", "description": "Задержка в секундах"},
                        "condition": {
                            "type": "string",
                            "description": "Свободное условие срабатывания",
                        },
                        "once": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object", "properties": {"id": {"type": "string"}}},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        workflow_id = _current_workflow_id(input_data)
        created_by = str(
            (input_data.get("runtime_context") or {}).get("workflow_id")
            or (input_data.get("runtime_context") or {}).get("agent_id")
            or input_data.get("agent_id")
            or workflow_id
        ).strip()
        at = str(input_data.get("at") or input_data.get("send_at") or "").strip() or None
        after_raw = input_data.get("after_seconds")
        if after_raw is None:
            after_raw = input_data.get("after")
        condition = str(input_data.get("condition") or "").strip()
        if not workflow_id:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_INPUT",
                error_message="Нужен workflow_id агента.",
            )
        if not at and after_raw is None and not condition:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_INPUT",
                error_message="Укажи at, after_seconds или condition.",
            )
        payload: dict = {
            "workflow_id": workflow_id,
            "created_by_workflow_id": created_by,
            "message": str(input_data.get("message") or ""),
            "condition": condition,
            "once": bool(input_data["once"]) if "once" in input_data else True,
        }
        if at:
            payload["at"] = at
        if after_raw is not None and str(after_raw).strip() != "":
            payload["after_seconds"] = after_raw
        try:
            data = request("POST", "/api/v1/triggers", json=payload)
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="SCHEDULE_FAILED",
                error_message=str(exc),
            )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data=data if isinstance(data, dict) else {"ok": True},
        )


class AgentScheduleCancelTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name="agent.schedule.cancel",
                title="Отменить триггер агента",
                description="Отменяет триггер, созданный через agent.schedule. Нужен trigger_id из ответа schedule.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "trigger_id": {"type": "string"},
                    },
                    "required": ["trigger_id"],
                },
                output_schema={"type": "object", "properties": {"id": {"type": "string"}}},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        trigger_id = str(input_data.get("trigger_id") or input_data.get("id") or "").strip()
        if not trigger_id:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_INPUT",
                error_message="Нужен trigger_id.",
            )
        try:
            data = request("POST", f"/api/v1/triggers/{trigger_id}/cancel")
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CANCEL_FAILED",
                error_message=str(exc),
            )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data=data if isinstance(data, dict) else {"ok": True},
        )


def register_schedule_tools(registry: ToolRegistry, *, skip_existing: bool = False) -> None:
    for tool in (AgentScheduleTool(), AgentScheduleCancelTool()):
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)
