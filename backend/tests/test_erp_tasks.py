"""Задачи пользователя из erp_pm: даты 1С, JWT-актор, регистрация инструментов."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.clients.erp_sql import ErpOrgDept, ErpSubordinate, ErpUserProfile
from app.core.jwt import create_access_token
from app.services.erp_tasks import (
    actor_from_args,
    actor_from_jwt,
    build_subordinate_task_tree,
    from_1c_datetime,
    list_org_subordinates,
    merge_task_lists,
    parse_date,
    task_is_late,
    to_1c_datetime,
    _looks_like_1c_user_id,
    resolve_actor,
    ErpTaskError,
)
from app.services.local_mcp import list_tools
from app.services.onec_tools import ONEC_TOOLS, invoke_onec


def test_1c_datetime_offset() -> None:
    raw = datetime(4026, 8, 14, 12, 30, 0)
    human = from_1c_datetime(raw)
    assert human == datetime(2026, 8, 14, 12, 30, 0)
    assert to_1c_datetime(human) == raw
    assert from_1c_datetime(datetime(2001, 1, 1)) is None
    assert from_1c_datetime(datetime(2026, 8, 14)) == datetime(2026, 8, 14)


def test_task_is_late_needs_both_dates() -> None:
    due = datetime(2026, 8, 1, 12, 0, 0)
    done_late = datetime(2026, 8, 2, 9, 0, 0)
    done_on_time = datetime(2026, 8, 1, 11, 0, 0)
    assert task_is_late(done=True, completed_at=done_late, due_at=due)
    assert not task_is_late(done=True, completed_at=done_on_time, due_at=due)
    assert not task_is_late(done=False, completed_at=done_late, due_at=due)
    assert not task_is_late(done=True, completed_at=None, due_at=due)
    assert not task_is_late(done=True, completed_at=done_late, due_at=None)


def test_parse_date_formats() -> None:
    assert parse_date("2026-08-01") == datetime(2026, 8, 1)
    end = parse_date("2026-08-01", end=True)
    assert end == datetime(2026, 8, 1, 23, 59, 59)
    assert parse_date("01.08.2026").date().isoformat() == "2026-08-01"
    try:
        parse_date("")
        raise AssertionError("expected ErpTaskError")
    except ErpTaskError:
        pass


def test_actor_from_args_prefers_explicit_then_jwt() -> None:
    assert actor_from_args({}, actor_fio="Иванов И.И.", actor_user_id="u1") == (
        "Иванов И.И.",
        "u1",
    )
    assert actor_from_args(
        {"fio": "Петров П.П.", "user_id": "1c-id"},
        actor_fio="Иванов И.И.",
        actor_user_id="u1",
    ) == ("Петров П.П.", "1c-id")


def test_constructor_uuid_is_not_1c_id() -> None:
    assert not _looks_like_1c_user_id("fdc038c1-73f5-45e4-880c-d1ee4e3f5d02")
    assert _looks_like_1c_user_id("A1B2C3D4E5F60718293A4B5C6D7E8F90")
    assert not _looks_like_1c_user_id("")


def test_resolve_actor_uses_fio_when_jwt_id_is_constructor(monkeypatch) -> None:
    called = {"by_id": 0, "by_fio": 0}

    def fake_by_id(_user_id: str):
        called["by_id"] += 1
        raise AssertionError("Constructor UUID must not query v8users by id")

    def fake_by_fio(fio: str):
        called["by_fio"] += 1
        return SimpleNamespace(fio=fio, id="1CUSER")

    monkeypatch.setattr("app.clients.erp_sql.find_user_by_id", fake_by_id)
    monkeypatch.setattr("app.clients.erp_sql.find_user_by_fio", fake_by_fio)
    fio, user_id = resolve_actor(
        fio="Иванов Иван Иванович",
        user_id="fdc038c1-73f5-45e4-880c-d1ee4e3f5d02",
    )
    assert fio == "Иванов Иван Иванович"
    assert user_id == "1CUSER"
    assert called == {"by_id": 0, "by_fio": 1}


def test_tools_registered() -> None:
    assert "onec.erp_tasks_current" in ONEC_TOOLS
    assert "onec.erp_tasks_period" in ONEC_TOOLS
    assert "onec.erp_subordinate_tasks" in ONEC_TOOLS
    assert "onec.docflow_tasks" in ONEC_TOOLS
    names = {item["name"] for item in list_tools()}
    assert "onec.meeting_service_notes" in names
    meeting = next(item for item in list_tools() if item["name"] == "onec.meeting_service_notes")
    assert meeting.get("execution") == "server"
    assert meeting.get("entity") == "service_note"
    assert meeting.get("runtime") != "com32"
    search = next(item for item in list_tools() if item["name"] == "onec.search_documents")
    assert search.get("runtime") == "com32"
    assert "users.subordinates" in names
    assert "onec.erp_tasks_current" in names
    assert "onec.erp_tasks_period" in names
    assert "onec.erp_subordinate_tasks" in names
    assert "onec.docflow_tasks" in names
    for item in list_tools():
        if item["name"] in {
            "onec.erp_tasks_current",
            "onec.erp_tasks_period",
            "onec.erp_subordinate_tasks",
            "onec.docflow_tasks",
            "onec.meeting_service_notes",
        }:
            assert item.get("execution") == "server"


def test_list_org_subordinates_from_erp_without_constructor(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.erp_tasks.resolve_actor",
        lambda **_kwargs: ("Руководитель Сектора", ""),
    )
    monkeypatch.setattr(
        "app.services.erp_tasks.erp_sql.load_subordinate_org",
        lambda _fio: (
            ErpUserProfile(fio="Руководитель Сектора", position="Руководитель", department="Сектор"),
            [],
            [
                ErpSubordinate(
                    fio="Незарегистрированный Иванов",
                    position="Инженер",
                    department="Сектор",
                )
            ],
        ),
    )
    result = list_org_subordinates(fio="Руководитель Сектора")
    assert result["ok"] is True
    assert result["source"] == "erp_pm"
    assert result["count"] == 1
    assert result["users"][0]["fio"] == "Незарегистрированный Иванов"
    assert result["users"][0]["source"] == "erp_pm"
    assert "id" not in result["users"][0]


def test_invoke_current_uses_jwt_actor(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.onec_tools._erp_sql_ready",
        lambda: False,
    )
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: False)
    result = invoke_onec(
        "onec.erp_tasks_current",
        {"limit": 5},
        actor_user_id="app-user",
        actor_fio="Сидоров С.С.",
    )
    assert result["source"] == "stub"
    assert result["fio"] == "Сидоров С.С."
    assert result["count"] == 0


def test_invoke_period_uses_jwt_and_dates(monkeypatch) -> None:
    monkeypatch.setattr("app.services.onec_tools._erp_sql_ready", lambda: True)
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: False)
    monkeypatch.setattr(
        "app.services.erp_tasks.list_tasks_for_period",
        lambda **kwargs: {
            "summary": "ok",
            "fio": kwargs["fio"],
            "user_id": kwargs["user_id"],
            "date_from": kwargs["date_from"],
            "date_to": kwargs["date_to"],
            "count": 0,
            "tasks": [],
            "source": "erp_pm",
        },
    )
    result = invoke_onec(
        "onec.erp_tasks_period",
        {"date_from": "2026-08-01", "date_to": "2026-08-17"},
        actor_fio="Иванов И.И.",
    )
    assert result["source"] == "erp_pm"
    assert result["fio"] == "Иванов И.И."
    assert result["date_from"] == "2026-08-01"


def test_actor_from_jwt_uses_access_token() -> None:
    token = create_access_token(
        user_id="u-1",
        fio="Мангасарян Давид Каренович",
        department="Сектор ИИ",
        position="Руководитель сектора",
    )
    fio, user_id = actor_from_jwt(
        {"access_token": token},
        actor_fio="Другой",
        actor_user_id="other",
    )
    assert fio == "Мангасарян Давид Каренович"
    assert user_id == "u-1"


def test_actor_from_jwt_rejects_bad_token() -> None:
    try:
        actor_from_jwt({"jwt": "not-a-token"}, actor_fio="Иванов")
        raise AssertionError("expected ErpTaskError")
    except ErpTaskError as exc:
        assert "JWT" in str(exc)


def test_actor_from_jwt_falls_back_to_session() -> None:
    assert actor_from_jwt({}, actor_fio="Сидоров С.С.", actor_user_id="app") == (
        "Сидоров С.С.",
        "app",
    )


def test_subordinate_task_tree_nests_people_and_due_dates() -> None:
    manager = ErpUserProfile(
        fio="Соломичева Светлана Викторовна",
        department="Служба развития",
        position="Начальник службы развития",
    )
    parent = ErpOrgDept(
        id="A",
        name="Служба развития",
        parent_id="PARENT",
        is_root=True,
        head_fio="Соломичева Светлана Викторовна",
    )
    child = ErpOrgDept(
        id="B",
        name="Сектор по внедрению искусственного интеллекта",
        parent_id="A",
        is_root=False,
        head_fio="Мангасарян Давид Каренович",
    )
    people = [
        ErpSubordinate(
            fio="Гарипова Екатерина Сергеевна",
            position="Начальник службы развития",
            department="Служба развития",
        ),
        ErpSubordinate(
            fio="Мангасарян Давид Каренович",
            position="Руководитель сектора",
            department="Сектор по внедрению искусственного интеллекта",
        ),
        ErpSubordinate(
            fio="Давлетов Руслан Игоревич",
            position="Промпт-инженер 1 категории",
            department="Сектор по внедрению искусственного интеллекта",
        ),
    ]
    tasks = {
        "Мангасарян Давид Каренович": [
            {
                "number": "1",
                "title": "План сектора",
                "due_at": "2026-08-20 18:00:00",
                "created_at": "2026-08-10 10:00:00",
                "status": "открыта",
            }
        ],
        "Давлетов Руслан Игоревич": [
            {
                "number": "2",
                "title": "Проверить промпт",
                "due_at": "2026-08-18 12:00:00",
                "created_at": "2026-08-11 09:00:00",
                "status": "открыта",
            }
        ],
        "Гарипова Екатерина Сергеевна": [],
    }
    tree = build_subordinate_task_tree(
        manager=manager,
        departments=[parent, child],
        people=people,
        tasks_by_fio=tasks,
    )
    assert [node["fio"] for node in tree] == [
        "Мангасарян Давид Каренович",
        "Гарипова Екатерина Сергеевна",
    ]
    assert tree[0]["level"] == 1
    assert tree[0]["position"] == "Руководитель сектора"
    assert tree[0]["tasks"][0]["due_at"] == "2026-08-20 18:00:00"
    assert tree[0]["subordinates"][0]["fio"] == "Давлетов Руслан Игоревич"
    assert tree[0]["subordinates"][0]["level"] == 2
    assert tree[0]["subordinates"][0]["tasks"][0]["due_at"] == "2026-08-18 12:00:00"
    assert tree[1]["subordinates"] == []


def test_invoke_subordinate_tasks_uses_jwt_actor(monkeypatch) -> None:
    monkeypatch.setattr("app.services.onec_tools._erp_sql_ready", lambda: False)
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: False)
    result = invoke_onec(
        "onec.erp_subordinate_tasks",
        {},
        actor_user_id="app-user",
        actor_fio="Мангасарян Давид Каренович",
    )
    assert result["source"] == "stub"
    assert result["manager"]["fio"] == "Мангасарян Давид Каренович"
    assert result["tree"] == []
    assert "erp_since" in result


def test_invoke_subordinate_tasks_real_path(monkeypatch) -> None:
    monkeypatch.setattr("app.services.onec_tools._erp_sql_ready", lambda: True)
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: False)
    monkeypatch.setattr(
        "app.services.erp_tasks.list_subordinate_tasks",
        lambda **kwargs: {
            "summary": "ok",
            "manager": {"fio": kwargs["fio"], "position": "Руководитель сектора"},
            "subordinate_count": 1,
            "task_count": 2,
            "tree": [],
            "source": "erp_pm",
        },
    )
    token = create_access_token(user_id="u-1", fio="Мангасарян Давид Каренович")
    result = invoke_onec(
        "onec.erp_subordinate_tasks",
        {"access_token": token, "limit_per_person": 10},
        actor_fio="Другой",
    )
    assert result["source"] == "erp_pm"
    assert result["manager"]["fio"] == "Мангасарян Давид Каренович"


def test_merge_task_lists_keeps_sources_apart() -> None:
    erp = [{"number": "1", "title": "ERP", "source": "erp_pm", "due_at": ""}]
    doc = [
        {"number": "1", "title": "DOC", "source": "документооборот", "due_at": ""},
        {"number": "1", "title": "DOC dup", "source": "документооборот", "due_at": ""},
    ]
    merged = merge_task_lists(erp, doc, limit=10)
    assert len(merged) == 2
    assert merged[0]["source"] == "erp_pm"
    assert merged[1]["title"] == "DOC"


def test_invoke_docflow_stub(monkeypatch) -> None:
    monkeypatch.setattr("app.services.onec_tools._erp_sql_ready", lambda: False)
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: False)
    monkeypatch.setattr("app.services.docflow_tasks.docflow_configured", lambda: False)
    result = invoke_onec(
        "onec.docflow_tasks",
        {},
        actor_user_id="app-user",
        actor_fio="Сидоров С.С.",
    )
    assert result["source"] == "stub"
    assert result["fio"] == "Сидоров С.С."
    assert result["count"] == 0
