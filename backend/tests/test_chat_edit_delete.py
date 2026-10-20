"""Chat: editing and deleting own messages; agent direct messages."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.user import AppUser
from app.modules.chat import agent_messages
from app.modules.chat.handler import handle_command
from app.modules.chat.models import ChatAttachment, ChatMessage, ChatThread, ChatThreadMember
from app.modules.chat.queries import list_messages, list_threads


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            AppUser.__table__,
            ChatThread.__table__,
            ChatThreadMember.__table__,
            ChatMessage.__table__,
            ChatAttachment.__table__,
        ],
    )
    with Session(engine) as session:
        session.add_all([AppUser(id="u1", fio="Иванов Иван Иванович"), AppUser(id="u2", fio="Петров Пётр")])
        session.commit()
        yield session


def _send(db: Session, text: str = "Привет") -> str:
    events = handle_command(
        db, {"type": "send_message", "user_id": "u1", "peer_id": "u2", "client_id": f"c-{text}", "text": text}
    )
    db.commit()
    return events[0]["message"]["id"]


def test_author_edits_message_and_members_get_event(db: Session) -> None:
    message_id = _send(db)

    events = handle_command(db, {"type": "edit_message", "user_id": "u1", "message_id": message_id, "text": "Исправлено"})
    db.commit()

    assert events[0]["type"] == "chat_message_updated"
    assert set(events[0]["user_ids"]) == {"u1", "u2"}
    assert events[0]["text"] == "Исправлено"
    row = list_messages(db, "u2", events[0]["thread_id"])[0]
    assert row["text"] == "Исправлено"
    assert row["edited_at"] is not None
    assert row["deleted"] is False


def test_author_deletes_message_it_disappears_from_preview_and_unread(db: Session) -> None:
    message_id = _send(db, "Секрет")

    events = handle_command(db, {"type": "delete_message", "user_id": "u1", "message_id": message_id})
    db.commit()

    assert events[0]["type"] == "chat_message_deleted"
    row = list_messages(db, "u2", events[0]["thread_id"])[0]
    assert row["deleted"] is True
    assert row["text"] == ""
    assert row["attachments"] == []
    thread = next(item for item in list_threads(db, "u2") if item["id"] == events[0]["thread_id"])
    assert thread["preview"] == ""
    assert thread["unread"] == 0


def test_only_author_can_edit_or_delete(db: Session) -> None:
    message_id = _send(db)

    with pytest.raises(PermissionError):
        handle_command(db, {"type": "edit_message", "user_id": "u2", "message_id": message_id, "text": "Чужое"})
    with pytest.raises(PermissionError):
        handle_command(db, {"type": "delete_message", "user_id": "u2", "message_id": message_id})


def test_deleted_message_cannot_be_edited_and_empty_edit_is_rejected(db: Session) -> None:
    message_id = _send(db)

    with pytest.raises(ValueError):
        handle_command(db, {"type": "edit_message", "user_id": "u1", "message_id": message_id, "text": "  "})
    handle_command(db, {"type": "delete_message", "user_id": "u1", "message_id": message_id})
    with pytest.raises(ValueError):
        handle_command(db, {"type": "edit_message", "user_id": "u1", "message_id": message_id, "text": "Снова"})


def test_short_name_form() -> None:
    assert agent_messages._short("Иванов Иван Иванович") == "иванов и.и."
    assert agent_messages._short("Иванов И.И.") == "иванов и.и."


def test_send_direct_message_resolves_fio_and_marks_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    recipient = AppUser(id="u2", fio="Петров Пётр")
    monkeypatch.setattr(agent_messages, "resolve_recipient", lambda query: (recipient, []))
    monkeypatch.setattr("app.modules.chat.bus.producer.enqueue_command", lambda cmd: sent.append(cmd) or "id")

    result = agent_messages.send_direct_message("u1", {"fio": "Петров П.", "text": "Не хватает ДДС"})

    assert result["sent"] is True
    assert result["recipient_user_id"] == "u2"
    assert sent[0]["type"] == "send_message"
    assert sent[0]["user_id"] == "u1" and sent[0]["peer_id"] == "u2"
    assert sent[0]["text"] == "[ИИ-агент] Не хватает ДДС"


def test_send_direct_message_reports_unknown_or_self(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_messages, "resolve_recipient", lambda query: (None, ["А Б", "А В"]))
    result = agent_messages.send_direct_message("u1", {"fio": "А", "text": "x"})
    assert result["sent"] is False and "несколькими" in result["note"]

    me = AppUser(id="u1", fio="Иванов Иван Иванович")
    monkeypatch.setattr(agent_messages, "resolve_recipient", lambda query: (me, []))
    result = agent_messages.send_direct_message("u1", {"fio": "Иванов", "text": "x"})
    assert result["sent"] is False and "самому себе" in result["note"]
