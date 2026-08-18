from app.services.local_mcp import list_tools
from app.services.workflows.cursor_tools import (
    invoke_creation_tool,
    required_live_tools_from_plan,
    should_run_tool_calls,
)
from app.services.workflows.plan_models import (
    OpenQuestion,
    PlanRuntime,
    PlanStep,
    WorkflowPlan,
)
from app.services.workflows.service import _tests_status_from_text


def test_should_run_tool_calls_despite_tests_fail() -> None:
    text = (
        "TESTS: FAIL — на Cloud VM нет BACKEND_URL\n\n"
        "```constructor_tool\n"
        '{"name": "turboproject", "arguments": {}}\n'
        "```\n"
    )
    calls = should_run_tool_calls(text, mode="execute")
    assert calls == [{"name": "turboproject", "arguments": {}}]


def test_required_live_tools_from_plan_turboproject() -> None:
    plan = WorkflowPlan(
        title="Реестр проектов",
        goal="Показать проекты",
        runtime=PlanRuntime(kind="turboproject"),
        steps=[PlanStep(id="s1", title="Список", action="вызови turboproject")],
        answered_questions=[
            OpenQuestion(id="q1", question="Откуда данные?", answer="TurboProject")
        ],
    )
    families = required_live_tools_from_plan(plan)
    assert "turboproject" in families


def test_vm_backend_url_fail_without_live_is_unknown() -> None:
    text = (
        "Тестовый прогон не завершён. На Cloud VM нет BACKEND_URL. TESTS: FAIL"
    )
    assert _tests_status_from_text(text, live_tools_ok=False) == "unknown"


def test_real_fail_stays_fail() -> None:
    text = "Constructor tool turboproject дважды вернул 401. TESTS: FAIL"
    assert _tests_status_from_text(text, live_tools_ok=False) == "fail"


def test_vm_fail_after_live_ok_stays_fail_or_pass() -> None:
    text = "Получил данные. На Cloud VM нет BACKEND_URL. TESTS: FAIL"
    assert _tests_status_from_text(text, live_tools_ok=True) == "fail"
    assert _tests_status_from_text("RESULT ok\nTESTS: PASS", live_tools_ok=True) == "pass"


def test_users_list_catalog_is_server() -> None:
    item = next(tool for tool in list_tools() if tool.get("name") == "users.list")
    assert item.get("execution") == "server"


def test_users_list_runs_on_server(monkeypatch) -> None:
    class _User:
        def model_dump(self, mode: str = "json") -> dict:
            return {"id": "u1", "fio": "Иванов", "position": "", "department": ""}

    class _Db:
        def close(self) -> None:
            return None

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: _Db())
    monkeypatch.setattr(
        "app.services.notifications.service.list_directory_users",
        lambda db, *, search="": [_User()],
    )
    result = invoke_creation_tool(tool="users.list", arguments={"query": "Ив"}, on_event=None)
    assert result["count"] == 1
    assert result["users"][0]["id"] == "u1"
