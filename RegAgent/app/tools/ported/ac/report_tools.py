"""Локальные report tools без изменений внешних систем."""

from __future__ import annotations

from app.tools.ported.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.ported.ac.base import BaseTool
from app.tools.ported.ac.registry import ToolRegistry


class LocalBuildMeetingSummaryTool(BaseTool):
    """Формирует локальную сводку совещаний."""

    def __init__(self) -> None:
        """Создать tool."""
        super().__init__(
            ToolDefinition(
                name="report.build_meeting_summary",
                title="Формирование материалов совещания",
                description="Формирует сводку, повестку или протокол без записи в Outlook.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть краткую сводку по событиям календаря."""
        events = _calendar_events(input_data)
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "summary_text": f"Найдено совещаний: {len(events)}. Подготовлена краткая сводка.",
                "event_count": len(events),
            },
        )


class LocalBuildScheduleRecommendationsTool(BaseTool):
    """Формирует рекомендации по планированию графика на основе календаря."""

    def __init__(self) -> None:
        """Создать tool."""
        super().__init__(
            ToolDefinition(
                name="report.build_schedule_recommendations",
                title="Рекомендации по планированию графика",
                description="Формирует рекомендации по расписанию без изменения календаря.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Сформировать рекомендации по плотности, окнам и фокус-времени."""
        calendar_output = _calendar_output(input_data)
        if calendar_output is None:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CALENDAR_DATA_MISSING",
                error_message="Нет данных календаря для формирования рекомендаций",
            )
        if calendar_output.get("ok") is False or calendar_output.get("error_type"):
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CALENDAR_DATA_NOT_AVAILABLE",
                error_message=(
                    calendar_output.get("error_message")
                    or calendar_output.get("error_type")
                    or "Данные календаря недоступны"
                ),
            )
        if "events" not in calendar_output:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CALENDAR_EVENTS_MISSING",
                error_message="Данные календаря не содержат events",
            )

        raw_events = calendar_output.get("events")
        if not isinstance(raw_events, list):
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CALENDAR_EVENTS_MISSING",
                error_message="Поле events должно быть списком",
            )
        events = [event for event in raw_events if isinstance(event, dict)]
        if not events:
            return ToolCallResult(
                ok=True,
                tool_name=self.definition.name,
                output_data={
                    "recommendation_text": "В выбранном периоде совещания не найдены.",
                    "meeting_count": 0,
                    "busy_slots": [],
                    "free_slots": [],
                    "risks": [],
                    "recommendations": [
                        "Используйте свободное время для фокус-работы или планирования."
                    ],
                },
            )

        analytics = (
            input_data.get("tool_outputs", {})
            .get("llm.analyze_collected_data", {})
        )
        if not isinstance(analytics, dict):
            analytics = {}
        busy_slots = [
            {
                "title": event.get("title", "Совещание"),
                "start_at": event.get("start_at"),
                "risk": "meeting_load",
            }
            for event in events
        ]
        free_slots = _clean_str_list(analytics.get("free_slots"))
        risks = _clean_str_list(analytics.get("risks"))
        recommendations = _clean_str_list(analytics.get("recommendations"))
        recommendation_text = _first_non_empty_text(
            analytics.get("summary"),
            "\n".join(recommendations) if recommendations else None,
            f"Найдено совещаний: {len(events)}. "
            "Аналитика LLM не предоставила рекомендаций.",
        )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "recommendation_text": recommendation_text,
                "meeting_count": len(events),
                "busy_slots": busy_slots,
                "free_slots": free_slots,
                "risks": risks,
                "recommendations": recommendations,
                "analysis_source": "llm.analyze_collected_data"
                if analytics
                else "none",
            },
        )


class LocalBuildTaskReportTool(BaseTool):
    """Формирует отчёт по поручениям и рискам просрочки на основе собранных данных."""

    def __init__(self) -> None:
        """Создать tool."""
        super().__init__(
            ToolDefinition(
                name="report.build_task_report",
                title="Отчёт по поручениям",
                description=(
                    "Формирует отчёт по поручениям с рисками просрочки на основе "
                    "собранных данных и аналитики LLM, без записи во внешние системы."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Собрать отчёт из аналитики LLM и найденных поручений (без хардкода)."""
        tool_outputs = input_data.get("tool_outputs", {})
        if not isinstance(tool_outputs, dict):
            tool_outputs = {}
        analytics = tool_outputs.get("llm.analyze_collected_data", {})
        if not isinstance(analytics, dict):
            analytics = {}

        tasks = _collect_tasks(tool_outputs)
        risks = _clean_str_list(analytics.get("risks"))
        recommendations = _clean_str_list(analytics.get("recommendations"))
        findings = _clean_str_list(analytics.get("findings"))

        if not analytics and not tasks:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="TASK_DATA_MISSING",
                error_message=(
                    "Нет собранных поручений и аналитики для формирования отчёта"
                ),
            )

        report_text = _first_non_empty_text(
            analytics.get("summary"),
            "\n".join(findings) if findings else None,
            f"Найдено поручений: {len(tasks)}. Рисков просрочки: {len(risks)}.",
        )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "report_text": report_text,
                "task_count": len(tasks),
                "risk_count": len(risks),
                "tasks": tasks,
                "risks": risks,
                "recommendations": recommendations,
                "analysis_source": "llm.analyze_collected_data"
                if analytics
                else "none",
            },
        )


def register_report_tools(
    registry: ToolRegistry,
    *,
    skip_existing: bool = False,
) -> None:
    """Зарегистрировать локальные report tools."""
    for tool in [
        LocalBuildMeetingSummaryTool(),
        LocalBuildScheduleRecommendationsTool(),
        LocalBuildTaskReportTool(),
    ]:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)


def _collect_tasks(tool_outputs: dict) -> list[dict]:
    """Собрать поручения из результатов 1С и Outlook без выдумывания данных."""
    tasks: list[dict] = []
    for key in ("onec.search_tasks", "outlook.read_tasks"):
        output = tool_outputs.get(key)
        if isinstance(output, dict):
            items = output.get("tasks")
            if isinstance(items, list):
                tasks.extend(item for item in items if isinstance(item, dict))
    card = tool_outputs.get("onec.get_task_card")
    if isinstance(card, dict) and isinstance(card.get("task"), dict):
        tasks.append(card["task"])
    return tasks


def _calendar_events(input_data: dict) -> list[dict]:
    """Достать events из tool_outputs outlook.read_calendar."""
    output = _calendar_output(input_data) or {}
    events = output.get("events", [])
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]
    return []


def _calendar_output(input_data: dict) -> dict | None:
    """Достать output outlook.read_calendar без подстановки fake данных."""
    tool_outputs = input_data.get("tool_outputs", {})
    if not isinstance(tool_outputs, dict):
        return None
    output = tool_outputs.get("outlook.read_calendar")
    if isinstance(output, dict):
        return output
    return None


def _clean_str_list(value: object) -> list[str]:
    """Вернуть список непустых строк из значения аналитики LLM."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            text = item.get("text") or item.get("title") or item.get("summary")
            if isinstance(text, str) and text.strip():
                result.append(text.strip())
    return result


def _first_non_empty_text(*candidates: object) -> str:
    """Вернуть первую непустую строку из кандидатов."""
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return "Рекомендации не сформированы."

