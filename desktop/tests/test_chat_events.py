from app.chat.crypto import decrypt_text, encrypt_text
from app.chat.events import dispatch, is_chat_event
from app.api_client import BoardAgent
from app.chat.agent_share import agent_share_payload
from app.chat.models import ChatMessage
from app.chat.store import load_history, save_history
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
