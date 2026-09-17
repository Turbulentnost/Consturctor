from __future__ import annotations

from app.models.workflow import Workflow
from app.services.workflows.plan_models import WorkflowPlan
from app.services.workflows.service import _tools_for_published_plan
from app.services.workflows.tool_whitelist import collect_runtime_whitelist


def test_whitelist_from_draft_steps_not_domain_pack() -> None:
    local = {
        "playbook": {
            "tools": ["users.current", "excel.list_files"],
            "steps": [
                {"id": "s1", "tool_candidates": ["users.current"]},
                {"id": "s2", "tool": "onec.erp_assignments"},
                {"id": "s3", "tool_candidates": ["onec.erp_assignments_write"]},
            ],
        },
        "live_tools_invoked": ["users.current", "read", "glob", "onec.erp_assignments"],
        "tools": [
            "onec.odata_get",
            "onec.sql_query",
            "turboproject",
            "users.current",
        ],
    }

    names = collect_runtime_whitelist(local=local)

    assert names == [
        "users.current",
        "excel.list_files",
        "onec.erp_assignments",
        "onec.erp_assignments_write",
        "office.read_file",
    ]
    assert "onec.odata_get" not in names
    assert "read" not in names


def test_whitelist_falls_back_to_stored_when_playbook_empty() -> None:
    names = collect_runtime_whitelist(local={"tools": ["outlook.read_calendar", "notify.send"]})
    assert names == ["outlook.read_calendar", "notify.send"]


def test_published_plan_prefers_playbook_whitelist() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Ежедневный контроль поручений по 1С ERP и Excel",
            "goal": "Сверка журнала",
            "runtime": {"kind": "onec"},
        }
    )
    row = Workflow(
        id="wf-at",
        user_id="user-1",
        title=plan.title,
        notes="Action Tracker xlsx и 1С ERP",
        plan_json=plan.to_dict(),
        local_run={
            "playbook": {
                "tools": ["users.current", "onec.erp_assignments", "excel.read_workbook"],
                "steps": [
                    {"tool_candidates": ["users.current"]},
                    {"tool_candidates": ["onec.erp_assignments", "onec.erp_assignments_write"]},
                    {"tool_candidates": ["excel.read_workbook", "excel.edit_workbook"]},
                ],
            }
        },
    )

    tools = _tools_for_published_plan(plan, row)

    assert "onec.erp_assignments" in tools
    assert "onec.erp_assignments_write" in tools
    assert "excel.edit_workbook" in tools
    assert "office.read_file" in tools
    assert "onec.odata_get" not in tools
    assert "onec.sql_query" not in tools
    assert "turboproject" not in tools
