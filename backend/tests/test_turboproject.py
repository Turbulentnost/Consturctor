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
    is_phrase_query,
    is_project_name_query,
    list_projects,
    unique_resource_names,
)
from app.services.workflows.cursor_tools import (
    build_tool_envelope,
    format_tool_inputs,
    step_candidates_block,
    tool_catalog_block,
)
from app.services.workflows.tool_result_validation import evaluate_tool_result


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


def test_build_project_payload_clips_long_overdue_lists() -> None:
    yesterday = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    tasks = [
        {
            "id": index,
            "uid": index,
            "name": f"просрочка {index}",
            "is_summary": False,
            "is_milestone": index % 2 == 0,
            "finish_date": yesterday,
            "percent_complete": 0,
            "assignments": [{"resource_name": f"Исполнитель {index}"}],
        }
        for index in range(1, 25)
    ]
    payload = build_project_payload(
        {"id": 1, "original_name": "план.mpp"},
        {"project": {"name": "Большой"}, "tasks": tasks, "resources": [f"Р{n}" for n in range(40)]},
    )
    assert payload["task_stats"]["overdue_tasks_count"] == 24
    assert payload["task_stats"]["overdue_milestones_count"] == 12
    assert len(payload["overdue_tasks"]) == 8
    assert len(payload["overdue_milestones"]) == 8
    assert len(payload["resources"]) == 20


def test_invoke_stub_when_not_configured(monkeypatch) -> None:
    monkeypatch.setattr("app.services.turboproject.turboproject_configured", lambda: False)
    result = invoke_turboproject("turboproject", {"limit": 1})
    assert result["source"] == "stub"
    assert result["projects"] == []
    assert result["total_projects"] == 0


def test_phrase_query_is_not_a_project_name() -> None:
    phrase = (
        "активные проекты участники Мангасарян Давид Каренович, "
        "Жалыбин Максим Дмитриевич, Комарькова Анастасия Эдуардовна"
    )
    assert is_phrase_query(phrase)
    assert not is_project_name_query(phrase)
    assert is_project_name_query("Реконструкция")
    assert is_project_name_query("ПР-001")
    assert not is_phrase_query("Реконструкция")


def test_list_projects_ignores_phrase_query() -> None:
    result = list_projects(
        {
            "query": (
                "активные проекты участники Мангасарян Давид Каренович, "
                "Жалыбин Максим Дмитриевич"
            )
        }
    )
    assert result["projects"] == []
    assert "не фраза" in result["summary"]


def test_tool_envelope_splits_received_and_inputs() -> None:
    phrase = "активные проекты участники Иванов Иван Иванович, Петров Пётр Петрович"
    envelope = build_tool_envelope("turboproject", {"query": phrase, "unknown": 1})
    assert envelope["received"]["query"] == phrase
    assert "query" not in envelope["accepted"]
    assert "unknown" in envelope["ignored"]
    assert "query" in envelope["ignored"]
    assert "query" in envelope["inputs"]
    assert "manager" in envelope["inputs"]
    assert "фраза" in envelope["inputs"]["query"]
    assert all(key in envelope["inputs"] for key in envelope["accepted"])


def test_tool_envelope_keeps_project_name_query() -> None:
    envelope = build_tool_envelope("turboproject", {"query": "Реконструкция", "limit": 5})
    assert envelope["accepted"]["query"] == "Реконструкция"
    assert envelope["accepted"]["limit"] == 5
    assert "query" not in envelope["ignored"]


def test_users_list_envelope_ignores_generic_query() -> None:
    envelope = build_tool_envelope("users.list", {"query": "получатели"})
    assert "query" not in envelope["accepted"]
    assert envelope["ignored"]["query"]
    assert "query" in envelope["inputs"]


def test_empty_result_with_ignored_query_is_suspect() -> None:
    envelope = build_tool_envelope(
        "turboproject",
        {"query": "активные проекты участники Иванов Иван Иванович"},
    )
    verdict = evaluate_tool_result(
        step={"system": "turboproject", "operation": "search"},
        name="turboproject",
        arguments={"query": "активные проекты участники Иванов Иван Иванович"},
        result={"projects": [], "summary": "query не применён"},
        ignored=envelope["ignored"],
    )
    assert verdict.data_status == "empty_suspect"
    assert not verdict.accepted
    assert "inputs" in verdict.next_action


def test_every_tool_input_has_description() -> None:
    for item in list_tools():
        schema = item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key, spec in props.items():
            assert isinstance(spec, dict), item["name"]
            desc = str(spec.get("description") or "").strip()
            assert desc, f"{item['name']}.{key}"
            assert desc != f"поле {key}", f"{item['name']}.{key} без описания"


def test_prompt_shows_inputs_for_candidates() -> None:
    catalog = tool_catalog_block()
    assert "входы:" in catalog
    assert "query" in catalog
    block = step_candidates_block(
        {"steps": [{"id": "s3", "tool_candidates": ["turboproject"]}]}
    )
    assert "turboproject" in block
    assert "входы:" in block
    assert "не фраза" in format_tool_inputs("turboproject")
    assert "arguments: {}" in format_tool_inputs("users.current")
