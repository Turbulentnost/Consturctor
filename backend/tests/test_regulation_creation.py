from __future__ import annotations

import json
from pathlib import Path

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
    set_interview_position,
)
from app.services.regulation_creation.service import (
    _apply_agent_reply,
    _finalize_document,
    _parse_agent_response,
    _result_from_created_document,
    get_active_creation_session,
    get_creation_document,
    start_creation_session,
)


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
    assert "только новую или изменённую функцию" in prompt


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


def test_unclear_role_blocks_ready() -> None:
    payload = _ready_payload(
        {
            "id": "f1",
            "title": "Сводка инспекции",
            "actor": "Руководитель инспекционной группы",
            "tool": "Excel",
            "periodicity": "Каждый понедельник",
            "triggerAction": "Наступил понедельник до 10:00",
            "userAction": "Обновляет сводный план",
        }
    )
    state = set_interview_position({}, "Помощник Председателя совета директоров")

    blocker = ready_blocker(payload, state)

    assert blocker is not None
    assert blocker.field == "roleStatus"
    assert "относится к должности" in blocker.message


def test_foreign_function_is_excluded_from_document() -> None:
    document = document_from_interview(
        {
            "position": "Помощник ПСД",
            "functions": [
                {
                    "id": "f1",
                    "title": "Чужая функция",
                    "roleStatus": "foreign",
                    "tool": "1C",
                    "userAction": "Согласует заявку",
                },
                {
                    "id": "f2",
                    "title": "Моя сводка",
                    "roleStatus": "belongs",
                    "tool": "Excel",
                    "userAction": "Обновляет план",
                },
            ],
        }
    )

    titles = [section["title"] for section in document["sections"]]
    assert titles == ["Моя сводка"]


def test_matching_actor_becomes_belongs() -> None:
    state = merge_agent_payload(
        {"position": "Помощник Председателя совета директоров"},
        {
            "interview": {
                "functions": [
                    {
                        "id": "f1",
                        "title": "Подготовка сводки",
                        "actor": "Помощник Председателя совета директоров",
                        "tool": "Excel",
                        "periodicity": "Каждый понедельник",
                        "triggerAction": "Наступил понедельник до 10:00",
                        "userAction": "Обновляет сводный план",
                    }
                ]
            }
        },
    )

    assert state["functions"][0]["roleStatus"] == "belongs"
    assert state["functions"][0]["openGaps"] == []


def _owned_function() -> dict:
    return {
        "id": "f1",
        "title": "Сводка на неделю",
        "actor": "Помощник ПСД",
        "roleStatus": "belongs",
        "tool": "Excel",
        "periodicity": "Каждый понедельник",
        "triggerAction": "Наступил понедельник до 10:00",
        "userAction": "Обновляет сводный план",
    }


def test_ready_without_document_finalizes_from_interview() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(
        id="draft-ready-nodoc",
        user_id="user-1",
        status="interview",
        interview_json={"functions": [_owned_function()]},
    )
    db.add(draft)
    db.commit()

    class DummyResult:
        regulationId = "reg-ready"

    from unittest.mock import patch

    with patch(
        "app.services.regulation_creation.service._finalize_document",
        return_value=DummyResult(),
    ) as finalize:
        _apply_agent_reply(
            db,
            user_id="user-1",
            draft=draft,
            raw=json.dumps({"status": "ready", "message": "Регламент сформирован."}),
        )
        db.commit()

    db.refresh(draft)
    assert finalize.called
    assert draft.status == "finalized"
    assert draft.result_regulation_id == "reg-ready"


def test_result_from_created_document_has_fragments() -> None:
    result = _result_from_created_document(
        regulation_id="reg-doc",
        filename="Регламент.docx",
        document={
            "title": "Регламент помощника",
            "sections": [
                {
                    "number": "1",
                    "title": "Сводка",
                    "paragraphs": ["Исполнитель: помощник"],
                    "items": ["Инструмент: Excel"],
                }
            ],
        },
    )

    assert result.regulationId == "reg-doc"
    assert result.fileName == "Регламент.docx"
    assert "1 Сводка" in result.sections
    assert any("Excel" in item.text for item in result.fragments)


def test_finalize_document_writes_docx_and_regulation_row(tmp_path, monkeypatch) -> None:
    from app.config import settings
    from app.services.regulation.storage import get_document

    monkeypatch.setattr(settings, "regulation_storage_dir", tmp_path)
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(id="draft-fin", user_id="user-1", status="interview")
    db.add(draft)
    db.commit()

    result = _finalize_document(
        db,
        user_id="user-1",
        draft=draft,
        document={
            "title": "Регламент",
            "sections": [{"title": "Порядок", "paragraphs": ["Текст"], "items": []}],
        },
    )
    db.commit()

    assert result.regulationId
    assert Path(draft.result_document_path).is_file()
    stored = get_document(db, regulation_id=result.regulationId, user_id="user-1")
    assert stored is not None
    assert stored.file_name.endswith(".docx")


def test_get_creation_document_rebuilds_missing_file(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "regulation_storage_dir", tmp_path)
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(
        id="draft-missing",
        user_id="user-1",
        status="finalized",
        result_document_path=str(tmp_path / "gone.docx"),
        draft_document_json={
            "title": "Регламент",
            "sections": [{"title": "Порядок", "paragraphs": ["Текст"], "items": []}],
        },
    )
    db.add(draft)
    db.commit()

    path = get_creation_document(db, user_id="user-1", draft_id="draft-missing")

    assert path.is_file()
    assert path.suffix == ".docx"
    db.refresh(draft)
    assert draft.result_document_path == str(path)


def test_start_creation_resumes_open_draft() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест", position="Помощник"))
    db.commit()

    first = start_creation_session(db, user_id="user-1")
    second = start_creation_session(db, user_id="user-1")
    active = get_active_creation_session(db, user_id="user-1")

    assert first.draftId == second.draftId
    assert active is not None
    assert active.draftId == first.draftId
    assert any(item.role == "assistant" for item in second.messages)


def test_start_creation_fresh_closes_previous_draft() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    db.commit()

    first = start_creation_session(db, user_id="user-1")
    second = start_creation_session(db, user_id="user-1", fresh=True)
    old = db.get(RegulationCreationDraft, first.draftId)
    active = get_active_creation_session(db, user_id="user-1")

    assert first.draftId != second.draftId
    assert old is not None
    assert old.status == "closed"
    assert active is not None
    assert active.draftId == second.draftId


def test_parse_agent_response_keeps_first_interview_json() -> None:
    raw = (
        '{"status":"need_more","message":"Вопрос один","interview":{"functions":[]}}'
        '{"status":"need_more","message":"Вопрос два","interview":{"functions":[]}}'
    )

    parsed = _parse_agent_response(raw)

    assert parsed["message"] == "Вопрос один"
    assert parsed["status"] == "need_more"
