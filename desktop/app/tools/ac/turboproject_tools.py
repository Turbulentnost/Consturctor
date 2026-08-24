"""Паспорт и прокси TurboProject: исполнение на backend Constructor."""

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

TOOL_NAME = "turboproject"
LIST_TOOL_NAME = "turboproject.list"
GET_TOOL_NAME = "turboproject.get"
_SAMPLE_LIMIT = 5
_MAX_OVERDUE_ITEMS = 8
_MAX_RESOURCES = 20

TOOL_DESCRIPTION = (
    "Быстрый индекс проектов TurboProject с 1С. Не читает карточки MPP. "
    "Для задач, просрочек, ресурсов и полной карточки используй turboproject.get(file_id). "
    "Учётка уже в backend/.env — не спрашивай логин и не вызывай API сам.\n\n"
    "Итог:\n"
    "• total_projects — сколько файлов вернул список;\n"
    "• projects_with_1c_count — сколько из них с 1С;\n"
    "• generated_at — время сборки JSON;\n"
    "• projects — строки индекса проектов с 1С.\n\n"
    "Поля индекса:\n"
    "• file_id — ProjectFile.id;\n"
    "• original_name — имя загруженного MPP;\n"
    "• uploaded_at — дата загрузки MPP;\n"
    "• project_name — project.name или имя файла;\n"
    "• dates — только даты, доступные в списке;\n"
    "• data_1c — короткие поля 1С, если они есть в списке.\n\n"
    "Аргументы: query (только название / имя MPP / номер 1С, не фраза), "
    "manager, file_id (тогда вернётся карточка), limit."
)

GET_TOOL_DESCRIPTION = (
    "Полная карточка одного проекта TurboProject по file_id из turboproject.list. "
    "Возвращает даты MSP/1С, статистику задач, просрочки, ресурсы и data_1c. "
    "Не вызывай без file_id и не используй для полного портфеля."
)


class TurboProjectTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name=TOOL_NAME,
                title="Проекты TurboProject",
                description=TOOL_DESCRIPTION,
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                timeout_seconds=180,
                max_retries=1,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Название проекта, имя MPP или номер 1С — не фраза "
                                "и не список участников"
                            ),
                        },
                        "manager": {
                            "type": "string",
                            "description": "ФИО руководителя проекта из 1С",
                        },
                        "file_id": {
                            "type": "string",
                            "description": "ID файла проекта (ProjectFile.id)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Максимум строк индекса в ответе",
                        },
                    },
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "total_projects": {"type": "integer"},
                        "projects_with_1c_count": {"type": "integer"},
                        "generated_at": {"type": "string"},
                        "projects": {"type": "array"},
                        "summary": {"type": "string"},
                        "source": {"type": "string"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        arguments = {
            key: input_data[key]
            for key in ("query", "manager", "file_id", "limit")
            if key in input_data and input_data[key] not in (None, "")
        }
        endpoint_tool = GET_TOOL_NAME if arguments.get("file_id") else LIST_TOOL_NAME
        try:
            data = request(
                "POST",
                f"/api/v1/tools/{endpoint_tool}/invoke",
                json={"arguments": arguments},
                timeout=180.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="TURBOPROJECT_FAILED",
                error_message=str(exc),
            )
        result = data.get("result") if isinstance(data, dict) else {}
        if isinstance(result, dict):
            result = _sample_for_agent(result, arguments)
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data=result if isinstance(result, dict) else {"result": result},
        )


class TurboProjectListTool(TurboProjectTool):
    def __init__(self) -> None:
        super().__init__()
        self.definition.name = LIST_TOOL_NAME
        self.definition.title = "Список проектов TurboProject"


class TurboProjectGetTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name=GET_TOOL_NAME,
                title="Карточка проекта TurboProject",
                description=GET_TOOL_DESCRIPTION,
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                timeout_seconds=180,
                max_retries=1,
                input_schema={
                    "type": "object",
                    "required": ["file_id"],
                    "properties": {
                        "file_id": {
                            "type": "string",
                            "description": "ID файла проекта из turboproject.list",
                        },
                        "overdue_only": {
                            "type": "boolean",
                            "default": False,
                            "description": "Вернуть проект только если в карточке есть просроченные задачи или вехи",
                        },
                    },
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "total_projects": {"type": "integer"},
                        "projects_with_1c_count": {"type": "integer"},
                        "generated_at": {"type": "string"},
                        "projects": {"type": "array"},
                        "summary": {"type": "string"},
                        "source": {"type": "string"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        arguments = {
            key: input_data[key]
            for key in ("file_id", "overdue_only")
            if key in input_data and input_data[key] not in (None, "")
        }
        try:
            data = request(
                "POST",
                f"/api/v1/tools/{GET_TOOL_NAME}/invoke",
                json={"arguments": arguments},
                timeout=180.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="TURBOPROJECT_FAILED",
                error_message=str(exc),
            )
        result = data.get("result") if isinstance(data, dict) else {}
        if isinstance(result, dict):
            result = _sample_for_agent(result, arguments)
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data=result if isinstance(result, dict) else {"result": result},
        )


def _sample_for_agent(result: dict, arguments: dict) -> dict:
    payload = dict(result)
    projects = payload.get("projects")
    if not isinstance(projects, list):
        return payload
    focused = any(arguments.get(key) for key in ("query", "manager", "file_id"))
    raw_limit = arguments.get("limit")
    cap = _SAMPLE_LIMIT
    if raw_limit not in (None, ""):
        try:
            cap = max(1, min(int(raw_limit), _SAMPLE_LIMIT if not focused else 20))
        except (TypeError, ValueError):
            cap = _SAMPLE_LIMIT
    elif not focused:
        cap = _SAMPLE_LIMIT
    else:
        cap = min(len(projects), 20)
    sampled = []
    for item in projects[:cap]:
        if not isinstance(item, dict):
            continue
        card = dict(item)
        overdue = card.get("overdue_tasks")
        milestones = card.get("overdue_milestones")
        resources = card.get("resources")
        if isinstance(overdue, list) and len(overdue) > _MAX_OVERDUE_ITEMS:
            card["overdue_tasks"] = overdue[:_MAX_OVERDUE_ITEMS]
        if isinstance(milestones, list) and len(milestones) > _MAX_OVERDUE_ITEMS:
            card["overdue_milestones"] = milestones[:_MAX_OVERDUE_ITEMS]
        if isinstance(resources, list) and len(resources) > _MAX_RESOURCES:
            card["resources"] = resources[:_MAX_RESOURCES]
        sampled.append(card)
    payload["projects"] = sampled
    if len(projects) > len(sampled):
        payload["sample"] = True
        summary = str(payload.get("summary") or "").strip()
        note = f"выборка {len(sampled)} из {len(projects)}, не весь портфель"
        payload["summary"] = f"{summary}; {note}" if summary else note
    return payload


def register_turboproject_tools(registry: ToolRegistry, *, skip_existing: bool = False) -> None:
    for tool in (TurboProjectTool(), TurboProjectListTool(), TurboProjectGetTool()):
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)
