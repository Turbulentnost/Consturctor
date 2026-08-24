"""TurboProject: сборка карточки проекта и регистрация инструмента."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.local_mcp import list_tools
from app.services.turboproject import (
    GET_TOOL_NAME,
    GET_BLOCKED_TASKS_TOOL_NAME,
    GET_OVERDUE_PROJECTS_TOOL_NAME,
    GET_PORTFOLIO_SUMMARY_TOOL_NAME,
    GET_PROJECT_METRICS_TOOL_NAME,
    GET_PROJECT_TASKS_TOOL_NAME,
    GET_PROJECT_TOOL_NAME,
    LIST_TOOL_NAME,
    SEARCH_PROJECTS_TOOL_NAME,
    TOOL_NAME,
    TURBOPROJECT_TOOLS,
    build_overdue_milestones,
    build_overdue_tasks,
    get_overdue_projects,
    get_project,
    get_project_card,
    get_project_portfolio_summary,
    get_project_tasks,
    build_project_payload,
    invoke_turboproject,
    is_phrase_query,
    is_project_name_query,
    list_project_index,
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
    assert TURBOPROJECT_TOOLS <= names
    for item in list_tools():
        if item["name"] == TOOL_NAME:
            assert item.get("execution") == "server"
            assert "turboproject.search_projects" in item.get("description", "")


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


def test_project_index_does_not_read_cards(monkeypatch) -> None:
    calls: list[str] = []

    def fake_api_get(path: str, _token: str) -> dict:
        calls.append(path)
        assert path == "/api/projects/files"
        return {
            "items": [
                {
                    "id": 10,
                    "original_name": "А.mpp",
                    "uploaded_at": "2026-01-01T00:00:00",
                    "has_1c": True,
                },
                {"id": 11, "original_name": "Б.mpp", "has_1c": False},
            ]
        }

    monkeypatch.setattr("app.services.turboproject._login", lambda: "token")
    monkeypatch.setattr("app.services.turboproject._api_get", fake_api_get)

    result = list_project_index({"limit": 50})

    assert calls == ["/api/projects/files"]
    assert result["mode"] == "index"
    assert result["projects"] == [
        {
            "file_id": 10,
            "original_name": "А.mpp",
            "uploaded_at": "2026-01-01T00:00:00",
            "has_1c": True,
            "project_name": "А.mpp",
            "dates": {
                "start_date": None,
                "finish_date": None,
                "actual_finish_date": None,
                "baseline_start": None,
                "baseline_finish": None,
                "plan_finish_1c": None,
            },
            "data_1c": {},
        }
    ]


def test_project_get_reads_single_card(monkeypatch) -> None:
    calls: list[str] = []

    def fake_api_get(path: str, _token: str) -> dict:
        calls.append(path)
        assert path == "/api/projects/files/10"
        return {
            "file": {"original_name": "А.mpp", "uploaded_at": "2026-01-01T00:00:00"},
            "project": {"name": "Проект А"},
            "tasks": [],
            "data_1c": {"nomer_proekta": "ПР-10"},
        }

    monkeypatch.setattr("app.services.turboproject._login", lambda: "token")
    monkeypatch.setattr("app.services.turboproject._api_get", fake_api_get)

    result = get_project_card({"file_id": 10})

    assert calls == ["/api/projects/files/10"]
    assert result["mode"] == "card"
    assert result["projects"][0]["project_name"] == "Проект А"
    assert result["projects"][0]["data_1c"]["nomer_proekta"] == "ПР-10"


def test_search_projects_does_not_read_cards(monkeypatch) -> None:
    calls: list[str] = []

    def fake_api_get(path: str, _token: str) -> dict:
        calls.append(path)
        assert path == "/api/projects/files"
        return {
            "items": [
                {
                    "id": 10,
                    "original_name": "А.mpp",
                    "uploaded_at": "2026-01-01T00:00:00",
                    "has_1c": True,
                    "data_1c": {
                        "status_proekta": "Активный",
                        "rukovoditel": "Иванов",
                        "podrazdelenie": "ИТ",
                    },
                },
                {
                    "id": 11,
                    "original_name": "Б.mpp",
                    "has_1c": True,
                    "data_1c": {"status_proekta": "Закрыт", "rukovoditel": "Петров"},
                },
            ]
        }

    monkeypatch.setattr("app.services.turboproject._login", lambda: "token")
    monkeypatch.setattr("app.services.turboproject._api_get", fake_api_get)

    result = invoke_turboproject(SEARCH_PROJECTS_TOOL_NAME, {"status": "Активный", "limit": 1})

    assert calls == ["/api/projects/files"]
    assert result["mode"] == "search"
    assert result["matched_projects_count"] == 1
    assert [item["file_id"] for item in result["projects"]] == [10]
    assert "next_cursor" in result


def test_get_project_reads_one_card_and_selects_fields(monkeypatch) -> None:
    calls: list[str] = []

    def fake_api_get(path: str, _token: str) -> dict:
        calls.append(path)
        assert path == "/api/projects/files/10"
        return {
            "file": {"id": 10, "original_name": "А.mpp", "uploaded_at": "2026-01-01T00:00:00"},
            "project": {"name": "Проект А", "finish_date": "2026-02-01"},
            "tasks": [],
            "resources": ["Иванов"],
            "data_1c": {"rukovoditel": "Иванов", "nomer_proekta": "ПР-10"},
        }

    monkeypatch.setattr("app.services.turboproject._login", lambda: "token")
    monkeypatch.setattr("app.services.turboproject._api_get", fake_api_get)

    result = get_project({"project_id": 10, "fields": ["identity", "data_1c"]})

    assert calls == ["/api/projects/files/10"]
    assert result["mode"] == "project"
    project = result["projects"][0]
    assert project["project_name"] == "Проект А"
    assert project["data_1c"]["nomer_proekta"] == "ПР-10"
    assert "resources" not in project
    assert "dates" not in project


def test_get_project_tasks_filters_overdue_status_assignee_and_paginates(monkeypatch) -> None:
    yesterday = (datetime.now() - timedelta(days=3)).date().isoformat()
    tomorrow = (datetime.now() + timedelta(days=3)).date().isoformat()

    def fake_api_get(path: str, _token: str) -> dict:
        assert path == "/api/projects/files/10"
        return {
            "tasks": [
                {
                    "id": 1,
                    "name": "Сводная",
                    "is_summary": True,
                    "finish_date": yesterday,
                    "percent_complete": 0,
                },
                {
                    "id": 2,
                    "name": "Просрочена",
                    "is_summary": False,
                    "finish_date": yesterday,
                    "percent_complete": 0.5,
                    "assignments": [{"resource_name": "Иванов"}],
                },
                {
                    "id": 3,
                    "name": "Не просрочена",
                    "is_summary": False,
                    "finish_date": tomorrow,
                    "percent_complete": 0,
                    "assignments": [{"resource_name": "Иванов"}],
                },
                {
                    "id": 4,
                    "name": "Другой исполнитель",
                    "is_summary": False,
                    "finish_date": yesterday,
                    "percent_complete": 0,
                    "assignments": [{"resource_name": "Петров"}],
                },
            ]
        }

    monkeypatch.setattr("app.services.turboproject._login", lambda: "token")
    monkeypatch.setattr("app.services.turboproject._api_get", fake_api_get)

    result = get_project_tasks(
        {
            "project_id": 10,
            "status": "open",
            "assignee": "Иванов",
            "overdue_only": True,
            "limit": 1,
        }
    )

    assert result["mode"] == "tasks"
    assert result["matched_tasks_count"] == 1
    assert [item["id"] for item in result["tasks"]] == [2]
    assert result["next_cursor"] == ""


def test_get_overdue_projects_sorts_by_delay_days(monkeypatch) -> None:
    old_date = (datetime.now() - timedelta(days=20)).date().isoformat()
    recent_date = (datetime.now() - timedelta(days=5)).date().isoformat()

    def fake_api_get(path: str, _token: str) -> dict:
        if path == "/api/projects/files":
            return {
                "items": [
                    {"id": 10, "original_name": "Старый.mpp", "has_1c": True},
                    {"id": 11, "original_name": "Новый.mpp", "has_1c": True},
                ]
            }
        if path == "/api/projects/files/10":
            return {
                "file": {"id": 10, "original_name": "Старый.mpp"},
                "project": {"name": "Старый", "finish_date": old_date},
                "tasks": [{"id": 1, "name": "T", "finish_date": old_date, "percent_complete": 0}],
            }
        if path == "/api/projects/files/11":
            return {
                "file": {"id": 11, "original_name": "Новый.mpp"},
                "project": {"name": "Новый", "finish_date": recent_date},
                "tasks": [{"id": 2, "name": "T", "finish_date": recent_date, "percent_complete": 0}],
            }
        raise AssertionError(path)

    monkeypatch.setattr("app.services.turboproject._login", lambda: "token")
    monkeypatch.setattr("app.services.turboproject._api_get", fake_api_get)

    result = get_overdue_projects({"limit": 2})

    assert result["mode"] == "overdue_projects"
    assert [item["project_id"] for item in result["projects"]] == [10, 11]
    assert result["projects"][0]["delay_days"] >= result["projects"][1]["delay_days"]


def test_get_project_portfolio_summary_groups_by_status_department_owner(monkeypatch) -> None:
    def fake_api_get(path: str, _token: str) -> dict:
        assert path == "/api/projects/files"
        return {
            "items": [
                {
                    "id": 10,
                    "original_name": "А.mpp",
                    "has_1c": True,
                    "data_1c": {
                        "status_proekta": "Активный",
                        "podrazdelenie": "ИТ",
                        "rukovoditel": "Иванов",
                    },
                },
                {
                    "id": 11,
                    "original_name": "Б.mpp",
                    "has_1c": True,
                    "data_1c": {
                        "status_proekta": "Активный",
                        "podrazdelenie": "ИТ",
                        "rukovoditel": "Петров",
                    },
                },
                {
                    "id": 12,
                    "original_name": "В.mpp",
                    "has_1c": True,
                    "data_1c": {
                        "status_proekta": "Закрыт",
                        "podrazdelenie": "Финансы",
                        "rukovoditel": "Иванов",
                    },
                },
            ]
        }

    monkeypatch.setattr("app.services.turboproject._login", lambda: "token")
    monkeypatch.setattr("app.services.turboproject._api_get", fake_api_get)

    by_status = get_project_portfolio_summary({"group_by": "status"})
    by_department = get_project_portfolio_summary({"group_by": "department"})
    by_owner = get_project_portfolio_summary({"group_by": "owner"})

    assert by_status["groups"][0]["status"] == "Активный"
    assert by_status["groups"][0]["projects_count"] == 2
    assert by_department["groups"][0]["department"] == "ИТ"
    assert by_owner["groups"][0]["owner"] == "Иванов"
    assert by_owner["groups"][0]["projects_count"] == 2


def test_api_catalog_contains_new_turboproject_names() -> None:
    expected = {
        TOOL_NAME,
        LIST_TOOL_NAME,
        GET_TOOL_NAME,
        SEARCH_PROJECTS_TOOL_NAME,
        GET_PROJECT_TOOL_NAME,
        GET_PROJECT_TASKS_TOOL_NAME,
        GET_PROJECT_METRICS_TOOL_NAME,
        GET_OVERDUE_PROJECTS_TOOL_NAME,
        GET_BLOCKED_TASKS_TOOL_NAME,
        GET_PORTFOLIO_SUMMARY_TOOL_NAME,
    }
    names = {item["name"] for item in list_tools()}
    assert expected <= names


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
