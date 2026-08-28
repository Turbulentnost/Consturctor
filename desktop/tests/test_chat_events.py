from app.chat.crypto import decrypt_text, encrypt_text
from app.chat.events import dispatch, is_chat_event
from app.api_client import BoardAgent
from app.chat.agent_share import agent_share_payload
from app.chat.models import ChatMessage
from app.chat.store import load_history, save_history
from app.chat.api import _directory_users
from app.chat.shared_bus import append_shared, load_shared
from app.chat.models import ChatThread
from app.chat.page import dedupe_dm_threads, sort_threads, thread_matches
from app.chat.store import load_dialogs, save_history
from app.chat.test_user import (
    TEST_USER_FIO,
    TEST_USER_ID,
    is_test_credentials,
    is_test_user_fio,
    matches_test_user_query,
)
from app.chat.support_agent import echo_command


def test_chat_event_types() -> None:
    assert is_chat_event({"type": "chat_message"})
    assert is_chat_event({"type": "thread_opened"})
    assert not is_chat_event({"type": "pong"})


def test_dispatch_calls_handler() -> None:
    seen: list[dict] = []
    dispatch({"type": "chat_receipt", "thread_id": "1"}, seen.append)
    assert seen and seen[0]["type"] == "chat_receipt"
    dispatch({"type": "pong"}, seen.append)
    assert len(seen) == 1


def test_echo_command_keeps_api_fields() -> None:
    payload = {
        "type": "send_message",
        "client_id": "abc",
        "thread_id": "",
        "kind": "support",
        "text": "проверка",
        "file_ids": [],
        "user_id": "u1",
    }
    dumped = echo_command(payload)
    assert '"type": "send_message"' in dumped
    assert '"client_id": "abc"' in dumped
    assert "проверка" in dumped


def test_encrypt_roundtrip() -> None:
    packed = encrypt_text("секрет")
    assert packed.startswith("enc:v1:")
    assert "секрет" not in packed
    assert decrypt_text(packed) == "секрет"
    assert decrypt_text("обычный текст") == "обычный текст"


def test_history_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    rows = [
        ChatMessage(
            id="1",
            thread_id="support",
            sender_id="u1",
            mine=True,
            text="привет",
            created_at="2026-08-24T10:00:00+00:00",
            receipt="read",
        )
    ]
    save_history("8854", {"support": rows})
    loaded = load_history("8854")
    assert loaded["support"][0].text == "привет"
    assert loaded["support"][0].receipt == "read"


def test_agent_share_payload_uses_name_and_description() -> None:
    agent = BoardAgent(
        id="wf-1",
        title="Сводка поручений",
        description="Собирает поручения за день",
        trigger_summary="Каждый день в 09:00",
        trigger_kind="cron",
        phase="done",
    )
    payload = agent_share_payload(agent)
    assert payload["type"] == "agent_card"
    assert payload["workflow_id"] == "wf-1"
    assert payload["title"] == "Сводка поручений"
    assert payload["description"] == "Собирает поручения за день"
    assert payload["trigger_summary"] == "Каждый день в 09:00"


