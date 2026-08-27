from __future__ import annotations

from app.api_client import BoardAgent, BoardStats, WorkflowBoard, WorkflowPlan, WorkflowPlanStep, WorkflowRecord
from app.orchestrator.models import MEETING_ID, REVISION_ID, DEFINITIONS, ProcessDefinition

REVISION_WORKFLOW_ID = "orch-revision-commission"
MEETING_WORKFLOW_ID = "orch-meeting-prep"

_WORKFLOW_IDS = {
    REVISION_ID: REVISION_WORKFLOW_ID,
    MEETING_ID: MEETING_WORKFLOW_ID,
}

_TITLE_KEYS = {
    REVISION_ID: ("ревизион",),
    MEETING_ID: ("совещани",),
}


def workflow_id_for_definition(definition_id: str) -> str:
    return _WORKFLOW_IDS.get(definition_id, "")


def is_local_workflow(workflow_id: str) -> bool:
    return (workflow_id or "").strip() in set(_WORKFLOW_IDS.values())


def local_workflow(workflow_id: str) -> WorkflowRecord | None:
    wid = (workflow_id or "").strip()
    for record in local_workflows():
        if record.id == wid:
            return record
    return None


def local_workflows() -> tuple[WorkflowRecord, ...]:
    return (
        _revision_workflow(),
        _meeting_workflow(),
    )


def local_board() -> WorkflowBoard:
    agents = [_board_agent(item) for item in local_workflows()]
    return WorkflowBoard(
        stats=BoardStats(active_agents=len(agents)),
        agents=agents,
    )


def match_board_agent(
    definition: ProcessDefinition,
    agents: list[BoardAgent],
) -> BoardAgent | None:
    keys = _TITLE_KEYS.get(definition.id, ())
    wanted = workflow_id_for_definition(definition.id)
    exact_title = definition.title.casefold()
    for agent in agents:
        if agent.kind != "workflow":
            continue
        if wanted and agent.id == wanted:
            return agent
        title = (agent.title or "").casefold()
        if title == exact_title:
            return agent
        if keys and any(key in title for key in keys):
            return agent
    return None


def bound_workflow_id(definition: ProcessDefinition, agents: list[BoardAgent] | None = None) -> str:
    matched = match_board_agent(definition, agents or [])
    if matched is not None and matched.id:
        return matched.id
    return workflow_id_for_definition(definition.id)


def _board_agent(record: WorkflowRecord) -> BoardAgent:
    goal = record.plan.goal if record.plan is not None else ""
    return BoardAgent(
        id=record.id,
        kind="workflow",
        title=record.title,
        description=goal,
        status="active",
        phase="done",
        trigger_summary="Запуск из оркестратора",
        trigger_kind="manual",
    )


def _revision_workflow() -> WorkflowRecord:
    return WorkflowRecord(
        id=REVISION_WORKFLOW_ID,
        title="Работа ревизионной комиссии",
        phase="done",
        notes="Агент корпоративного секретаря: пакет, протокол и поручения РК.",
        plan=WorkflowPlan(
            title="Работа ревизионной комиссии",
            goal=(
                "Собрать комплект к заседанию ревизионной комиссии, "
                "подготовить протокол и поставить на контроль поручения."
            ),
            constraints=[
                "Работать от должности корпоративного секретаря.",
                "Не выдумывать документы: брать факты из 1С, почты, календаря и файлов агента.",
                "Если данных не хватает — явно написать, чего не хватает.",
            ],
            out_of_scope=["Публикация решений без проверки человеком."],
            steps=[
                WorkflowPlanStep(
                    id="calendar",
                    title="Ближайшее заседание",
                    action="Найди ближайшее заседание ревизионной комиссии в календаре и почте.",
                    done_when="Известны дата, участники и повестка.",
                ),
                WorkflowPlanStep(
                    id="pack",
                    title="Пакет материалов",
                    action="Собери список материалов к заседанию и отметь, чего не хватает.",
                    done_when="Есть перечень документов и статус готовности пакета.",
                ),
                WorkflowPlanStep(
                    id="instructions",
                    title="Поручения РК",
                    action="Выгрузи поручения ревизионной комиссии и покажи просроченные и без ответа.",
                    done_when="Есть реестр поручений со сроками и ответственными.",
                ),
                WorkflowPlanStep(
                    id="protocol",
                    title="Протокол",
                    action="Подготовь черновик протокола и список решений к подтверждению.",
                    done_when="Есть текст протокола или явный список недостающих фактов.",
                ),
            ],
            test_criteria=[
                "В результате есть дата заседания или причина, почему её нет.",
                "Есть статус пакета материалов.",
                "Есть поручения или явное «поручений не найдено».",
            ],
            raw_text=(
                "Пилотный агент должности «Корпоративный секретарь». "
                "Зона: ревизионная комиссия. KPI: своевременность пакета, протокола и контроль поручений."
            ),
        ),
    )


def _meeting_workflow() -> WorkflowRecord:
    return WorkflowRecord(
        id=MEETING_WORKFLOW_ID,
        title="Подготовка совещания",
        phase="done",
        notes="Агент корпоративного секретаря: пакет и протокол совета директоров / совещания.",
        plan=WorkflowPlan(
            title="Подготовка совещания",
            goal=(
                "Подготовить пакет к совещанию или заседанию совета директоров "
                "и черновик протокола без возвратов по замечаниям."
            ),
            constraints=[
                "Работать от должности корпоративного секретаря.",
                "Опираться на календарь, почту, 1С и файлы агента.",
                "Не закрывать протокол как финальный без решения человека.",
            ],
            out_of_scope=["Рассылка итогового протокола без подтверждения."],
            steps=[
                WorkflowPlanStep(
                    id="agenda",
                    title="Повестка",
                    action="Найди ближайшее совещание или заседание СД и восстанови повестку.",
                    done_when="Известны дата, участники и вопросы.",
                ),
                WorkflowPlanStep(
                    id="materials",
                    title="Материалы",
                    action="Проверь комплект материалов к каждому вопросу повестки.",
                    done_when="По каждому вопросу понятно, готов материал или чего не хватает.",
                ),
                WorkflowPlanStep(
                    id="protocol",
                    title="Протокол",
                    action="Собери черновик протокола и решения, которые нужно зафиксировать.",
                    done_when="Есть черновик или список пробелов.",
                ),
                WorkflowPlanStep(
                    id="followup",
                    title="Поручения",
                    action="Выпиши поручения по итогам и поставь их на контроль.",
                    done_when="Есть реестр поручений или явное «поручений нет».",
                ),
            ],
            test_criteria=[
                "Есть ближайшее совещание или причина, почему его нет.",
                "Есть статус пакета материалов.",
                "Есть черновик протокола или список недостающих фактов.",
            ],
            raw_text=(
                "Пилотный агент должности «Корпоративный секретарь». "
                "Зона: подготовка совещания / СД. KPI: пакет вовремя, протокол вовремя, качество без возвратов."
            ),
        ),
    )


__all__ = [
    "MEETING_WORKFLOW_ID",
    "REVISION_WORKFLOW_ID",
    "bound_workflow_id",
    "is_local_workflow",
    "local_board",
    "local_workflow",
    "local_workflows",
    "match_board_agent",
    "workflow_id_for_definition",
    "DEFINITIONS",
]
