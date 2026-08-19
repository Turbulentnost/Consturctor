"""TurboProject: сборка карточки проекта и регистрация инструмента."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.local_mcp import list_tools
from app.services.turboproject import (
    TOOL_NAME,
    build_overdue_milestones,
    build_overdue_tasks,
    build_project_payload,
    invoke_turboproject,
    unique_resource_names,
)


def test_tool_registered() -> None:
    names = {item["name"] for item in list_tools()}
    assert TOOL_NAME in names
    for item in list_tools():
        if item["name"] == TOOL_NAME:
            assert item.get("execution") == "server"
            assert "data_1c" in item.get("description", "")


def test_unique_resource_names_dedupes() -> None:
    assert unique_resource_names([" Иванов ", "иванов", "", None, "Петров"]) == [
        "Иванов",
        "Петров",
    ]


def test_overdue_tasks_skip_summary_and_done() -> None:
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    tasks = [
        {"id": 1, "is_summary": True, "finish_date": yesterday, "percent_complete": 0, "name": "сумма"},
        {"id": 2, "is_summary": False, "finish_date": yesterday, "percent_complete": 1, "name": "готова"},
        {
            "id": 3,
            "uid": 30,
            "is_summary": False,
            "finish_date": yesterday,
            "start_date": yesterday,
            "percent_complete": 0.4,
            "name": "просрочена",
            "assignments": [{"resource_name": "Иванов"}],
        },
        {"id": 4, "is_summary": False, "finish_date": tomorrow, "percent_complete": 0, "name": "ещё нет"},
    ]
    overdue = build_overdue_tasks(tasks)
    assert [item["id"] for item in overdue] == [3]
    assert overdue[0]["executors"] == ["Иванов"]


def test_overdue_milestones() -> None:
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    tasks = [
        {"id": 1, "is_milestone": True, "finish_date": yesterday, "percent_complete": 0, "name": "веха"},
        {"id": 2, "is_milestone": False, "finish_date": yesterday, "percent_complete": 0, "name": "задача"},
    ]
    assert [item["id"] for item in build_overdue_milestones(tasks)] == [1]


def test_build_project_payload() -> None:
    yesterday = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    payload = build_project_payload(
        {"id": 15, "original_name": "план.mpp", "uploaded_at": "2026-01-01T00:00:00"},
        {
            "project": {"name": "Реконструкция", "start_date": "2026-01-02", "plan_finish_1c": "2026-12-01"},
            "tasks": [
                {
                    "id": 9,
                    "uid": 90,
                    "name": "Поставка",
                    "is_summary": False,
                    "finish_date": yesterday,
                    "start_date": yesterday,
                    "percent_complete": 0,
                    "assignments": [{"resource_name": "Петров"}],
                }
            ],
            "resources": ["Петров", "Сидоров"],
            "data_1c": {"rukovoditel": "Иванов И.И.", "nomer_proekta": "ПР-1"},
        },
    )
    assert payload["file_id"] == 15
    assert payload["project_name"] == "Реконструкция"
    assert payload["dates"]["plan_finish_1c"] == "2026-12-01"
    assert payload["task_stats"]["overdue_tasks_count"] == 1
    assert payload["resources"] == ["Петров", "Сидоров"]
    assert payload["data_1c"]["rukovoditel"] == "Иванов И.И."


def test_invoke_stub_when_not_configured(monkeypatch) -> None:
    monkeypatch.setattr("app.services.turboproject.turboproject_configured", lambda: False)
    result = invoke_turboproject("turboproject", {"limit": 1})
    assert result["source"] == "stub"
    assert result["projects"] == []
    assert result["total_projects"] == 0