def test_history_keeps_agent_card(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    rows = [
        ChatMessage(
            id="2",
            thread_id="support",
            sender_id="u1",
            mine=True,
            text="",
            created_at="2026-08-24T10:00:00+00:00",
            receipt="delivered",
            agent={"type": "agent_card", "workflow_id": "wf-1", "title": "Агент"},
        )
    ]
    save_history("8854", {"support": rows})
    loaded = load_history("8854")
    assert loaded["support"][0].agent["title"] == "Агент"


def test_directory_users_from_fio_list_and_objects() -> None:
    rows = _directory_users(
        {
            "items": [
                "Иванов Иван",
                {"id": "ABC", "fio": "Петров Пётр", "position": "Юрист", "department": "Право"},
            ]
        }
    )
    assert rows[0].fio == "Иванов Иван"
    assert rows[1].id == "ABC"
    assert rows[1].position == "Юрист"


def test_anna_credentials() -> None:
    assert is_test_user_fio("Анна Де Армас")
    assert is_test_credentials("Анна Де Армас", "anna")
    assert is_test_credentials("Анна Де Армас", "any")
    assert not is_test_credentials("Анна Де Армас", "")
    assert matches_test_user_query("анн")
    assert matches_test_user_query("арма")
    assert not matches_test_user_query("иван")


def test_zhalybin_credentials() -> None:
    from app.chat.test_user import (
        ZHALYBIN_FIO,
        ZHALYBIN_PASSWORD,
        is_local_test_user,
        is_zhalybin_user,
        test_login_result,
    )

    assert is_test_user_fio("Жалыбин Максим")
    assert is_test_credentials(ZHALYBIN_FIO, ZHALYBIN_PASSWORD)
    assert is_test_credentials(ZHALYBIN_FIO, "any-local")
    result = test_login_result(ZHALYBIN_FIO)
    assert result.user.fio == ZHALYBIN_FIO
    assert result.user.position == "Промпт-инженер 2 категории"
    assert is_zhalybin_user(result.user.id, result.user.fio)
    assert is_local_test_user(result.user.id, result.user.fio)
    from app.chat.test_user import preferred_login_fio

    assert preferred_login_fio("") == ZHALYBIN_FIO
    assert preferred_login_fio("Ильченко Екатерина Александровна") == ZHALYBIN_FIO
    assert preferred_login_fio("Анна Де Армас") == ZHALYBIN_FIO
    assert test_login_result().user.fio == ZHALYBIN_FIO


def test_ilchenko_credentials() -> None:
    from app.chat.test_user import ILCHENKO_FIO, ILCHENKO_PASSWORD, test_login_result

    assert is_test_user_fio("Ильченко Екатерина")
    assert is_test_credentials(ILCHENKO_FIO, ILCHENKO_PASSWORD)
    assert not is_test_credentials(ILCHENKO_FIO, "anna")
    result = test_login_result("Ильченко Екатерина Александровна")
    assert result.user.fio == ILCHENKO_FIO
    assert result.access_token == ""
    from app.chat.test_user import canonical_test_credentials, is_local_test_user

    assert is_local_test_user(result.user.id, result.user.fio)
    creds = canonical_test_credentials(fio=ILCHENKO_FIO)
    assert creds is not None
    assert creds[1] == ILCHENKO_PASSWORD


def test_threads_sort_by_pin_then_last_message() -> None:
    older = ChatThread(id="a", kind="dm", title="A", last_message_at="2026-08-24T10:00:00+00:00")
    newer = ChatThread(id="b", kind="dm", title="B", last_message_at="2026-08-24T12:00:00+00:00")
    pinned = ChatThread(
        id="c",
        kind="dm",
        title="C",
        last_message_at="2026-08-24T09:00:00+00:00",
        pinned=True,
    )
    support = ChatThread(id="support", kind="support", title="Поддержка")
    rows = sort_threads([older, newer, pinned, support])
    assert [item.id for item in rows] == ["c", "b", "a", "support"]


def test_dialog_keeps_pin(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_history(
        "u1",
        {},
        [ChatThread(id="peer", kind="dm", title="Анна", pinned=True, last_message_at="2026-08-24T12:00:00+00:00")],
    )
    loaded = load_dialogs("u1")
    assert loaded[0].pinned is True


def test_dialog_keeps_unread(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_history(
        "u1",
        {},
        [ChatThread(id="peer", kind="dm", title="Анна", unread=2, last_read_id="m1")],
    )
    loaded = load_dialogs("u1")
    assert loaded[0].unread == 2
    assert loaded[0].last_read_id == "m1"


def test_shared_bus_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    message = ChatMessage(
        id="m1",
        thread_id=TEST_USER_ID,
        sender_id="u1",
        mine=True,
        text="привет, Анна",
        client_id="c1",
        created_at="2026-08-24T10:00:00+00:00",
    )
    append_shared("u1", TEST_USER_ID, message)
    incoming = load_shared(TEST_USER_ID, "u1")
    assert incoming[0].text == "привет, Анна"
    assert incoming[0].mine is False
    assert TEST_USER_FIO


def test_dialog_ids_match_peer_and_server() -> None:
    from app.ui.widgets.sidebar import dialog_ids_match

    assert dialog_ids_match("thr-1", "user-1", "user-1")
    assert dialog_ids_match("user-1", "", "thr-1", "user-1")
    assert not dialog_ids_match("thr-1", "user-1", "thr-2", "user-2")


def test_short_fio_uses_last_name_and_initials() -> None:
    from app.ui.widgets.sidebar import short_fio

    assert short_fio("Иванов Иван Иванович") == "Иванов И. И."
    assert short_fio("Петрова Анна") == "Петрова А."
    assert short_fio("") == ""


def test_thread_matches_peer_and_server_ids() -> None:
    assert thread_matches("user-1", "thr-1", "user-1")
    assert thread_matches("thr-1", "thr-1", "user-1")
    assert not thread_matches("user-2", "thr-1", "user-1")
    assert not thread_matches("", "thr-1", "user-1")


def test_dedupe_dm_threads_keeps_one_chat_per_person() -> None:
    first = ChatThread(id="a", kind="dm", title="Уставицкий Андрей Алексеевич", last_message_at="1")
    second = ChatThread(
        id="b",
        kind="dm",
        title="Уставицкий Андрей Алексеевич",
        peer_id="peer-1",
        last_message_at="2",
    )
    empty = ChatThread(id="c", kind="dm", title="Комарькова Анастасия Эдуардовна")
    merged = dedupe_dm_threads([first, second, empty])
    titles = [item.title for item in merged]
    assert titles.count("Уставицкий Андрей Алексеевич") == 1
    assert next(item for item in merged if item.title.startswith("Уставицкий")).id == "b"
    assert "Комарькова Анастасия Эдуардовна" in titles
