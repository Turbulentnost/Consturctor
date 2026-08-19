from __future__ import annotations

from app.models.workflow import Workflow
from app.services.act_registry_workflow import (
    apply_act_registry_spec_to_workflow,
    workflow_looks_like_act_registry,
)
from app.services.agent_route import resolve_agent_route


def test_workflow_looks_like_act_registry_from_document_name() -> None:
    wf = Workflow(
        id="w1",
        title="ИИ-агент",
        document_name="ACT_REGISTRY.md",
        document_text="Document_ТД_Поручения ACT00-00088",
        notes="",
        plan_json={},
        local_run={},
    )
    assert workflow_looks_like_act_registry(wf)


def test_apply_act_registry_spec_sets_route_and_tools() -> None:
    wf = Workflow(
        id="w2",
        title="ИИ-агент",
        document_name="ACT_REGISTRY.md",
        document_text="Document_ТД_Поручения ACT00",
        notes="ACT-реестр поручений",
        plan_json={},
        local_run={"passport_title": "ACT-реестр"},
        phase="document",
    )
    assert apply_act_registry_spec_to_workflow(wf) is True
    route = resolve_agent_route(wf)
    assert route.handler == "act_porucheniya_registry"
    assert wf.exec_agent_id == "mcp:act_porucheniya_registry"
    assert wf.phase == "tested"
    tools = (wf.local_run or {}).get("tools") or []
    assert "excel.create_workbook" in tools
    assert "act_protocol_merge" in tools


def test_generic_porucheniya_without_act_markers_not_forced() -> None:
    wf = Workflow(
        id="w3",
        title="Поручения 1С",
        notes="Задачи сотрудников из 1С ERP",
        document_text="",
        plan_json={},
        local_run={},
    )
    assert workflow_looks_like_act_registry(wf) is False
