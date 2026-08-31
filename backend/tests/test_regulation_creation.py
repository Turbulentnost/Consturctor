from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.regulation import RegulationCreationDraft
from app.models.user import AppUser
from app.services.regulation_creation.interview import (
    append_user_turn,
    build_creation_prompt,
    document_from_interview,
    merge_agent_payload,
    ready_blocker,
)
from app.services.regulation_creation.service import _apply_agent_reply


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return Session()


def _ready_payload(function: dict) -> dict:
    return {
        "status": "ready",
        "message": "Готово",
        "positions": ["Помощник"],
        "interview": {"functions": [function]},
        "document": {
            "title": "Регламент",
            "sections": [{"number": "1", "title": "Порядок", "paragraphs": ["Текст"], "items": []}],
        },
    }


def test_interview_state_keeps_attachment_text_in_followup_prompt() -> None:
    state = append_user_turn(
        {},
        "Проанализируй обязанности",
        [{"name": "duties.txt", "text": "Пользователь ведет календарь совещаний.", "kind": "text"}],
    )
    prompt = build_creation_prompt(
        state=state,
        message="Отвечаю на следующий вопрос",
        initial=False,
        force_create=False,
    )

    assert "duties.txt" in prompt
    assert "Пользователь ведет календарь совещаний." in prompt
    assert "tool, periodicity, triggerAction" in prompt


def test_agent_payload_merges_function_answers() -> None:
    state = merge_agent_payload(
        {},
        {
            "interview": {
                "functions": [
                    {
                        "id": "f1",
                        "title": "Ведение календаря совещаний",
                        "tool": "Excel",
                    }
                ]
            }
        },
    )
    state = merge_agent_payload(
        state,
        {
            "interview": {
                "functions": [
                    {
                        "id": "f1",
                        "periodicity": "Каждый рабочий день",
                        "triggerAction": "Приходит письмо в Outlook с новым совещанием",
                        "userAction": "Открывает Excel и добавляет строку в календарь",
                    }
                ]
            }
        },
    )

    function = state["functions"][0]
    assert function["tool"] == "Excel"
    assert function["periodicity"] == "Каждый рабочий день"
    assert function["openGaps"] == []


def test_notify_two_hours_is_not_concrete_trigger() -> None:
    payload = _ready_payload(
        {
            "id": "f1",
            "title": "Напоминание о совещании",
            "tool": "Outlook",
            "periodicity": "Перед каждым совещанием",
            "triggerAction": "Сообщить за 2 часа до совещания",
            "userAction": "Сообщает участникам",
        }
    )
    state = merge_agent_payload({}, payload)

    blocker = ready_blocker(payload, state)

    assert blocker is not None
    assert blocker.field == "triggerAction"
    assert "конкретный триггер" in blocker.message


def test_apply_agent_reply_rejects_ready_with_missing_inventory() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(id="draft-1", user_id="user-1", status="interview")
    db.add(draft)
    db.commit()

    _apply_agent_reply(db, user_id="user-1", draft=draft, raw=json.dumps(_ready_payload({})))
    db.commit()

    db.refresh(draft)
    assert draft.status == "interview"
    message = db.query(RegulationCreationDraft).filter(RegulationCreationDraft.id == "draft-1").one()
    assert message.result_regulation_id == ""


def test_document_from_interview_builds_sections() -> None:
    document = document_from_interview(
        {
            "functions": [
                {
                    "id": "f1",
                    "title": "Сводка на неделю",
                    "actor": "Помощник ПСД",
                    "tool": "Excel",
                    "periodicity": "Каждый понедельник",
                    "triggerAction": "Наступил понедельник до 10:00",
                    "userAction": "Обновляет сводный план",
                }
            ]
        }
    )

    assert document["title"] == "Регламент"
    assert document["sections"][0]["title"] == "Сводка на неделю"
    assert any("Excel" in item for item in document["sections"][0]["items"])


def test_force_create_finalizes_without_agent_document() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(
        id="draft-force",
        user_id="user-1",
        status="interview",
        interview_json={
            "functions": [
                {
                    "id": "f1",
                    "title": "Сводка на неделю",
                    "actor": "Помощник ПСД",
                    "tool": "Excel",
                    "periodicity": "Каждый понедельник",
                    "triggerAction": "Наступил понедельник до 10:00",
                    "userAction": "Обновляет сводный план",
                }
            ]
        },
    )
    db.add(draft)
    db.commit()

    class DummyResult:
        regulationId = "reg-force"

    from unittest.mock import patch

    with patch(
        "app.services.regulation_creation.service._finalize_document",
        return_value=DummyResult(),
    ) as finalize:
        _apply_agent_reply(
            db,
            user_id="user-1",
            draft=draft,
            raw=json.dumps(
                {
                    "status": "need_more",
                    "message": "Регламент сформирован по приложенным документам.",
                }
            ),
            force_create=True,
        )
        db.commit()

    db.refresh(draft)
    assert finalize.called
    assert draft.status == "finalized"
    assert draft.result_regulation_id == "reg-force"
