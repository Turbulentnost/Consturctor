"""OData документооборота: URL, маппинг задач, без живого /doc."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.services.docflow_document_tasks import (
    fio_matches,
    map_document_executor_row,
    odata_executor_filter_clauses,
)
from app.services.docflow_tasks import (
    _credentials_from_args,
    _map_task,
    _parse_odata_dt,
    docflow_auth,
    docflow_base_url,
    docflow_env_auth,
    docflow_soap_ready,
    docflow_url_ready,
    handle_docflow_tasks,
    odata_entity,
)


def test_docflow_url_ready_without_env_user(monkeypatch) -> None:
    monkeypatch.setattr("app.tools.onec.dok_soap.soap_configured", lambda **_kwargs: True)
    monkeypatch.setattr("app.services.docflow_tasks.docflow_base_url", lambda: "")
    assert docflow_soap_ready() is True
    assert docflow_url_ready() is True


def test_fetch_inbox_tasks_soap_keeps_session_fio_not_soap_user(monkeypatch) -> None:
    from app.tools.onec import docflow_inbox_fetch

    captured: dict[str, object] = {}

    def fake_fetch(fio: str, **kwargs):
        captured["fio"] = fio
        captured.update(kwargs)
        return {"user_fio": fio, "rows": []}

    monkeypatch.setattr(docflow_inbox_fetch, "fetch_user_inbox_tasks", fake_fetch)
    monkeypatch.setattr(docflow_inbox_fetch, "map_inbox_payload", lambda _payload, *, fio: [])
    tasks, warning = docflow_inbox_fetch.fetch_inbox_tasks_soap(
        "Иванов И.И.",
        auth_args={"fio": "Иванов И.И.", "erp_login": "Иванов И.И.", "password": "secret", "erp_password": "secret"},
    )
    assert tasks == []
    assert warning == ""
    assert captured["fio"] == "Иванов И.И."
    assert captured.get("username") == "Иванов И.И."
    assert captured.get("password") == "secret"


def test_fetch_inbox_tasks_soap_session_alias_is_soap_user(monkeypatch) -> None:
    from app.tools.onec import docflow_inbox_fetch

    captured: dict[str, object] = {}

    def fake_fetch(fio: str, **kwargs):
        captured["fio"] = fio
        captured.update(kwargs)
        return {"user_fio": fio, "rows": []}

    monkeypatch.setattr(docflow_inbox_fetch, "fetch_user_inbox_tasks", fake_fetch)
    monkeypatch.setattr(docflow_inbox_fetch, "map_inbox_payload", lambda _payload, *, fio: [])
    docflow_inbox_fetch.fetch_inbox_tasks_soap(
        "Петров П.П.",
        auth_args={"erp_login": "Петров П.П.", "erp_password": "pw"},
    )
    assert captured["fio"] == "Петров П.П."
    assert captured.get("username") == "Петров П.П."
    assert captured.get("password") == "pw"


def test_fetch_inbox_tasks_soap_uses_session_login_first(monkeypatch) -> None:
    from app.tools.onec import docflow_inbox_fetch

    captured: dict[str, object] = {}

    def fake_fetch(fio: str, **kwargs):
        captured["fio"] = fio
        captured.update(kwargs)
        return {"user_fio": fio, "rows": []}

    monkeypatch.setattr(docflow_inbox_fetch, "fetch_user_inbox_tasks", fake_fetch)
    monkeypatch.setattr(docflow_inbox_fetch, "map_inbox_payload", lambda _payload, *, fio: [])
    docflow_inbox_fetch.fetch_inbox_tasks_soap(
        "Иванов Иван Иванович",
        auth_args={
            "fio": "Иванов Иван Иванович",
            "session_login": "Иванов И.И.",
            "username": "i.ivanov",
            "password": "typed-secret",
        },
    )
    assert captured.get("username") == "Иванов И.И."
    assert captured.get("password") == "typed-secret"


def test_fetch_inbox_tasks_soap_does_not_fallback_to_service_account(monkeypatch) -> None:
    from app.tools.onec import docflow_inbox_fetch

    calls: list[tuple[str | None, str | None]] = []

    def fake_fetch(fio: str, **kwargs):
        user = kwargs.get("username")
        secret = kwargs.get("password")
        calls.append((user if isinstance(user, str) or user is None else str(user), secret if isinstance(secret, str) or secret is None else str(secret)))
        raise RuntimeError("HTTP 401: Документооборот отклонил Basic-учётку")

    monkeypatch.setattr(docflow_inbox_fetch, "fetch_user_inbox_tasks", fake_fetch)
    tasks, warning = docflow_inbox_fetch.fetch_inbox_tasks_soap(
        "Иванов И.И.",
        auth_args={
            "fio": "Иванов И.И.",
            "username": "i.ivanov",
            "password": "typed-secret",
        },
    )
    assert tasks == []
    assert "экрана входа" in warning
    assert "Иванов И.И." in warning
    assert "i.ivanov" in warning
    assert all(secret == "typed-secret" for _user, secret in calls)
    assert (None, None) not in calls


def test_fetch_inbox_tasks_soap_retries_latin_after_401(monkeypatch) -> None:
    from app.tools.onec import docflow_inbox_fetch

    calls: list[tuple[str | None, str | None]] = []

    def fake_fetch(fio: str, **kwargs):
        user = kwargs.get("username")
        secret = kwargs.get("password")
        calls.append((user if isinstance(user, str) or user is None else str(user), secret if isinstance(secret, str) or secret is None else str(secret)))
        if user == "Иванов И.И.":
            raise RuntimeError("HTTP 401: Документооборот отклонил Basic-учётку")
        return {"user_fio": fio, "rows": []}

    monkeypatch.setattr(docflow_inbox_fetch, "fetch_user_inbox_tasks", fake_fetch)
    monkeypatch.setattr(docflow_inbox_fetch, "map_inbox_payload", lambda _payload, *, fio: [{"title": "ok"}])
    tasks, warning = docflow_inbox_fetch.fetch_inbox_tasks_soap(
        "Иванов И.И.",
        auth_args={
            "fio": "Иванов И.И.",
            "username": "i.ivanov",
            "password": "secret",
        },
    )
    assert warning == ""
    assert tasks == [{"title": "ok"}]
    assert calls[0] == ("Иванов И.И.", "secret")
    assert calls[1] == ("i.ivanov", "secret")


def test_fetch_inbox_tasks_soap_missing_creds_asks_reconnect(monkeypatch) -> None:
    from app.tools.onec import docflow_inbox_fetch

    tasks, warning = docflow_inbox_fetch.fetch_inbox_tasks_soap(
        "Иванов И.И.",
        auth_args={"fio": "Иванов И.И."},
    )
    assert tasks == []
    assert "Войдите с паролем 1С" in warning
    assert "DOK_HTTP_USER" not in warning
    assert "DOK_HTTP_PASSWORD" not in warning


def test_docflow_auth_prefers_session_fio_password(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.docflow_tasks.settings",
        SimpleNamespace(
            docflow_odata_username="env-user",
            docflow_odata_password="env-pass",
            odata_username="odata-only",
            odata_password="odata-pass",
            erp_login="",
            erp_password="",
        ),
    )
    assert docflow_env_auth() == ("env-user", "env-pass")
    assert docflow_auth({"fio": "Иванов И.И.", "password": "secret"}) == (
        "Иванов И.И.",
        "secret",
    )
    assert docflow_auth(
        {"username": "name_mail_slug", "fio": "Иванов И.И.", "password": "secret"}
    ) == ("Иванов И.И.", "secret")
    assert _credentials_from_args({"username": "u", "erp_password": "p"}) == ("u", "p")


def test_docflow_env_auth_falls_back_to_odata_when_no_docflow_or_erp(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.docflow_tasks.settings",
        SimpleNamespace(
            docflow_odata_username="",
            docflow_odata_password="",
            odata_username="odata-only",
            odata_password="odata-pass",
            erp_login="",
            erp_password="",
        ),
    )
    assert docflow_env_auth() == ("odata-only", "odata-pass")


def test_docflow_base_url_from_erp(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.docflow_tasks.settings",
        SimpleNamespace(docflow_odata_base_url="", odata_base_url="http://host/erp_pm/odata/standard.odata"),
    )
    assert docflow_base_url() == "http://host/doc/odata/standard.odata"


def test_docflow_base_url_explicit(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.docflow_tasks.settings",
        SimpleNamespace(
            docflow_odata_base_url="http://host/doc/odata/standard.odata/",
            odata_base_url="http://host/erp_pm/odata/standard.odata",
        ),
    )
    assert docflow_base_url() == "http://host/doc/odata/standard.odata"


def test_parse_odata_dt_skips_empty() -> None:
    assert _parse_odata_dt("") is None
    assert _parse_odata_dt("0001-01-01T00:00:00") is None
    parsed = _parse_odata_dt("2026-08-17T12:00:00")
    assert parsed == datetime(2026, 8, 17, 12, 0, 0)


def test_odata_entity_and_executor_filters() -> None:
    assert odata_entity() == "Task_ЗадачаИсполнителя"
    clauses = odata_executor_filter_clauses("41290a43-1111-2222-3333-444455556666")
    assert len(clauses) == 1
    assert "Исполнитель eq cast(guid'" in clauses[0][0]


def test_fio_matches_executor_column() -> None:
    assert fio_matches("Жалыбин Максим Дмитриевич", "Жалыбин Максим Дмитриевич")
    assert fio_matches("  жалыбин   максим  ", "Жалыбин Максим")


def test_map_document_executor_row_subject_and_action() -> None:
    row = {
        "Number": "DO-12",
        "Description": "Исполнить",
        "ПредметСтрокой": "Заявка в службу развития…",
        "Executed": False,
        "СрокИсполнения": "2025-09-15T00:00:00",
        "Исполнитель_Name": "Жалыбин Максим Дмитриевич",
    }
    item = map_document_executor_row(row, fio="Жалыбин Максим Дмитриевич")
    assert "Заявка в службу развития" in item["title"]
    assert "Исполнить" in item["title"]
    assert item["due_at"].startswith("2025-09-15")
    assert item["performer"] == "Жалыбин Максим Дмитриевич"


def test_list_docflow_tasks_uses_soap_not_odata(monkeypatch) -> None:
    from app.services import docflow_tasks

    called = {"odata": 0}

    def _forbidden_get(*_args, **_kwargs):
        called["odata"] += 1
        raise AssertionError("OData не должен вызываться для задач ДО")

    monkeypatch.setattr(docflow_tasks, "_get", _forbidden_get)
    monkeypatch.setattr(
        "app.tools.onec.docflow_inbox_fetch.fetch_inbox_tasks_soap",
        lambda fio, **_kwargs: (
            [
                {
                    "number": "do-1",
                    "title": "Согласовать",
                    "source": "документооборот",
                    "done": False,
                    "created_at": "2026-09-01 10:00:00",
                    "due_at": "2026-09-10 18:00:00",
                    "performer": fio,
                }
            ],
            "",
        ),
    )
    rows = docflow_tasks.list_docflow_tasks(
        fio="Иванов И.И.",
        only_open=True,
        limit=20,
        today_and_overdue=True,
    )
    assert called["odata"] == 0
    assert len(rows) == 1
    assert rows[0]["title"] == "Согласовать"


def test_handle_docflow_tasks_forwards_session_password(monkeypatch) -> None:
    from app.services import docflow_tasks

    captured: dict[str, object] = {}

    def fake_soap(fio, **kwargs):
        captured["fio"] = fio
        captured.update(kwargs)
        return [], ""

    monkeypatch.setattr(docflow_tasks, "_get", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.tools.onec.docflow_inbox_fetch.fetch_inbox_tasks_soap", fake_soap)
    handle_docflow_tasks(
        {
            "fio": "Иванов И.И.",
            "erp_login": "Иванов И.И.",
            "password": "secret",
            "erp_password": "secret",
            "today_and_overdue": True,
            "only_open": True,
        },
        actor_fio="Иванов И.И.",
    )
    auth = captured.get("auth_args")
    assert isinstance(auth, dict)
    assert auth["fio"] == "Иванов И.И."
    assert auth["password"] == "secret"
    assert auth["erp_password"] == "secret"


def test_handle_docflow_tasks_keeps_both_roles_and_warning(monkeypatch) -> None:
    from app.services import docflow_tasks

    monkeypatch.setattr(docflow_tasks, "_get", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        "app.tools.onec.docflow_inbox_fetch.fetch_inbox_tasks_soap",
        lambda fio, **_kwargs: (
            [
                {
                    "number": "to-me",
                    "title": "Мне",
                    "source": "документооборот",
                    "role": "executor",
                    "channel": "soap",
                    "author": "Петров П.П.",
                    "performer": fio,
                    "done": False,
                    "due_at": "2026-09-10 18:00:00",
                    "created_at": "2026-09-01 10:00:00",
                },
                {
                    "number": "from-me",
                    "title": "От меня",
                    "source": "документооборот (от меня)",
                    "role": "author",
                    "channel": "soap",
                    "author": fio,
                    "performer": "Петров П.П.",
                    "done": False,
                    "due_at": "2026-09-10 18:00:00",
                    "created_at": "2026-09-01 10:00:00",
                },
                {
                    "number": "both",
                    "title": "Оба",
                    "source": "документооборот (от меня)",
                    "role": "both",
                    "channel": "soap",
                    "author": fio,
                    "performer": fio,
                    "done": False,
                    "due_at": "2026-09-10 18:00:00",
                    "created_at": "2026-09-01 10:00:00",
                },
            ],
            "SOAP: частичное предупреждение",
        ),
    )
    payload = handle_docflow_tasks(
        {"today_and_overdue": True, "only_open": True, "limit": 20},
        actor_fio="Иванов И.И.",
    )
    assert payload["count"] == 3
    assert {row["role"] for row in payload["tasks"]} == {"executor", "author", "both"}
    assert payload["docflow_warning"] == "SOAP: частичное предупреждение"
    assert payload["tasks"][1]["source"] == "документооборот (от меня)"


def test_list_docflow_today_and_overdue_drops_future(monkeypatch) -> None:
    from app.services import docflow_tasks

    monkeypatch.setattr(docflow_tasks, "_get", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        "app.tools.onec.docflow_inbox_fetch.fetch_inbox_tasks_soap",
        lambda fio, **_kwargs: (
            [
                {
                    "number": "late",
                    "title": "Просрочена",
                    "done": False,
                    "due_at": "2026-09-10 18:00:00",
                    "created_at": "2026-09-01 10:00:00",
                },
                {
                    "number": "future",
                    "title": "Потом",
                    "done": False,
                    "due_at": "2026-12-01 18:00:00",
                    "created_at": "2026-09-01 10:00:00",
                },
            ],
            "",
        ),
    )
    rows = docflow_tasks.list_docflow_tasks(
        fio="Иванов И.И.",
        only_open=True,
        today_and_overdue=True,
        limit=20,
    )
    assert [row["title"] for row in rows] == ["Просрочена"]


def test_list_docflow_for_people_does_not_require_odata(monkeypatch) -> None:
    from app.services import docflow_tasks

    monkeypatch.setattr(docflow_tasks, "docflow_base_url", lambda: "")
    monkeypatch.setattr(
        docflow_tasks,
        "list_docflow_tasks",
        lambda **kwargs: [{"number": "1", "title": kwargs["fio"], "source": "документооборот"}],
    )
    extra, warning = docflow_tasks.list_docflow_for_people(["Петров П.П."], only_open=True)
    assert warning == ""
    assert extra["Петров П.П."][0]["title"] == "Петров П.П."


def test_map_task_marks_source_and_late() -> None:
    row = {
        "Number": "38",
        "Description": "Исполнить задачу №2",
        "Executed": False,
        "Date": "2026-08-10T09:00:00",
        "СрокИсполнения": "2026-08-12T18:00:00",
        "ДатаИсполнения": "",
        "Описание": "протокол",
        "СостояниеБизнесПроцесса": "",
    }
    item = _map_task(row, fio="Мангасарян Давид Каренович")
    assert item["source"] == "документооборот"
    assert item["done"] is False
    assert item["late"] is False
    assert item["title"] == "Исполнить задачу №2"
    assert item["performer"] == "Мангасарян Давид Каренович"

    done = dict(row)
    done["Executed"] = True
    done["ДатаИсполнения"] = "2026-08-13T10:00:00"
    late = _map_task(done, fio="X")
    assert late["done"] is True
    assert late["late"] is True
