"""Show meetings on the in-app calendar (not Outlook write)."""

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


def _current_run_id(input_data: dict) -> str:
    return str(
        input_data.get("run_id")
        or (input_data.get("runtime_context") or {}).get("run_id")
        or (input_data.get("runtime_context") or {}).get("history_id")
        or ""
    ).strip()


class CalendarShowMeetingsTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name="calendar.show_meetings",
                title="Показать план совещаний",
                description=(
                    "Рисует итоговый план совещаний отдельной мини-формой календаря "
                    "в ответе агента (её можно раскрыть модальным окном). "
                    "Не ставит совещания на общую вкладку «Календарь запусков». "
                    "mark=cancel или red - красным, рекомендовано отменить. "
                    "mark=add или green - зелёным, рекомендовано поставить. "
                    "mark=keep - уже запланированное. "
                    "Вызови при формировании результата, чтобы человек увидел план. "
                    "Инструмент только визуализирует и НИЧЕГО не двигает и не пишет в Outlook. "
                    "Конфликты со встречами решает сам агент: сверяет календари участников "
                    "и их загрузку, переносит нужное через outlook.create_event и отражает итог здесь."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "meetings": {
                            "type": "array",
                            "description": "Список совещаний для календаря",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string", "description": "Тема совещания"},
                                    "start": {
                                        "type": "string",
                                        "description": "Начало ISO datetime",
                                    },
                                    "end": {
                                        "type": "string",
                                        "description": "Конец ISO datetime",
                                    },
                                    "mark": {
                                        "type": "string",
                                        "description": "keep, cancel/red или add/green",
                                    },
                                    "reason": {
                                        "type": "string",
                                        "description": "Почему отменить или поставить",
                                    },
                                },
                                "required": ["title", "start"],
                            },
                        },
                        "title": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "mark": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "shown": {"type": "integer"},
                        "ok": {"type": "boolean"},
                        "meetings": {"type": "array"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        meetings = input_data.get("meetings")
        if not isinstance(meetings, list) or not meetings:
            if str(input_data.get("title") or "").strip() and str(input_data.get("start") or "").strip():
                meetings = [
                    {
                        "title": input_data.get("title"),
                        "start": input_data.get("start"),
                        "end": input_data.get("end") or "",
                        "mark": input_data.get("mark") or "keep",
                        "reason": input_data.get("reason") or "",
                    }
                ]
            else:
                return ToolCallResult(
                    ok=False,
                    tool_name=self.definition.name,
                    error_type="INVALID_INPUT",
                    error_message="Nuzhen meetings[] s title i start.",
                )
        payload = {
            "workflow_id": _current_workflow_id(input_data),
            "run_id": _current_run_id(input_data),
            "meetings": meetings,
        }
        try:
            data = request("POST", "/api/v1/calendar/overlays", json=payload)
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CALENDAR_SHOW_FAILED",
                error_message=str(exc),
            )
        shown = data.get("meetings") if isinstance(data, dict) else None
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "ok": True,
                "shown": len(meetings) if isinstance(meetings, list) else 0,
                "meetings": shown if isinstance(shown, list) and shown else meetings,
            },
        )


def register_calendar_tools(registry: ToolRegistry, *, skip_existing: bool = False) -> None:
    tool = CalendarShowMeetingsTool()
    if skip_existing and registry.has_tool(tool.definition.name):
        return
    registry.register(tool)
