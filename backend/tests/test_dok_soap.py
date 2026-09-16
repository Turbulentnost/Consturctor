"""HTTP SOAP inbox документооборота: разбор XML и маппинг без живого /doc."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from app.tools.onec.docflow_inbox_map import map_inbox_row
import pytest

from datetime import date

from app.tools.onec.dok_soap import (
    CHANNEL_SOAP,
    DokConfig,
    ROLE_AUTHOR,
    ROLE_BOTH,
    ROLE_EXECUTOR,
    SOURCE_FROM_ME,
    SOURCE_INBOX,
    envelope,
    is_today_or_overdue,
    load_config,
    normalize_person,
    object_id_value,
    parse_tasks,
    parse_users,
    performer_value,
    slice_dump_for_user,
    soap_configured,
    soap_timeout_message,
    task_role_for_user,
)


def _soap(inner: str) -> ET.Element:
    return ET.fromstring(envelope(inner))


def test_parse_users_from_dm_list() -> None:
    root = _soap(
        '<dm:return xmlns:dm="http://www.1c.ru/dm" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:type="dm:DMGetObjectListResponse">'
        "<dm:items><dm:object>"
        "<dm:name>Жалыбин Максим Дмитриевич</dm:name>"
        "<dm:objectID><dm:id>user-1</dm:id><dm:type>DMUser</dm:type></dm:objectID>"
        "</dm:object></dm:items>"
        "</dm:return>"
    )
    users = parse_users(root)
    assert users == [
        {"name": "Жалыбин Максим Дмитриевич", "id": "user-1", "type": "DMUser"}
    ]


def test_parse_tasks_and_map_inbox_row() -> None:
    root = _soap(
        '<dm:return xmlns:dm="http://www.1c.ru/dm" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dm:items><dm:object>"
        "<dm:name>Исполнить</dm:name>"
        "<dm:objectID><dm:id>task-9</dm:id><dm:type>DMBusinessProcessTask</dm:type></dm:objectID>"
        "<dm:performer><dm:user><dm:name>Комарькова Анастасия Эдуардовна</dm:name></dm:user></dm:performer>"
        "<dm:author><dm:name>Жалыбин Максим Дмитриевич</dm:name></dm:author>"
        "<dm:beginDate>2026-09-01T10:00:00</dm:beginDate>"
        "<dm:dueDate>2026-09-10T18:00:00</dm:dueDate>"
        "<dm:executed>false</dm:executed>"
        "<dm:businessProcessStep>Исполнение</dm:businessProcessStep>"
        "<dm:number>ДО-17</dm:number>"
        "<dm:description>Подготовить презентацию для клиента</dm:description>"
        "<dm:target><dm:name>Служебная записка</dm:name>"
        "<dm:objectID><dm:id>doc-1</dm:id></dm:objectID></dm:target>"
        "</dm:object></dm:items>"
        "</dm:return>"
    )
    rows = parse_tasks(root)
    assert len(rows) == 1
    assert rows[0]["id"] == "task-9"
    assert rows[0]["performer"] == "Комарькова Анастасия Эдуардовна"
    assert rows[0]["executed"] is False
    mapped = map_inbox_row(rows[0], fio="Комарькова Анастасия Эдуардовна")
    assert mapped["title"] == "Подготовить презентацию для клиента"
    assert mapped["number"] == "ДО-17"
    assert mapped["source"] == SOURCE_INBOX
    assert mapped["author"] == "Жалыбин Максим Дмитриевич"
    assert mapped["performer"] == "Комарькова Анастасия Эдуардовна"
    assert mapped["role"] == ROLE_EXECUTOR
    assert mapped["channel"] == CHANNEL_SOAP
    assert mapped["created_at"].startswith("2026-09-01")
    assert mapped["due_at"].startswith("2026-09-10")
    assert mapped["ref_key"] == "task-9"
    assert mapped["done"] is False


def test_map_inbox_row_author_and_both_roles() -> None:
    author_row = {
        "id": "from-me",
        "number": "ДО-2",
        "description": "Проверить отчёт",
        "author": "Иванов И.И.",
        "performer": "Петров П.П.",
        "executed": False,
        "due": "2026-09-10T18:00:00",
        "begin": "2026-09-01T10:00:00",
    }
    mapped_author = map_inbox_row(author_row, fio="Иванов И.И.")
    assert mapped_author["role"] == ROLE_AUTHOR
    assert mapped_author["source"] == SOURCE_FROM_ME
    assert mapped_author["channel"] == CHANNEL_SOAP
    assert mapped_author["author"] == "Иванов И.И."
    assert mapped_author["performer"] == "Петров П.П."

    both_row = {
        **author_row,
        "id": "both",
        "performer": "Иванов И.И.",
        "role": ROLE_BOTH,
    }
    mapped_both = map_inbox_row(both_row, fio="Иванов И.И.")
    assert mapped_both["role"] == ROLE_BOTH
    assert mapped_both["source"] == SOURCE_FROM_ME
    assert mapped_both["performer"] == "Иванов И.И."


def test_slice_dump_for_user_performer_and_author() -> None:
    dump = {
        "endpoint": "http://host/doc/ws/dm.1cws",
        "rows": [
            {
                "id": "to-me",
                "performer": "Иванов И.И.",
                "author": "Петров П.П.",
                "executed": False,
                "due": "2026-09-10T18:00:00",
            },
            {
                "id": "from-me",
                "performer": "Сидоров С.С.",
                "author": "Иванов И.И.",
                "executed": False,
                "due": "2026-09-10T18:00:00",
            },
            {
                "id": "both",
                "performer": "Иванов И.И.",
                "author": "иванов и.и.",
                "executed": False,
                "due": "2026-09-10T18:00:00",
            },
            {
                "id": "other",
                "performer": "Петров П.П.",
                "author": "Сидоров С.С.",
                "executed": False,
                "due": "2026-09-10T18:00:00",
            },
        ],
    }
    sliced = slice_dump_for_user(dump, "Иванов И.И.")
    by_id = {row["id"]: row["role"] for row in sliced["rows"]}
    assert by_id == {"to-me": ROLE_EXECUTOR, "from-me": ROLE_AUTHOR, "both": ROLE_BOTH}
    assert sliced["count"] == 3
    assert task_role_for_user(dump["rows"][3], "Иванов И.И.") is None


def test_slice_dump_dedupes_repeated_task_id() -> None:
    dump = {
        "rows": [
            {
                "id": "dup-1",
                "number": "00001",
                "performer": "Иванов И.И.",
                "author": "Петров П.П.",
                "executed": False,
                "due": "2026-09-10T18:00:00",
            },
            {
                "id": "dup-1",
                "number": "00001",
                "performer": "Иванов И.И.",
                "author": "Петров П.П.",
                "executed": False,
                "due": "2026-09-10T18:00:00",
            },
        ],
    }
    sliced = slice_dump_for_user(dump, "Иванов И.И.")
    assert sliced["count"] == 1


def test_normalize_person_yo_and_spaces() -> None:
    assert normalize_person("Комарькова  Анастасия") == normalize_person("комарькова анастасия")
    assert normalize_person("Ёлкин") == normalize_person("елкин")


def test_is_today_or_overdue() -> None:
    today = date(2026, 9, 16)
    assert is_today_or_overdue(
        {"executed": False, "due": "2026-09-16T18:00:00"}, today=today
    )
    assert is_today_or_overdue(
        {"executed": False, "due": "2026-09-10T10:00:00"}, today=today
    )
    assert not is_today_or_overdue(
        {"executed": False, "due": "2026-09-17T10:00:00"}, today=today
    )
    assert not is_today_or_overdue(
        {"executed": True, "due": "2026-09-10T10:00:00"}, today=today
    )
    assert is_today_or_overdue(
        {"executed": False, "due": "", "begin": "2026-09-16T09:00:00"}, today=today
    )
    assert not is_today_or_overdue(
        {"executed": False, "due": "0001-01-01T00:00:00", "begin": "2026-08-01T09:00:00"},
        today=today,
    )


def test_object_id_value_and_timeout_message() -> None:
    xml = object_id_value("user-1", "DMUser")
    assert 'xsi:type="dm:DMObjectID"' in xml
    assert "<dm:id>user-1</dm:id>" in xml
    assert "<dm:type>DMUser</dm:type>" in xml
    assert soap_timeout_message(45) == "Документооборот SOAP: нет ответа за 45 с"
    executor = performer_value({"id": "user-1", "name": "Иванов И.И.", "type": "DMUser"})
    assert 'xsi:type="dm:DMBusinessProcessTaskExecutor"' in executor
    assert "<dm:id>user-1</dm:id>" in executor
    assert "Иванов И.И." in executor


def _isolate_dok_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.onec import dok_soap

    monkeypatch.setattr(dok_soap, "discover_env_files", lambda _explicit: [])
    monkeypatch.setattr(dok_soap, "_settings_mapping", lambda: {})
    for key in (
        "DOK_HTTP_SERVER",
        "DOK_HTTP_PORT",
        "DOK_HTTP_USER",
        "DOK_HTTP_PASSWORD",
        "DOK_HTTP_TIMEOUT",
        "DOK_HTTP_BASE_PATH",
        "DOCFLOW_ODATA_USERNAME",
        "DOCFLOW_ODATA_PASSWORD",
        "ODATA_USERNAME",
        "ODATA_PASSWORD",
        "ERP_LOGIN",
        "ERP_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_config_session_fio_password_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    config = load_config(username="Иванов И.И.", password="secret")
    assert config.user == "Иванов И.И."
    assert config.password == "secret"


def test_load_config_session_wins_over_dok_http(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    monkeypatch.setenv("DOK_HTTP_USER", "env-user")
    monkeypatch.setenv("DOK_HTTP_PASSWORD", "env-pass")
    config = load_config()
    assert config.user == "env-user"
    assert config.password == "env-pass"
    session = load_config(username="Иванов И.И.", password="secret")
    assert session.user == "Иванов И.И."
    assert session.password == "secret"


def test_load_config_fallback_docflow_odata(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    monkeypatch.setenv("DOCFLOW_ODATA_USERNAME", "doc-user")
    monkeypatch.setenv("DOCFLOW_ODATA_PASSWORD", "doc-pass")
    config = load_config()
    assert config.user == "doc-user"
    assert config.password == "doc-pass"


def test_load_config_fallback_odata(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    monkeypatch.setenv("ODATA_USERNAME", "odata-user")
    monkeypatch.setenv("ODATA_PASSWORD", "odata-pass")
    config = load_config()
    assert config.server == "192.168.2.229"
    assert config.port == 81
    assert config.user == "odata-user"
    assert config.password == "odata-pass"


def test_load_config_fallback_erp(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    monkeypatch.setenv("ERP_LOGIN", "erp-user")
    monkeypatch.setenv("ERP_PASSWORD", "erp-pass")
    config = load_config()
    assert config.user == "erp-user"
    assert config.password == "erp-pass"


def test_load_config_fallback_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    monkeypatch.setenv("DOK_HTTP_USER", "dok-user")
    monkeypatch.setenv("DOK_HTTP_PASSWORD", "dok-pass")
    monkeypatch.setenv("DOCFLOW_ODATA_USERNAME", "doc-user")
    monkeypatch.setenv("DOCFLOW_ODATA_PASSWORD", "doc-pass")
    monkeypatch.setenv("ODATA_USERNAME", "odata-user")
    monkeypatch.setenv("ODATA_PASSWORD", "odata-pass")
    monkeypatch.setenv("ERP_LOGIN", "erp-user")
    monkeypatch.setenv("ERP_PASSWORD", "erp-pass")
    assert load_config().user == "dok-user"
    monkeypatch.delenv("DOK_HTTP_USER")
    monkeypatch.delenv("DOK_HTTP_PASSWORD")
    assert load_config().user == "doc-user"
    monkeypatch.delenv("DOCFLOW_ODATA_USERNAME")
    monkeypatch.delenv("DOCFLOW_ODATA_PASSWORD")
    assert load_config().user == "odata-user"
    monkeypatch.delenv("ODATA_USERNAME")
    monkeypatch.delenv("ODATA_PASSWORD")
    assert load_config().user == "erp-user"


def test_load_config_incomplete_pair_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    monkeypatch.setenv("DOK_HTTP_USER", "dok-only")
    monkeypatch.setenv("ODATA_USERNAME", "odata-user")
    monkeypatch.setenv("ODATA_PASSWORD", "odata-pass")
    config = load_config()
    assert config.user == "odata-user"
    assert config.password == "odata-pass"


def test_load_config_uses_settings_odata(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.onec import dok_soap

    monkeypatch.setattr(dok_soap, "discover_env_files", lambda _explicit: [])
    monkeypatch.setattr(
        dok_soap,
        "_settings_mapping",
        lambda: {"ODATA_USERNAME": "settings-odata", "ODATA_PASSWORD": "settings-pass"},
    )
    for key in (
        "DOK_HTTP_USER",
        "DOK_HTTP_PASSWORD",
        "DOCFLOW_ODATA_USERNAME",
        "DOCFLOW_ODATA_PASSWORD",
        "ODATA_USERNAME",
        "ODATA_PASSWORD",
        "ERP_LOGIN",
        "ERP_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)
    config = load_config()
    assert config.user == "settings-odata"
    assert config.password == "settings-pass"


def test_load_config_missing_user_does_not_blame_server(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    with pytest.raises(RuntimeError, match="нет пользователя") as exc:
        load_config()
    assert "DOK_HTTP_SERVER" not in str(exc.value)
    assert "DOK_HTTP_USER" not in str(exc.value)
    assert "Войдите с паролем 1С" in str(exc.value)


def test_load_config_session_fio_without_password(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    monkeypatch.setenv("ODATA_USERNAME", "odata-user")
    monkeypatch.setenv("ODATA_PASSWORD", "odata-pass")
    with pytest.raises(RuntimeError, match="нет пароля") as exc:
        load_config(username="Иванов И.И.")
    assert "DOK_HTTP_SERVER" not in str(exc.value)
    assert "DOK_HTTP_USER" not in str(exc.value)
    assert "Войдите с паролем 1С" in str(exc.value)
    assert "odata-user" not in str(exc.value)


def test_soap_configured_false_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    assert soap_configured() is False


def test_soap_configured_true_with_odata(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_dok_env(monkeypatch)
    monkeypatch.setenv("ODATA_USERNAME", "odata-user")
    monkeypatch.setenv("ODATA_PASSWORD", "odata-pass")
    assert soap_configured() is True


def test_soap_configured_false_when_server_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tools.onec import dok_soap

    def _no_server(**_kwargs):
        raise RuntimeError("Задайте DOK_HTTP_SERVER в окружении или .env")

    monkeypatch.setattr(dok_soap, "load_config", _no_server)
    assert soap_configured() is False


def test_dok_config_soap_url() -> None:
    config = DokConfig(
        server="192.168.2.229",
        port=81,
        user="svc",
        password="x",
        timeout=30,
        base_path="/doc",
    )
    assert config.soap_url() == "http://192.168.2.229:81/doc/ws/dm.1cws"
    assert config.auth_header().startswith("Basic ")


def test_dok_config_auth_header_encodings() -> None:
    import base64

    utf = DokConfig(
        server="192.168.2.229",
        port=81,
        user="Иванов",
        password="пароль",
        timeout=30,
        base_path="/doc",
        encoding="utf-8",
    )
    cp = utf.with_encoding("cp1251")
    assert utf.auth_header() != cp.auth_header()
    assert base64.b64decode(utf.auth_header().split(" ", 1)[1]) == "Иванов:пароль".encode("utf-8")
    assert base64.b64decode(cp.auth_header().split(" ", 1)[1]) == "Иванов:пароль".encode("cp1251")


def test_filter_ignored_needs_several_other_performers() -> None:
    from app.tools.onec.dok_soap import _filter_ignored

    assert _filter_ignored([], "Иванов И.И.") is False
    assert _filter_ignored([{"performer": "Иванов И.И."}], "Иванов И.И.") is False
    assert (
        _filter_ignored(
            [
                {"performer": "А"},
                {"performer": "Б"},
                {"performer": "В"},
                {"performer": "Иванов И.И."},
            ],
            "Иванов И.И.",
        )
        is True
    )


def test_fetch_inbox_does_not_dump_all_tasks(monkeypatch) -> None:
    from app.tools.onec import dok_soap

    modes: list[str | None] = []
    monkeypatch.setattr(
        dok_soap,
        "find_user",
        lambda *_args, **_kwargs: {"id": "1", "name": "Иванов И.И.", "type": "DMUser"},
    )

    def fake_list(*_args, **kwargs):
        modes.append(kwargs.get("filter_mode"))
        raise RuntimeError("Неизвестное поле в условии отбора: byUser")

    monkeypatch.setattr(dok_soap, "list_open_tasks", fake_list)
    config = DokConfig(
        server="192.168.2.229",
        port=81,
        user="svc",
        password="x",
        timeout=30,
        base_path="/doc",
    )
    with pytest.raises(RuntimeError, match="Неизвестное поле"):
        dok_soap.fetch_inbox(config, "Иванов И.И.", since_days=30, retrieve=False)
    assert modes == ["byUser", "performer"]


def test_fetch_inbox_keeps_dump_when_server_ignores_filter(monkeypatch) -> None:
    from app.tools.onec import dok_soap

    calls = {"n": 0}
    monkeypatch.setattr(
        dok_soap,
        "find_user",
        lambda *_args, **_kwargs: {"id": "1", "name": "Иванов И.И.", "type": "DMUser"},
    )

    def fake_list(*_args, **kwargs):
        calls["n"] += 1
        assert kwargs.get("filter_mode") == "byUser"
        return [
            {"id": "a", "performer": "А", "executed": False, "due": "2026-09-16T18:00:00"},
            {"id": "b", "performer": "Б", "executed": False, "due": "2026-09-16T18:00:00"},
            {"id": "c", "performer": "В", "executed": False, "due": "2026-09-16T18:00:00"},
            {
                "id": "mine",
                "performer": "Иванов И.И.",
                "executed": False,
                "due": "2026-09-16T18:00:00",
            },
        ]

    monkeypatch.setattr(dok_soap, "list_open_tasks", fake_list)
    config = DokConfig(
        server="192.168.2.229",
        port=81,
        user="svc",
        password="x",
        timeout=30,
        base_path="/doc",
    )
    payload = dok_soap.fetch_inbox(
        config,
        "Иванов И.И.",
        since_days=30,
        retrieve=False,
        today_and_overdue=True,
    )
    assert calls["n"] == 1
    assert payload["count"] == 1
    assert payload["rows"][0]["id"] == "mine"


def test_inbox_cache_shares_dump_across_users(tmp_path, monkeypatch) -> None:
    from app.tools.onec import dok_soap

    dok_soap._inbox_cache.clear()
    dok_soap._refreshing.clear()
    monkeypatch.setattr(dok_soap, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        dok_soap,
        "load_config",
        lambda **_kwargs: DokConfig(
            server="192.168.2.229",
            port=81,
            user="svc",
            password="x",
            timeout=210,
            base_path="/doc",
        ),
    )
    calls = {"n": 0}

    def fake_dump(*_args, **_kwargs):
        calls["n"] += 1
        return {
            "endpoint": "http://192.168.2.229:81/doc/ws/dm.1cws",
            "only_open": True,
            "count": 3,
            "rows": [
                {
                    "id": "1",
                    "performer": "Иванов И.И.",
                    "executed": False,
                    "due": "2026-09-16T18:00:00",
                },
                {
                    "id": "2",
                    "performer": "Петров П.П.",
                    "executed": False,
                    "due": "2026-09-10T18:00:00",
                },
                {
                    "id": "3",
                    "performer": "Сидоров С.С.",
                    "executed": False,
                    "due": "2026-09-20T18:00:00",
                },
            ],
        }

    monkeypatch.setattr(dok_soap, "fetch_open_dump", fake_dump)
    first = dok_soap.fetch_user_inbox_tasks("Иванов И.И.", today_and_overdue=True)
    second = dok_soap.fetch_user_inbox_tasks("Петров П.П.", today_and_overdue=True)
    assert calls["n"] == 1
    assert first["cached"] is False
    assert first["count"] == 1
    assert first["rows"][0]["id"] == "1"
    assert first["dump_count"] == 3
    assert second["cached"] is True
    assert second["count"] == 1
    assert second["rows"][0]["id"] == "2"
    third = dok_soap.fetch_user_inbox_tasks(
        "Иванов И.И.", today_and_overdue=True, force_refresh=True
    )
    assert calls["n"] == 2
    assert third["cached"] is False
