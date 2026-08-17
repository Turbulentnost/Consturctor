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
    parse_date,
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
    names = {item["name"] for item in list_tools()}
    assert "onec.erp_tasks_current" in names
    assert "onec.erp_tasks_period" in names
    assert "onec.erp_subordinate_tasks" in names
    for item in list_tools():
        if item["name"] in {
            "onec.erp_tasks_current",
            "onec.erp_tasks_period",
            "onec.erp_subordinate_tasks",
        }:
            assert item.get("execution") == "server"


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
        fio="Мангасарян Давид Каренович",
        department="Сектор по внедрению искусственного интеллекта",
        position="Руководитель сектора",
    )
    parent = ErpOrgDept(
        id="A",
        name="Сектор по внедрению искусственного интеллекта",
        parent_id="PARENT",
        is_root=True,
    )
    child = ErpOrgDept(id="B", name="Группа разметки", parent_id="A", is_root=False)
    people = [
        ErpSubordinate(
            fio="Давлетов Руслан Игоревич",
            position="Промпт-инженер 1 категории",
            department="Сектор по внедрению искусственного интеллекта",
        ),
        ErpSubordinate(
            fio="Петров Сергей Сергеевич",
            position="Промпт-инженер",
            department="Группа разметки",
        ),
    ]
    tasks = {
        "Давлетов Руслан Игоревич": [
            {
                "number": "1",
                "title": "Проверить промпт",
                "due_at": "2026-08-20 18:00:00",
                "created_at": "2026-08-10 10:00:00",
                "status": "открыта",
            }
        ],
        "Петров Сергей Сергеевич": [],
    }
    tree = build_subordinate_task_tree(
        manager=manager,
        departments=[parent, child],
        people=people,
        tasks_by_fio=tasks,
    )
    assert len(tree) == 1
    assert tree[0]["department"] == "Сектор по внедрению искусственного интеллекта"
    assert tree[0]["people"][0]["fio"] == "Давлетов Руслан Игоревич"
    assert tree[0]["people"][0]["position"] == "Промпт-инженер 1 категории"
    assert tree[0]["people"][0]["tasks"][0]["due_at"] == "2026-08-20 18:00:00"
    assert tree[0]["children"][0]["department"] == "Группа разметки"
    assert tree[0]["children"][0]["people"][0]["fio"] == "Петров Сергей Сергеевич"


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
