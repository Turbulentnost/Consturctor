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
_SAMPLE_LIMIT = 5
_MAX_OVERDUE_ITEMS = 8
_MAX_RESOURCES = 20

TOOL_DESCRIPTION = (
    "Проекты TurboProject с 1С. Большие ответы сохраняются в workspace для анализа tools Cursor SDK. "
    "Сервер ходит в API `/api/projects/files` и карточку файла. "
    "Учётка уже в backend/.env — не спрашивай логин и не вызывай API сам.\n\n"
    "Итог:\n"
    "• total_projects — сколько файлов вернул список;\n"
    "• projects_with_1c_count — сколько из них с 1С;\n"
    "• generated_at — время сборки JSON;\n"
    "• projects — список проектов с 1С.\n\n"
    "Поля проекта:\n"
    "• file_id — ProjectFile.id;\n"
    "• original_name — имя загруженного MPP;\n"
    "• uploaded_at — дата загрузки MPP;\n"
    "• project_name — project.name или имя файла;\n"
    "• dates.start_date / finish_date / actual_finish_date — план и факт из MSP;\n"
    "• dates.baseline_start / baseline_finish — базовый план MSP;\n"
    "• dates.plan_finish_1c — плановое окончание из 1С;\n"
    "• task_stats.total_tasks — все задачи, включая суммарные и вехи;\n"
    "• task_stats.non_summary_tasks — без суммарных;\n"
    "• task_stats.completed_tasks — несуммарные со 100% выполнения;\n"
    "• task_stats.overdue_tasks_count — не суммарные, не завершены, finish_date < сегодня;\n"
    "• task_stats.overdue_milestones_count — вехи, не завершены, finish_date < сегодня;\n"
    "• overdue_tasks[] — id, uid, name, start_date, finish_date, percent_complete, "
    "executors (assignments.resource_name);\n"
    "• overdue_milestones[] — id, uid, name, start_date, finish_date, percent_complete;\n"
    "• resources — уникальные ФИО ресурсов проекта;\n"
    "• data_1c — блок 1С: one_c_ref_key, nomer_proekta, status_proekta, tip_proekta, "
    "byudzhet_plan, byudzhet_fakt, data_nachala, data_okonchaniya, "
    "planovaya_data_nachala, planovaya_data_okonchaniya, rukovodstvo_proektom, "
    "osnovanie_zapuska, kolichestvo_perenosov, vkhodit_v_portfel, yavlyaetsya_portfelem, "
    "rukovoditel, kurator, zakazchik, investor, zam_rp, istochnik_finansirovaniya, "
    "podrazdelenie, organizatsiya, tseli_proekta, chek_list, resheniya, "
    "perenosy_proekta, synced_at.\n\n"
    "Аргументы: query (только название / имя MPP / номер 1С, не фраза), "
    "manager (одно ФИО руководителя 1С), file_id, overdue_only, limit."
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
                        "overdue_only": {
                            "type": "boolean",
                            "default": False,
                            "description": "Только проекты с просроченными задачами или вехами",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Максимум проектов в ответе",
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
            for key in ("query", "manager", "file_id", "overdue_only", "limit")
            if key in input_data and input_data[key] not in (None, "")
        }
        try:
            data = request(
                "POST",
                f"/api/v1/tools/{TOOL_NAME}/invoke",
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
    tool = TurboProjectTool()
    if skip_existing and registry.has_tool(tool.definition.name):
        return
    registry.register(tool)
