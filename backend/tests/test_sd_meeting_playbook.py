from __future__ import annotations

from app.models.workflow import Workflow
from app.services.workflow_tool_routing import default_tools_for_kind, infer_kind_from_blob, resolve_workflow_routing
from app.services.workflows.plan_models import WorkflowPlan
from app.services.workflows.meeting_agent_config import refresh_meeting_agent_view
from app.services.workflows.sd_meeting_playbook import (
    apply_sd_config,
    apply_sd_plan_runtime,
    is_sd_meeting_agent,
    sd_runtime_tools,
)
from app.services.workflows.service import _tools_for_published_plan


def test_is_sd_meeting_agent_detects_title() -> None:
    assert is_sd_meeting_agent("Подготовка заседаний Совета директоров")
    assert is_sd_meeting_agent("ПЛ-34-242 комплект материалов")
    assert not is_sd_meeting_agent("Еженедельный отчёт KPI")
    assert not is_sd_meeting_agent("Подготовка ПСД к рабочему дню и контроль календаря")
    assert not is_sd_meeting_agent("ИИ-агент: проверить SMART-формулировку поручения")


def test_infer_board_meeting_kind() -> None:
    blob = "Проверка комплекта заседания Совета директоров по ПЛ-34-242"
    assert infer_kind_from_blob(blob) == "board_meeting"
    tools = default_tools_for_kind("board_meeting", blob=blob)
    assert "onec.list_attachments" in tools
    assert "onec.meeting_protocols" in tools
    assert "outlook.read_calendar" in tools
    assert "report.export_document" in tools


def test_resolve_workflow_routing_for_sd_plan() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Подготовка заседаний Совета директоров",
            "goal": "Проверка комплекта по ПЛ-34-242",
            "runtime": {"kind": "board_meeting", "tools": sd_runtime_tools()},
        }
    )
    route = resolve_workflow_routing(plan)
    assert route.kind == "board_meeting"
    assert "onec.read_attachment" in route.tools


def test_tools_for_published_sd_agent() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Совет директоров",
            "goal": "ПЛ-34-242",
            "runtime": {"kind": "board_meeting", "tools": []},
        }
    )
    row = Workflow(title="Подготовка заседаний Совета директоров", notes="ПЛ-34-242 v03")
    tools = _tools_for_published_plan(plan, row)
    assert "excel.read_workbook" in tools
    assert "calendar.show_meetings" in tools
    assert "imap.search" not in tools
    assert "outlook.search_mail" not in sd_runtime_tools()


def test_apply_sd_config_patches_local_run() -> None:
    local = apply_sd_config({}, title="Подготовка заседаний Совета директоров", notes="ПЛ-34-242")
    assert local.get("playbook", {}).get("steps")
    assert "onec.list_attachments" in (local.get("tools") or [])


def test_apply_sd_plan_runtime_includes_protocol_step() -> None:
    plan = apply_sd_plan_runtime({"steps": []}, title="Подготовка заседаний Совета директоров", notes="")
    steps = plan.get("steps") or []
    protocol = next((step for step in steps if step.get("entity") == "protocol"), None)
    assert protocol is not None
    assert "onec.meeting_protocols" in (plan.get("runtime") or {}).get("tools", [])


def test_refresh_meeting_agent_view_merges_protocol_step() -> None:
    plan, local = refresh_meeting_agent_view(
        {"steps": [{"id": "old", "title": "Старый шаг"}]},
        {},
        title="Подготовка заседаний Совета директоров",
        notes="ПЛ-34-242",
    )
    assert any(step.get("entity") == "protocol" for step in plan.get("steps") or [])
    assert "onec.meeting_protocols" in (local.get("tools") or [])
