from __future__ import annotations

from app.models.workflow import Workflow
from app.services.agent_route import resolve_agent_route
from app.services.regulation_constructor_workflow import (
    apply_regulation_constructor_workflow,
    is_regulation_constructor_workflow,
)


def test_outlook_regulation_constructor() -> None:
    wf = Workflow(
        id="w-outlook",
        title="Календарь совещаний",
        document_name="reglament_outlook.docx",
        document_text="Агент работает с Outlook календарём и планирует встречи через COM.",
        notes="# Паспорт ИИ-агента: Календарь\n\nЦель: планирование совещаний",
        plan_json={},
        local_run={"passport_title": "Календарь", "from_regulation_constructor": True},
        phase="document",
    )
    assert is_regulation_constructor_workflow(wf)
    assert apply_regulation_constructor_workflow(wf) is True
    route = resolve_agent_route(wf)
    assert route.handler == "outlook_calendar"
    assert wf.phase == "tested"
    assert (wf.local_run or {}).get("execution_backend") == "mcp"
    tools = (wf.local_run or {}).get("tools") or []
    assert isinstance(tools, list)


def test_act_still_uses_plugin() -> None:
    wf = Workflow(
        id="w-act",
        title="ACT-реестр",
        document_name="ACT_REGISTRY.md",
        document_text="Document_ТД_Поручения ACT00-00088 OData Excel",
        notes="ACT-реестр",
        plan_json={},
        local_run={"passport_title": "ACT-реестр", "from_regulation_constructor": True},
        phase="document",
    )
    assert apply_regulation_constructor_workflow(wf) is True
    route = resolve_agent_route(wf)
    assert route.handler == "act_porucheniya_registry"
    assert "excel.create_workbook" in ((wf.local_run or {}).get("tools") or [])


def test_generic_regulation_gets_heuristic_plan() -> None:
    wf = Workflow(
        id="w-gen",
        title="Внутренний регламент",
        document_name="process.md",
        document_text="Сотрудник формирует отчёт и контролирует сроки исполнения.",
        notes="## Паспорт\n\nЦель: автоматизировать отчётность",
        plan_json={},
        local_run={"from_regulation_constructor": True},
        phase="document",
    )
    assert apply_regulation_constructor_workflow(wf) is True
    plan = wf.plan_json if isinstance(wf.plan_json, dict) else {}
    assert (plan.get("goal") or "").strip()
    assert plan.get("steps")
