from __future__ import annotations

from app.models.workflow import Workflow
from app.services.workflow_tool_routing import default_tools_for_kind, infer_kind_from_blob
from app.services.workflows.calendar_control_playbook import (
    PSD_CHAIRMAN_FIO,
    apply_calendar_control_config,
    apply_calendar_control_plan_runtime,
    calendar_control_schedule_draft,
    is_calendar_control_agent,
)
from app.services.workflows.meeting_agent_config import refresh_meeting_agent_view
from app.services.workflows.plan_models import WorkflowPlan
from app.services.workflows.service import _tools_for_published_plan


def test_is_calendar_control_agent() -> None:
    assert is_calendar_control_agent("Подготовка ПСД к рабочему дню и контроль календаря")
    assert is_calendar_control_agent("ИИ-агент: контроль календаря ПСД")
    assert not is_calendar_control_agent("Подготовка заседаний Совета директоров", "ПЛ-34-242")
    assert not is_calendar_control_agent("Подготовка заседаний Ревизионной комиссии", "ПЛ-01-001")
    assert not is_calendar_control_agent("Проверка артефактов и предложение поручений к закрытию")


def test_calendar_control_schedule_has_morning_and_evening() -> None:
    triggers = calendar_control_schedule_draft()["triggers"]
    assert len(triggers) == 2
    windows = {item["window_start"] for item in triggers}
    assert windows == {"08:30", "16:00"}
    assert all(item["weekdays"] == [0, 1, 2, 3, 4] for item in triggers)
    assert all(item["once"] is False for item in triggers)


def test_infer_calendar_control_kind() -> None:
    blob = "Подготовка ПСД к рабочему дню и контроль календаря"
    assert infer_kind_from_blob(blob) == "calendar_control"
    tools = default_tools_for_kind("calendar_control", blob=blob)
    assert "outlook.read_calendar" in tools
    assert "users.current" in tools
    assert "outlook.create_event" in tools
    assert "imap.search" not in tools


def test_apply_calendar_control_config_sets_chairman() -> None:
    local = apply_calendar_control_config(
        {},
        title="Подготовка ПСД к рабочему дню и контроль календаря",
        notes="Устный список",
    )
    instructions = str(local.get("playbook", {}).get("instructions") or "")
    assert PSD_CHAIRMAN_FIO in instructions
    assert "people=" in instructions
    assert local.get("schedule_draft", {}).get("triggers")
    assert "outlook.read_calendar" in (local.get("tools") or [])
    steps = local.get("playbook", {}).get("steps") or []
    assert any(step.get("tool") == "outlook.read_calendar" for step in steps)


def test_apply_calendar_control_plan_runtime() -> None:
    plan = apply_calendar_control_plan_runtime(
        {"steps": []},
        title="Подготовка ПСД к рабочему дню и контроль календаря",
        notes="",
    )
    assert (plan.get("runtime") or {}).get("kind") == "calendar_control"
    assert any(step.get("tool") == "users.current" for step in plan.get("steps") or [])


def test_refresh_meeting_agent_view_calendar_control() -> None:
    plan, local = refresh_meeting_agent_view(
        {"steps": [{"id": "old", "title": "Старый шаг"}]},
        {},
        title="Подготовка ПСД к рабочему дню и контроль календаря",
        notes="Календарь ПСД",
    )
    assert any(step.get("tool") == "outlook.read_calendar" for step in plan.get("steps") or [])
    assert PSD_CHAIRMAN_FIO in str(local.get("playbook", {}).get("instructions") or "")


def test_tools_for_published_calendar_agent() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Календарь ПСД",
            "goal": "Контроль календаря",
            "runtime": {"kind": "calendar_control", "tools": []},
        }
    )
    row = Workflow(title="Подготовка ПСД к рабочему дню и контроль календаря", notes="")
    tools = _tools_for_published_plan(plan, row)
    assert "calendar.show_meetings" in tools
    assert "users.list" in tools
    assert "imap.search" not in tools
