from __future__ import annotations

from app.models.workflow import Workflow
from app.services.workflow_tool_routing import default_tools_for_kind, infer_kind_from_blob
from app.services.workflows.rk_meeting_playbook import (
    apply_rk_config,
    apply_rk_plan_runtime,
    is_rk_meeting_agent,
    rk_runtime_tools,
    rk_schedule_draft,
)
from app.services.workflows.service import _tools_for_published_plan
from app.services.workflows.plan_models import WorkflowPlan


def test_is_rk_meeting_agent() -> None:
    assert is_rk_meeting_agent("Подготовка заседаний Ревизионной комиссии")
    assert is_rk_meeting_agent("ПЛ-01-001 реестр поручений")
    assert not is_rk_meeting_agent("Подготовка заседаний Совета директоров", "ПЛ-34-242")


def test_rk_weekly_schedule() -> None:
    draft = rk_schedule_draft()
    triggers = draft["triggers"]
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger["weekdays"] == [0]
    assert trigger["window_start"] == "09:00"
    assert trigger["window_end"] == "10:00"
    assert trigger["once"] is False


def test_infer_revision_commission_kind() -> None:
    blob = "Подготовка заседаний Ревизионной комиссии ПЛ-01-001"
    assert infer_kind_from_blob(blob) == "revision_commission"
    tools = default_tools_for_kind("revision_commission")
    assert "onec.erp_tasks_current" in tools
    assert "workspace.powershell_run" in tools


def test_apply_rk_config_sets_schedule_and_tools() -> None:
    local = apply_rk_config({}, title="Ревизионной комиссии", notes="ПЛ-01-001")
    assert local.get("schedule_draft", {}).get("triggers")
    assert "onec.docflow_tasks" in (local.get("tools") or [])
    assert local.get("playbook", {}).get("steps")


def test_apply_rk_plan_runtime_includes_protocol_step() -> None:
    plan = apply_rk_plan_runtime(
        {"steps": []},
        title="Подготовка заседаний Ревизионной комиссии",
        notes="ПЛ-01-001",
    )
    steps = plan.get("steps") or []
    protocol = next((step for step in steps if step.get("entity") == "protocol"), None)
    assert protocol is not None
    assert protocol.get("title") == "Протоколы РК на проверку"
    assert "onec.meeting_protocols" in (plan.get("runtime") or {}).get("tools", [])


def test_tools_for_published_rk_agent() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "РК",
            "goal": "ПЛ-01-001",
            "runtime": {"kind": "revision_commission", "tools": []},
        }
    )
    row = Workflow(title="Подготовка заседаний Ревизионной комиссии", notes="§15")
    tools = _tools_for_published_plan(plan, row)
    assert "report.build_task_report" in tools
    assert "excel.read_workbook" in tools
