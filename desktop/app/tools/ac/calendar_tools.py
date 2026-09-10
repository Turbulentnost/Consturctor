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
                    "Рисует итоговый план совещаний карточкой для доклада "
                    "(тема целиком, участники, кто кого замещает). "
                    "Не ставит совещания на общую вкладку «Календарь запусков». "
                    "mark=cancel или red - красным, рекомендовано отменить. "
                    "mark=add или green - зелёным, рекомендовано поставить. "
                    "mark=keep - уже запланированное. "
                    "В каждом совещании передай attendees[] и substitutes[] "
                    "(кто замещает кого: «Иванов замещает Петрова»). "
                    "Вызови при формировании результата, чтобы человек увидел план. "
                    "Инструмент только визуализирует и НИЧЕГО не двигает и не пишет в Outlook. "
                    "Утро / контроль календаря ПСД: после карточки сегодняшних встреч "
                    "(mark=keep) сразу ## WORK_RESULT, create_event не вызывай. "
                    "Вечер: сначала карточка сдвигов (keep/add/cancel), "
                    "outlook.create_event только после HITL."
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
                            "description": (
                                "Список совещаний: title, start, end, mark, reason, "
                                "organizer, attendees[], substitutes[] (кто замещает кого)"
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string", "description": "Тема совещания целиком"},
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
                                    "organizer": {
                                        "type": "string",
                                        "description": "Организатор или председатель",
                                    },
                                    "location": {
                                        "type": "string",
                                        "description": "Место или ссылка",
                                    },
                                    "attendees": {
                                        "type": "array",
                                        "description": "Участники: ФИО или почта",
                                        "items": {"type": "string"},
                                    },
                                    "substitutes": {
                                        "type": "array",
                                        "description": (
                                            "Кто кого замещает, например "
                                            "«Иванов замещает Петрова»"
                                        ),
                                        "items": {"type": "string"},
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
                        "organizer": input_data.get("organizer") or "",
                        "location": input_data.get("location") or "",
                        "attendees": input_data.get("attendees") or [],
                        "substitutes": input_data.get("substitutes") or [],
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
        # Overlay may still be an older API that strips people fields.
        # Keep the agent's payload so the briefing card can show attendees.
        payload_meetings = meetings if isinstance(meetings, list) else []
        if isinstance(shown, list) and shown:
            merged = []
            for index, remote in enumerate(shown):
                local = payload_meetings[index] if index < len(payload_meetings) else {}
                if not isinstance(remote, dict):
                    merged.append(local)
                    continue
                row = dict(remote)
                if isinstance(local, dict):
                    for key in (
                        "organizer",
                        "location",
                        "attendees",
                        "substitutes",
                        "required_attendees",
                        "optional_attendees",
                    ):
                        if not row.get(key) and local.get(key):
                            row[key] = local[key]
                merged.append(row)
            payload_meetings = merged
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "ok": True,
                "shown": len(payload_meetings),
                "meetings": payload_meetings,
            },
        )


def register_calendar_tools(registry: ToolRegistry, *, skip_existing: bool = False) -> None:
    tool = CalendarShowMeetingsTool()
    if skip_existing and registry.has_tool(tool.definition.name):
        return
    registry.register(tool)
