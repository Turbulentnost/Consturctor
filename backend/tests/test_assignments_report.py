from datetime import datetime

from app.models.workflow import Workflow
from app.services.assignments_report import (
    assignments_mode,
    criticality_for_task,
    is_assignments_workflow,
    task_implies_assignments,
    tracking_assessment_for_task,
)


def test_criticality_overdue() -> None:
    crit = criticality_for_task(
        {"title": "Подготовить отчёт", "due_at": "2020-01-01 12:00:00"},
        now=datetime(2026, 6, 1),
    )
    assert crit["level"] == "overdue"


def test_criticality_low() -> None:
    crit = criticality_for_task(
        {"title": "Длинная формулировка поручения с деталями", "due_at": "2026-12-01 12:00:00"},
        now=datetime(2026, 6, 1),
    )
    assert crit["level"] == "low"


def test_task_implies_assignments_from_generic_task() -> None:
    task = (
        "Выполни рабочую задачу агента «ИИ-агент: проверить SMART-формулировку поручения» "
        "по правилам из его плана и покажи понятный результат."
    )
    assert task_implies_assignments(task)


def test_is_assignments_workflow_reads_passport_title() -> None:
    wf = Workflow(
        id="wf-smart",
        title="regulation.docx",
        plan_json={},
        local_run={"passport_title": "проверить SMART-формулировку поручения"},
    )
    assert is_assignments_workflow(wf)


def test_is_assignments_workflow_empty_plan_with_task() -> None:
    wf = Workflow(id="wf-empty", title="regulation.docx", plan_json={})
    task = "Проверь SMART-формулировку поручения и сохрани Excel"
    assert is_assignments_workflow(wf, task=task)


def test_assignments_mode_defaults_to_smart() -> None:
    wf = Workflow(
        id="wf-at",
        title="regulation.docx",
        plan_json={},
        local_run={"passport_title": "проверить SMART-формулировку поручения"},
    )
    assert assignments_mode(wf) == "smart"


def test_tracking_assessment_flags_missing_artifacts() -> None:
    track = tracking_assessment_for_task(
        {
            "title": "Подготовить отчёт",
            "status": "выполнена",
            "due_at": "2026-12-01 12:00:00",
            "attachments": [],
        },
        now=datetime(2026, 6, 1),
    )
    assert track["state"] == "Риск"
    assert "артефакт" in track["issues"].casefold()
