from __future__ import annotations

from app.models.workflow import Workflow
from app.services.workflow_tool_routing import default_tools_for_kind, infer_kind_from_blob
from app.services.workflows.artifact_close_playbook import (
    apply_artifact_close_config,
    artifact_close_runtime_tools,
    is_artifact_close_agent,
)
from app.services.workflows.meeting_agent_config import apply_meeting_agent_config
from app.services.workflows.plan_models import WorkflowPlan
from app.services.workflows.rk_meeting_playbook import is_rk_meeting_agent
from app.services.workflows.service import _tools_for_published_plan


def test_is_artifact_close_agent() -> None:
    assert is_artifact_close_agent("Проверка артефактов и предложение поручений к закрытию")
    assert is_artifact_close_agent("Проверка артефактов и предложение к закрытию поручений")
    assert not is_artifact_close_agent("Подготовка заседаний Ревизионной комиссии")


def test_rk_path_in_notes_does_not_steal_artifact_agent() -> None:
    title = "Проверка артефактов и предложение поручений к закрытию"
    notes = r"\\192.168.1.198\Files\24.Ревизионная комиссия\Отдел\10. Секретарь РК"
    assert is_artifact_close_agent(title, notes)
    assert not is_rk_meeting_agent(title, notes)
    assert infer_kind_from_blob(f"{title} {notes}") == "assignment_artifacts"


def test_apply_config_clears_run_inputs_and_locks_journal_tools() -> None:
    local = apply_artifact_close_config(
        {"playbook": {"run_inputs": [{"id": "registry", "required": True}]}},
        title="Проверка артефактов и предложение поручений к закрытию",
        notes="п. 6.4.5",
    )
    playbook = local.get("playbook") or {}
    assert playbook.get("run_inputs") == []
    tools = local.get("tools") or []
    assert "onec.erp_assignments" in tools
    assert "onec.download_artifact" in tools
    assert "office.read_file" in tools
    assert "outlook.read_calendar" not in tools
    assert "workspace.powershell_run" not in tools
    steps = playbook.get("steps") or []
    assert steps[1]["tool"] == "onec.erp_assignments"
    assert steps[1]["proven_call"]["arguments"]["include_files"] is True
    assert "не подготовка заседания рк" in playbook.get("instructions", "").casefold()
    assert "по одному file_id" in playbook.get("instructions", "").casefold()


def test_meeting_config_prefers_artifact_over_rk() -> None:
    local = apply_meeting_agent_config(
        {},
        title="Проверка артефактов и предложение поручений к закрытию",
        notes=r"Ищи реестр в \\192.168.1.198\Files\24.Ревизионная комиссия",
    )
    assert (local.get("playbook") or {}).get("run_inputs") == []
    assert "onec.erp_assignments" in (local.get("tools") or [])
    assert "workspace.powershell_run" not in (local.get("tools") or [])


def test_tools_for_published_artifact_agent() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Проверка артефактов и предложение поручений к закрытию",
            "goal": "сверить файлы и решить о закрытии",
            "runtime": {"kind": "assignment_artifacts", "tools": []},
        }
    )
    row = Workflow(title="Проверка артефактов и предложение поручений к закрытию", notes="")
    tools = _tools_for_published_plan(plan, row)
    assert tools == artifact_close_runtime_tools()
    assert "report.export_document" in default_tools_for_kind("assignment_artifacts")
