from __future__ import annotations

from app.models.workflow import Workflow
from app.services.workflows.daily_assignment_playbook import (
    apply_daily_assignment_config,
    daily_assignment_runtime_tools,
    is_daily_assignment_agent,
)
from app.services.workflows.meeting_agent_config import apply_meeting_agent_config
from app.services.workflows.plan_models import WorkflowPlan
from app.services.workflows.service import _tools_for_published_plan


def test_is_daily_assignment_agent() -> None:
    assert is_daily_assignment_agent("Ежедневный контроль поручений по 1С ERP и Excel")
    assert is_daily_assignment_agent("Ежедневный контроль поручений АСТ00 и Action Tracker")
    assert not is_daily_assignment_agent("Еженедельный отчёт по поручениям")
    assert not is_daily_assignment_agent("Проверка артефактов и предложение поручений к закрытию")
    assert not is_daily_assignment_agent("Подготовка заседаний Совета директоров")


def test_apply_config_lists_all_assignments_and_psd_protocols() -> None:
    local = apply_daily_assignment_config(
        {},
        title="Ежедневный контроль поручений по 1С ERP и Excel",
        notes="Action Tracker",
    )
    playbook = local.get("playbook") or {}
    steps = {step["id"]: step for step in playbook.get("steps") or []}
    assign = steps["s4"]["proven_call"]["arguments"]
    assert assign["include_all"] is True
    assert assign["only_open"] is False
    proto = steps["s5"]["proven_call"]["arguments"]
    assert proto["psd_mark"] is True
    assert proto["review_only"] is False
    assert proto["include_closed"] is True
    assert steps["s5"]["tool"] == "onec.meeting_protocols"
    assert "psd_mark=true" in playbook.get("instructions", "").casefold()
    assert "include_all=true" in playbook.get("instructions", "")
    assert "onec.meeting_protocols" in (local.get("tools") or [])
    assert "excel.write_action_tracker" in (local.get("tools") or [])
    assert "excel.edit_workbook" not in (local.get("tools") or [])
    assert "excel.read_workbook" not in (local.get("tools") or [])
    assert "office.read_file" not in (local.get("tools") or [])
    assert steps["s6"]["tool"] == "excel.write_action_tracker"


def test_meeting_config_applies_daily_assignment() -> None:
    local = apply_meeting_agent_config(
        {},
        title="Ежедневный контроль поручений по 1С ERP и Excel",
        notes="",
    )
    tools = local.get("tools") or []
    assert tools == daily_assignment_runtime_tools()
    assert "outlook.read_calendar" not in tools


def test_tools_for_published_daily_assignment_agent() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Ежедневный контроль поручений по 1С ERP и Excel",
            "goal": "сверка журнала",
            "runtime": {"kind": "onec", "tools": []},
        }
    )
    row = Workflow(title="Ежедневный контроль поручений по 1С ERP и Excel", notes="Action Tracker")
    tools = _tools_for_published_plan(plan, row)
    assert tools == daily_assignment_runtime_tools()
    assert "onec.meeting_protocols" in tools
