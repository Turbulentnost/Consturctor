from __future__ import annotations

from app.services.workflow_tool_routing import select_candidates
from app.services.workflows.playbook_validation import (
    attach_tool_candidates,
    normalize_assignment_steps,
)


def test_any_agent_assignment_step_uses_journal_not_user_tasks() -> None:
    draft = normalize_assignment_steps(
        {
            "goal": "Сверить поручения и при необходимости написать руководителю",
            "steps": [
                {
                    "id": "s1",
                    "title": "Открытые поручения АСТ00 заказчика",
                    "system": "onec",
                    "entity": "task",
                    "operation": "list",
                },
                {
                    "id": "s2",
                    "title": "Письмо руководителю",
                    "system": "outlook",
                    "entity": "mail_message",
                    "operation": "create",
                },
            ],
        }
    )
    assert draft["steps"][0]["entity"] == "assignment"
    assert "задачи исполнителя" in draft["steps"][0]["on_empty"]
    assert draft["steps"][1]["entity"] == "mail_message"
    assert draft["steps"][1].get("on_empty") is None


def test_attach_candidates_keeps_other_steps_and_assignment_tool() -> None:
    draft = attach_tool_candidates(
        {
            "steps": [
                {
                    "id": "s1",
                    "title": "Журнал поручений Action Tracker",
                    "system": "onec",
                    "entity": "task",
                    "operation": "list",
                    "done_when": "есть список",
                    "on_empty": "нет поручений",
                },
                {
                    "id": "s2",
                    "title": "Выгрузка в Excel",
                    "system": "desktop",
                    "entity": "spreadsheet",
                    "operation": "export",
                    "required_params": ["filename"],
                    "done_when": "есть файл",
                    "on_empty": "пустой файл",
                },
            ]
        }
    )
    first = draft["steps"][0]["tool_candidates"]
    second = draft["steps"][1]["tool_candidates"]
    assert first[0] == "onec.erp_assignments"
    assert "onec.erp_tasks_current" not in first
    assert "excel.create_workbook" in second


def test_generic_task_step_is_not_rewritten_to_assignment() -> None:
    names = select_candidates(
        {
            "system": "onec",
            "entity": "task",
            "operation": "list",
            "title": "Текущие задачи исполнителя",
            "data_expectation": "мои задачи erp_pm",
        }
    )
    assert "onec.erp_assignments" not in names
    draft = normalize_assignment_steps(
        {
            "steps": [
                {
                    "id": "s1",
                    "title": "Текущие задачи исполнителя",
                    "system": "onec",
                    "entity": "task",
                    "operation": "list",
                    "data_expectation": "мои задачи erp_pm",
                }
            ]
        }
    )
    assert draft["steps"][0]["entity"] == "task"
