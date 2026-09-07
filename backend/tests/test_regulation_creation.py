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
    document_has_full_text,
    followup_blocker,
    is_replacement_garbage,
    merge_agent_payload,
    ready_blocker,
    remember_assistant_question,
    set_interview_position,
)
from app.services.workflows.document import DocumentError
from app.services.regulation_creation.service import (
    _apply_agent_reply,
    _display_user_message,
    _finalize_document,
    _load_creation_attachments,
    _parse_agent_response,
    _result_from_created_document,
    get_active_creation_session,
    get_creation_document,
    persist_creation_turn,
    start_creation_session,
)
from app.schemas.regulation import RegulationCreationSendRequest


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
    assert "roundQuestions" in prompt or "pipeline.stage" in prompt
    assert "interview.processes" in prompt or '"processes"' in prompt
    # Полный шаблон СТО не тащим на каждый вопрос интервью.
    assert "Назначение и область применения" not in prompt or "pipeline.stage" in prompt
    assert "самостоятельный регламент процесса" not in prompt


def test_document_prompt_includes_sto_structure() -> None:
    prompt = build_creation_prompt(
        state={},
        message="Готово",
        initial=False,
        force_create=False,
        for_document=True,
        include_attachment_bodies=False,
    )
    assert "СТО-34-003" in prompt
    assert "Назначение и область применения" in prompt
    assert "ready" in prompt

def test_local_sdk_prompt_omits_attachment_bodies() -> None:
    state = append_user_turn(
        {},
        "Проанализируй обязанности",
        [{"name": "duties.txt", "text": "Пользователь ведет календарь совещаний.", "kind": "text"}],
    )
    prompt = build_creation_prompt(
        state=state,
        message="Отвечаю на следующий вопрос",
        initial=True,
        force_create=False,
        include_attachment_bodies=False,
    )

    assert "duties.txt" in prompt
    assert "materials/" in prompt
    assert "Пользователь ведет календарь совещаний." not in prompt


def test_replacement_garbage_is_detected() -> None:
    assert is_replacement_garbage(
        "????? ?????? ??????????? ??????? ?? ????????? ?????????? ????????? ?????? ???????????"
    )
    assert not is_replacement_garbage("В какой системе вы готовите повестку?")
    assert not is_replacement_garbage("1С ERP")


def test_agent_payload_merges_function_answers() -> None:
    state = merge_agent_payload(
        {},
        {
            "interview": {
                "functions": [
                    {
                        "id": "f1",
                        "title": "Ведение календаря совещаний",
                        "tool": "Excel-файл сводного плана",
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
    assert function["tool"] == "Excel-файл сводного плана"
    assert function["periodicity"] == "Каждый рабочий день"
    assert function["openGaps"] == []
    assert state["processes"][0]["knownFacts"]["workLocation"] == "Excel-файл сводного плана"


def test_generic_system_name_does_not_close_work_location() -> None:
    payload = _ready_payload(
        {
            "id": "f1",
            "title": "Календарь заседаний СД",
            "actor": "Помощник ПСД",
            "roleStatus": "belongs",
            "tool": "1С",
            "periodicity": "Ежегодно на год вперед",
            "triggerAction": "Поручение председателя совета директоров",
            "userAction": "Формирует календарь заседаний Совета директоров",
        }
    )
    state = merge_agent_payload({}, payload)

    blocker = ready_blocker(payload, state)

    assert blocker is not None
    assert blocker.field == "tool"
    assert "общий инструмент" in blocker.message
    assert state["functions"][0]["openGaps"] == ["tool"]


def test_current_question_is_not_skipped_after_partial_answer() -> None:
    state = merge_agent_payload(
        {},
        {
            "interview": {
                "functions": [
                    {
                        "id": "f1",
                        "title": "Календарь заседаний СД",
                        "actor": "Помощник ПСД",
                        "roleStatus": "belongs",
                    }
                ]
            }
        },
    )
    state, _ = remember_assistant_question(
        state,
        message="В какой системе, файле или канале вы формируете календарь заседаний?",
        function_id="f1",
        field="tool",
    )
    state = append_user_turn(state, "1С", [])
    agent_payload = {
        "status": "need_more",
        "message": "Как часто вы формируете календарь заседаний?",
        "answerSufficiency": {
            "status": "partial",
            "processId": "f1",
            "field": "tool",
            "answerSummary": "Названа только система.",
            "missingFacts": ["Не указан объект работы в системе."],
        },
        "interview": {
            "functions": [
                {
                    "id": "f1",
                    "title": "Календарь заседаний СД",
                    "actor": "Помощник ПСД",
                    "roleStatus": "belongs",
                    "tool": "1С",
                }
            ]
        },
    }
    state = merge_agent_payload(state, agent_payload)

    blocker = followup_blocker(agent_payload, state)

    assert blocker is not None
    assert blocker.field == "tool"
    assert "Где именно пользователь работает" in blocker.message
    assert state["askedQuestions"][-1]["sufficiency"] == "partial"


def test_apply_agent_reply_overrides_next_question_after_partial_answer() -> None:
    from app.models.regulation import RegulationCreationMessage

    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    state = merge_agent_payload(
        {},
        {
            "interview": {
                "functions": [
                    {
                        "id": "f1",
                        "title": "Календарь заседаний СД",
                        "actor": "Помощник ПСД",
                        "roleStatus": "belongs",
                    }
                ]
            }
        },
    )
    state, _ = remember_assistant_question(
        state,
        message="В какой системе, файле или канале вы формируете календарь заседаний?",
        function_id="f1",
        field="tool",
    )
    state = append_user_turn(state, "1С", [])
    draft = RegulationCreationDraft(
        id="draft-partial-tool",
        user_id="user-1",
        status="generating",
        interview_json=state,
    )
    db.add(draft)
    db.commit()

    _apply_agent_reply(
        db,
        user_id="user-1",
        draft=draft,
        raw=json.dumps(
            {
                "status": "need_more",
                "message": "Как часто вы формируете календарь заседаний?",
                "answerSufficiency": {
                    "status": "partial",
                    "processId": "f1",
                    "field": "tool",
                    "answerSummary": "Названа только система.",
                    "missingFacts": ["Не указан объект работы в системе."],
                },
                "interview": {
                    "functions": [
                        {
                            "id": "f1",
                            "title": "Календарь заседаний СД",
                            "actor": "Помощник ПСД",
                            "roleStatus": "belongs",
                            "tool": "1С",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
    )
    db.commit()

    db.refresh(draft)
    message = (
        db.query(RegulationCreationMessage)
        .filter(RegulationCreationMessage.draft_id == "draft-partial-tool")
        .one()
    )
    assert draft.status == "interview"
    assert "Где именно пользователь работает" in message.content
    assert "Как часто" not in message.content


def test_repeated_question_is_saved_as_deeper_followup() -> None:
    question = "В какой системе вы проверяете комплектность материалов?"
    state, first = remember_assistant_question({}, message=question, function_id="f1", field="tool")
    state, second = remember_assistant_question(state, message=question, function_id="f1", field="tool")

    assert first == question
    assert second.startswith(question)
    assert "конкретный объект" in second or "файл/реестр" in second
    assert len(state["askedQuestions"]) >= 2


def test_notify_two_hours_is_not_concrete_trigger() -> None:
    payload = _ready_payload(
        {
            "id": "f1",
            "title": "Напоминание о совещании",
            "tool": "Outlook, карточка события календаря",
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
                    "tool": "Excel-файл сводного плана",
                    "periodicity": "Каждый понедельник",
                    "triggerAction": "Наступил понедельник до 10:00",
                    "userAction": "Обновляет сводный план",
                }
            ]
        }
    )

    assert document["title"] == "Регламент"
    titles = [section["title"] for section in document["sections"]]
    assert titles[0] == "Назначение и область применения"
    assert titles[5] == "Организация работы"
    work = document["sections"][5]["sections"][0]
    assert work["title"] == "Сводка на неделю"
    assert any("Excel" in item for item in work["items"])


def test_document_full_text_rejects_field_dump() -> None:
    assert not document_has_full_text(
        {
            "title": "Регламент",
            "sections": [
                {
                    "title": "Сводка",
                    "items": [
                        "Инструмент: Excel",
                        "Периодичность: Каждый понедельник",
                        "Триггер: Наступил понедельник до 10:00",
                        "Действие пользователя: Обновляет сводный план",
                    ],
                }
            ],
        }
    )
    assert document_has_full_text(
        {
            "title": "Регламент подготовки сводки",
            "sections": [
                {
                    "title": "Подготовка еженедельной сводки",
                    "paragraphs": [
                        (
                            "Процесс нужен для того, чтобы к началу рабочей недели у руководителя "
                            "была единая актуальная картина предстоящих совещаний, конфликтов "
                            "помещений и задач, требующих решения."
                        ),
                        (
                            "Работа начинается в понедельник до 10:00. Помощник открывает сводный "
                            "план в Excel, проверяет обновления календаря и переносит подтвержденные "
                            "совещания в итоговое письмо для руководителя."
                        ),
                    ],
                }
            ],
        }
    )


def _card_style_document() -> dict:
    return {
        "title": "Регламент действий помощника ПСД",
        "sections": [
            {
                "title": "Передача маркетинговых планов директору",
                "paragraphs": [
                    (
                        "Основание: СТО-34-003, таблица внутренних коммуникаций. "
                        "Исполнители в тексте: руководители структурных подразделений и помощник ПСД."
                    )
                ],
                "items": [
                    "Получить маркетинговый план от руководителя структурного подразделения.",
                    "Передать план директору организации в 1С ERP.",
                    "Предположение: начинать работу при поступлении плана от руководителя.",
                ],
            },
            {
                "title": "Подготовка и проведение заседаний РК",
                "paragraphs": [
                    (
                        "Основание: ПЛ-01-001. Ответственный за заседания - секретарь РК. "
                        "Заседания проводятся не реже одного раза в неделю."
                    )
                ],
                "items": [
                    "Еженедельно до заседания сформировать повестку.",
                    "Утвердить повестку у Руководителя РК.",
                    "Предположение: вести повестку в 1С ERP или отдельным файлом.",
                ],
            },
            {
                "title": "Оформление протоколов заседаний РК",
                "paragraphs": [
                    (
                        "Основание: ПЛ-01-001. По итогам совещания секретарь РК составляет "
                        "протокол в 1С ERP по утвержденному шаблону."
                    )
                ],
                "items": [
                    "После окончания заседания РК создать протокол в 1С ERP.",
                    "Зафиксировать решения, поручения, сроки и ответственных.",
                    "Предположение: создать протокол в день заседания.",
                ],
            },
        ],
    }


def test_document_full_text_rejects_card_style_sections() -> None:
    assert not document_has_full_text(_card_style_document())


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
                    "tool": "Excel-файл сводного плана",
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
            "tool": "Excel-файл сводного плана",
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
                    "tool": "Excel-файл сводного плана",
                    "userAction": "Обновляет план",
                },
            ],
        }
    )

    titles = [section["title"] for section in document["sections"]]
    assert "Чужая функция" not in titles
    work_titles = [item.get("title") for item in document["sections"][5].get("sections") or []]
    assert work_titles == ["Моя сводка"]


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
                        "tool": "Excel-файл сводного плана",
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
        "tool": "Excel-файл сводного плана",
        "periodicity": "Каждый понедельник",
        "triggerAction": "Наступил понедельник до 10:00",
        "userAction": "Обновляет сводный план",
    }


def test_ready_without_document_does_not_finalize_from_interview() -> None:
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
    assert not finalize.called
    assert draft.status == "interview"
    assert draft.result_regulation_id == ""
    assert draft.interview_json["document_write_required"] is True


def test_ready_with_card_style_document_does_not_finalize() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(
        id="draft-ready-card",
        user_id="user-1",
        status="interview",
        interview_json={"functions": [_owned_function()]},
    )
    db.add(draft)
    db.commit()

    class DummyResult:
        regulationId = "reg-card"

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
                    "status": "ready",
                    "message": "Регламент сформирован.",
                    "document": _card_style_document(),
                },
                ensure_ascii=False,
            ),
        )
        db.commit()

    db.refresh(draft)
    assert not finalize.called
    assert draft.status == "interview"
    assert draft.result_regulation_id == ""
    assert draft.interview_json["document_write_required"] is True


def test_ready_with_full_document_finalizes() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(
        id="draft-ready-full",
        user_id="user-1",
        status="interview",
        interview_json={"functions": [_owned_function()]},
    )
    db.add(draft)
    db.commit()

    class DummyResult:
        regulationId = "reg-ready-full"

    full_document = {
        "title": "Регламент подготовки сводки",
        "sections": [
            {
                "number": "1",
                "title": "Подготовка еженедельной сводки",
                "paragraphs": [
                    (
                        "Процесс нужен для того, чтобы к началу рабочей недели у руководителя была "
                        "единая актуальная картина предстоящих совещаний, конфликтов помещений и "
                        "задач, требующих решения."
                    ),
                    (
                        "Работа начинается в понедельник до 10:00. Помощник открывает сводный план "
                        "в Excel, проверяет обновления календаря и переносит подтвержденные "
                        "совещания в итоговое письмо для руководителя."
                    ),
                ],
                "items": [],
            }
        ],
    }

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
                    "status": "ready",
                    "message": "Регламент сформирован.",
                    "document": full_document,
                }
            ),
        )
        db.commit()

    db.refresh(draft)
    finalize.assert_called_once()
    assert draft.status == "finalized"
    assert draft.result_regulation_id == "reg-ready-full"


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


def test_apply_agent_reply_replaces_ascii_question_marks() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(id="draft-garbage", user_id="user-1", status="interview")
    db.add(draft)
    db.commit()

    raw = json.dumps(
        {
            "status": "need_more",
            "message": "????? ?????? ??????????? ??????? ?? ????????? ?????????? ?????????",
            "quickAnswers": ["????? ??????? ??? ??????????? ????????"],
            "interview": {
                "functions": [
                    {
                        "id": "f1",
                        "title": "????? ?????????",
                        "sourceRefs": [
                            {
                                "file": "?????????_????????.docx",
                                "quote": "???????? ??? ???????? ??",
                            }
                        ],
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    _apply_agent_reply(db, user_id="user-1", draft=draft, raw=raw)
    db.commit()

    from app.models.regulation import RegulationCreationMessage

    messages = (
        db.query(RegulationCreationMessage)
        .filter(RegulationCreationMessage.draft_id == "draft-garbage")
        .all()
    )
    assert messages
    assert "нечитаемом виде" in messages[-1].content
    assert "?" not in messages[-1].content[0:8]
    interview = draft.interview_json if isinstance(draft.interview_json, dict) else {}
    functions = interview.get("functions") or []
    if functions:
        refs = functions[0].get("sourceRefs") or []
        assert refs == []


def test_display_user_message_keeps_only_typed_text() -> None:
    files = [{"name": "a.pdf"}, {"name": "b.docx"}]
    assert _display_user_message("", files) == ""
    assert _display_user_message("  Привет  ", files) == "Привет"
    assert _display_user_message("Привет", []) == "Привет"
    assert "📎" not in _display_user_message("Привет", files)
    assert "a.pdf" not in _display_user_message("Привет", files)


def test_parse_agent_response_keeps_first_interview_json() -> None:
    raw = (
        '{"status":"need_more","message":"Вопрос один","interview":{"functions":[]}}'
        '{"status":"need_more","message":"Вопрос два","interview":{"functions":[]}}'
    )

    parsed = _parse_agent_response(raw)

    assert parsed["message"] == "Вопрос один"
    assert parsed["status"] == "need_more"


def test_unreadable_pdf_keeps_stub_and_does_not_abort_turn(monkeypatch) -> None:
    def boom(name: str, raw: bytes) -> dict:
        raise DocumentError("LM Studio OCR недоступен: connection refused")

    monkeypatch.setattr(
        "app.services.regulation_creation.service._load_creation_attachment",
        boom,
    )
    loaded = _load_creation_attachments([("scan.pdf", b"%PDF-1.3")])
    assert len(loaded) == 1
    assert loaded[0]["name"] == "scan.pdf"
    assert "не удалось прочитать" in loaded[0]["text"]
    assert loaded[0]["read_error"]

    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    db.commit()
    session = start_creation_session(db, user_id="user-1")
    turn = persist_creation_turn(
        db,
        user_id="user-1",
        draft_id=session.draftId,
        request=RegulationCreationSendRequest(message="Для помощника ПСД"),
        files=[("scan.pdf", b"%PDF-1.3")],
    )
    assert turn.session.draftId == session.draftId
    assert any(item.role == "user" for item in turn.session.messages)


def test_pipeline_default_and_upload_to_extract() -> None:
    from app.services.regulation_creation.pipeline import mark_upload_received, normalize_pipeline
    from app.services.regulation_creation.interview import append_user_turn, new_interview_state

    state = new_interview_state()
    assert normalize_pipeline(state["pipeline"])["stage"] == "upload"
    state = append_user_turn(
        state,
        "Разбери файл",
        [{"name": "duties.txt", "text": "Ведёт календарь совещаний в Outlook.", "kind": "text"}],
    )
    assert state["pipeline"]["stage"] == "extract"
    state = mark_upload_received(state)
    assert state["pipeline"]["stage"] == "extract"


def test_select_processes_and_material_slice() -> None:
    from app.services.regulation_creation.pipeline import select_processes, slice_materials_for_prompt

    state = {
        "attachments": [
            {"id": "file1", "name": "duties.txt", "kind": "text", "text": "A" * 5000 + " Календарь совещаний " + "B" * 5000}
        ],
        "processes": [
            {
                "id": "p1",
                "title": "Календарь совещаний",
                "actor": "Помощник",
                "roleStatus": "unclear",
                "knownFacts": {},
                "sourceRefs": [{"file": "duties.txt", "quote": "Календарь совещаний"}],
            },
            {
                "id": "p2",
                "title": "Чужая функция",
                "actor": "Другой",
                "roleStatus": "unclear",
                "knownFacts": {},
                "sourceRefs": [],
            },
        ],
        "functions": [],
        "pipeline": {"stage": "select"},
    }
    out = select_processes(state, ["p1"])
    assert out["pipeline"]["stage"] == "interview"
    assert out["pipeline"]["selectedProcessIds"] == ["p1"]
    assert out["processes"][0]["roleStatus"] == "belongs"
    assert out["processes"][1]["roleStatus"] == "foreign"
    sliced = slice_materials_for_prompt(out, full=False)
    names = [item["name"] for item in sliced]
    assert any(name.startswith("global-") for name in names)
    assert any("p1" in name for name in names)


def test_extract_cannot_skip_select_with_round_questions() -> None:
    """Agent must not jump to interview/first round before user picks processes."""
    from app.services.regulation_creation.interview import merge_agent_payload

    state = {
        "attachments": [{"id": "f1", "name": "duties.txt", "kind": "text", "text": "Календарь"}],
        "processes": [],
        "functions": [],
        "pipeline": {"stage": "extract"},
    }
    payload = {
        "status": "need_more",
        "message": "Нашёл процессы, сразу вопросы",
        "interview": {
            "processes": [
                {
                    "id": "p1",
                    "title": "Календарь",
                    "actor": "Помощник",
                    "roleStatus": "unclear",
                    "knownFacts": {},
                    "sourceRefs": [{"file": "duties.txt", "quote": "Календарь"}],
                }
            ]
        },
        "pipeline": {"stage": "interview"},
        "roundQuestions": [
            {"id": "q1", "processId": "p1", "field": "trigger", "text": "Когда запускается?"},
            {"id": "q2", "processId": "p1", "field": "steps", "text": "Какие шаги?"},
        ],
    }
    out = merge_agent_payload(state, payload)
    assert out["pipeline"]["stage"] == "select"
    assert out["pipeline"]["selectedProcessIds"] == []
    assert out["pipeline"]["roundQuestions"] == []
    assert out["pipeline"]["round"] == 0
    assert len(out["processes"]) >= 1


def test_round_questions_apply_only_after_select() -> None:
    from app.services.regulation_creation.interview import merge_agent_payload
    from app.services.regulation_creation.pipeline import select_processes

    state = {
        "processes": [
            {
                "id": "p1",
                "title": "Календарь",
                "roleStatus": "unclear",
                "knownFacts": {
                    "workLocation": "Outlook календарь",
                    "frequency": "ежедневно",
                    "trigger": "письмо от руководителя",
                    "steps": ["обновляет событие"],
                },
                "sourceRefs": [],
            }
        ],
        "functions": [],
        "pipeline": {"stage": "select", "blocks": []},
    }
    state = select_processes(state, ["p1"])
    out = merge_agent_payload(
        state,
        {
            "status": "need_more",
            "message": "Раунд 1",
            "roundQuestions": [
                {"id": "q1", "processId": "p1", "field": "trigger", "text": "Триггер?"},
            ],
        },
    )
    assert out["pipeline"]["stage"] == "interview"
    assert len(out["pipeline"]["roundQuestions"]) == 1
    assert out["pipeline"]["round"] == 1


def test_round_does_not_start_until_collect_stage_done() -> None:
    from app.services.regulation_creation.interview import merge_agent_payload
    from app.services.regulation_creation.pipeline import select_processes

    state = {
        "processes": [
            {
                "id": "p1",
                "title": "Календарь",
                "roleStatus": "unclear",
                "knownFacts": {"workLocation": "Outlook"},
                "sourceRefs": [],
            }
        ],
        "functions": [],
        "pipeline": {"stage": "select", "blocks": []},
    }
    state = select_processes(state, ["p1"])
    out = merge_agent_payload(
        state,
        {
            "status": "need_more",
            "message": "Попытка стартовать раунд",
            "roundQuestions": [
                {"id": "q1", "processId": "p1", "field": "trigger", "text": "Какой триггер?"},
            ],
        },
    )
    assert out["pipeline"]["interviewPhase"] == "collect"
    assert out["pipeline"]["round"] == 0
    assert out["pipeline"]["roundQuestions"] == []


def test_remaining_questions_estimate_is_non_negative() -> None:
    from app.services.regulation_creation.pipeline import normalize_pipeline

    pipe = normalize_pipeline(
        {
            "stage": "interview",
            "selectedProcessIds": ["p1"],
            "blocks": [
                {
                    "id": "b-p1",
                    "processId": "p1",
                    "title": "Календарь",
                    "elements": {"workLocation": ["Outlook"], "frequency": [], "trigger": [], "steps": []},
                    "smart": {"S": "missing", "M": "missing", "A": "done", "R": "done", "T": "missing"},
                    "status": "active",
                    "sourceRefs": [],
                }
            ],
            "questionsAskedTotal": 500,
        }
    )
    estimate = pipe.get("estimatedRemainingQuestions") if isinstance(pipe.get("estimatedRemainingQuestions"), dict) else {}
    assert int(estimate.get("min") or 0) >= 0
    assert int(estimate.get("max") or 0) >= int(estimate.get("min") or 0)


def test_round_questions_hidden_before_process_selection_even_if_nested() -> None:
    from app.services.regulation_creation.interview import merge_agent_payload

    state = {
        "processes": [
            {"id": "p1", "title": "Календарь", "roleStatus": "unclear", "knownFacts": {}, "sourceRefs": []}
        ],
        "functions": [],
        "pipeline": {"stage": "select", "selectedProcessIds": []},
    }
    out = merge_agent_payload(
        state,
        {
            "status": "need_more",
            "message": "Сразу уточним детали",
            "interview": {
                "roundQuestions": [
                    {"id": "q1", "processId": "p1", "field": "trigger", "text": "Когда запускается?"}
                ]
            },
        },
    )
    assert out["pipeline"]["selectedProcessIds"] == []
    assert out["pipeline"]["roundQuestions"] == []
    assert out["pipeline"]["round"] == 0


def test_round_questions_are_filtered_to_selected_processes() -> None:
    from app.services.regulation_creation.interview import merge_agent_payload
    from app.services.regulation_creation.pipeline import select_processes

    state = {
        "processes": [
            {
                "id": "p1",
                "title": "Календарь",
                "roleStatus": "unclear",
                "knownFacts": {
                    "workLocation": "Outlook календарь",
                    "frequency": "ежедневно",
                    "trigger": "письмо от руководителя",
                    "steps": ["обновляет событие"],
                },
                "sourceRefs": [],
            },
            {"id": "p2", "title": "Отчёты", "roleStatus": "unclear", "knownFacts": {}, "sourceRefs": []},
        ],
        "functions": [],
        "pipeline": {"stage": "select", "blocks": []},
    }
    state = select_processes(state, ["p1"])
    out = merge_agent_payload(
        state,
        {
            "status": "need_more",
            "message": "Раунд 1",
            "roundQuestions": [
                {"id": "q1", "processId": "p1", "field": "trigger", "text": "Триггер по p1?"},
                {"id": "q2", "processId": "p2", "field": "trigger", "text": "Триггер по p2?"},
                {"id": "q3", "field": "steps", "text": "Общий вопрос без processId"},
            ],
        },
    )
    assert out["pipeline"]["selectedProcessIds"] == ["p1"]
    assert out["pipeline"]["round"] == 1
    assert [item["id"] for item in out["pipeline"]["roundQuestions"]] == ["q1"]
    assert {item["processId"] for item in out["pipeline"]["roundQuestions"]} == {"p1"}


def test_single_selected_process_blocks_foreign_round_questions() -> None:
    from app.services.regulation_creation.interview import merge_agent_payload
    from app.services.regulation_creation.pipeline import select_processes

    state = {
        "processes": [
            {"id": "p1", "title": "Календарь", "roleStatus": "unclear", "knownFacts": {}, "sourceRefs": []},
            {"id": "p2", "title": "Отчёты", "roleStatus": "unclear", "knownFacts": {}, "sourceRefs": []},
        ],
        "functions": [],
        "pipeline": {"stage": "select", "blocks": []},
    }
    state = select_processes(state, ["p2"])
    out = merge_agent_payload(
        state,
        {
            "status": "need_more",
            "message": "Раунд 1",
            "roundQuestions": [
                {"id": "q1", "processId": "p1", "field": "steps", "text": "Шаги по p1?"},
            ],
        },
    )
    assert out["pipeline"]["selectedProcessIds"] == ["p2"]
    assert out["pipeline"]["round"] == 0
    assert out["pipeline"]["roundQuestions"] == []


def test_round_gates_min_rounds_and_per_round_cap() -> None:
    from app.services.regulation_creation.pipeline import (
        MAX_QUESTIONS_PER_ROUND,
        apply_round_answers,
        normalize_pipeline,
        round_gate,
        start_round,
    )
    from app.services.regulation_creation.interview import ready_blocker

    pipe = normalize_pipeline(
        {
            "stage": "interview",
            "selectedProcessIds": ["p1"],
            "blocks": [
                {
                    "id": "b-p1",
                    "processId": "p1",
                    "title": "Календарь",
                    "elements": {
                        "workLocation": ["Outlook календарь"],
                        "frequency": ["ежедневно"],
                        "trigger": ["письмо от руководителя"],
                        "steps": ["обновляет событие"],
                    },
                    "smart": {"S": "done", "M": "partial", "A": "done", "R": "done", "T": "done"},
                    "status": "active",
                    "sourceRefs": [],
                }
            ],
        }
    )
    questions = [{"id": f"q{i}", "text": f"Вопрос {i}", "processId": "p1", "field": "trigger"} for i in range(60)]
    pipe = start_round(pipe, questions)
    assert len(pipe["roundQuestions"]) == MAX_QUESTIONS_PER_ROUND
    assert pipe["round"] == 1
    assert pipe["questionsAskedTotal"] == MAX_QUESTIONS_PER_ROUND
    assert round_gate(pipeline=pipe) is not None

    # Simulate 3 rounds completed with SMART still missing → still blocked
    pipe["round"] = 3
    pipe["questionsAskedTotal"] = 120
    pipe["selectedProcessIds"] = ["p1"]
    pipe["blocks"] = [
        {
            "id": "b-p1",
            "processId": "p1",
            "title": "Календарь",
            "smart": {"S": "missing", "M": "missing", "A": "missing", "R": "partial", "T": "missing"},
            "status": "active",
            "elements": {},
            "sourceRefs": [],
        }
    ]
    assert round_gate(pipeline=pipe) is not None

    # Cap reached allows assemble path when SMART closed
    pipe["questionsAskedTotal"] = 250
    pipe["blocks"][0]["smart"] = {"S": "done", "M": "done", "A": "done", "R": "done", "T": "done"}
    assert round_gate(pipeline=pipe) is None

    state = {
        "pipeline": pipe,
        "processes": [{"id": "p1", "title": "Календарь", "roleStatus": "belongs", "knownFacts": {}}],
        "functions": [
            {
                "id": "p1",
                "title": "Календарь",
                "roleStatus": "belongs",
                "tool": "Outlook",
                "periodicity": "ежедневно",
                "triggerAction": "в 9:00 появляется письмо",
                "userAction": "создаёт событие в Outlook",
                "openGaps": [],
            }
        ],
        "answers": [],
    }
    state = apply_round_answers(
        state,
        [{"questionId": "q1", "processId": "p1", "field": "trigger", "answer": "в 9:00 письмо в Outlook"}],
        free_message="Дополнительно: контроль — галочка в реестре",
    )
    assert any(item.get("source") == "user_free" for item in state["answers"])
    assert state["pipeline"]["questionnaire"].get("q1")

    blocked = ready_blocker(
        {"status": "ready"},
        {**state, "pipeline": {**normalize_pipeline(pipe), "round": 1, "questionsAskedTotal": 10}},
    )
    assert blocked is not None
    assert "минимум" in blocked.message.lower() or "раунд" in blocked.message.lower()


def test_smart_check_and_incremental_document() -> None:
    from app.services.regulation_creation.pipeline import (
        blocks_from_processes_list,
        incremental_document_from_state,
        smart_check_block,
    )

    processes = [
        {
            "id": "p1",
            "title": "Календарь",
            "actor": "Помощник",
            "roleStatus": "belongs",
            "knownFacts": {
                "steps": ["создаёт событие в Outlook"],
                "trigger": "ежедневно в 9:00",
                "workLocation": "Outlook",
                "controls": ["KPI: 100% событий создано вовремя"],
                "frequency": "ежедневно",
            },
            "sourceRefs": [],
        }
    ]
    blocks = blocks_from_processes_list(processes)
    smart = smart_check_block(blocks[0], {"processes": processes})
    assert smart["S"] == "done"
    assert smart["A"] == "done"
    assert smart["R"] == "done"
    assert smart["T"] in {"done", "partial"}
    doc = incremental_document_from_state({"processes": processes, "functions": [], "pipeline": {}})
    assert doc.get("sections")
    assert len(doc["sections"]) >= 6


def test_select_creation_processes_api_service() -> None:
    from app.services.regulation_creation.service import select_creation_processes, submit_creation_round_answers

    db = _session()
    db.add(AppUser(id="user-2", fio="Тест"))
    db.commit()
    session = start_creation_session(db, user_id="user-2")
    draft = db.query(RegulationCreationDraft).filter(RegulationCreationDraft.id == session.draftId).one()
    draft.interview_json = {
        **(draft.interview_json or {}),
        "processes": [
            {"id": "p1", "title": "Календарь", "roleStatus": "unclear", "knownFacts": {}, "sourceRefs": []},
            {"id": "p2", "title": "Отчёты", "roleStatus": "unclear", "knownFacts": {}, "sourceRefs": []},
        ],
        "pipeline": {"stage": "select", "blocks": []},
    }
    db.add(draft)
    db.commit()
    updated = select_creation_processes(db, user_id="user-2", draft_id=session.draftId, process_ids=["p1"])
    assert updated.pipeline.get("stage") == "interview"
    assert updated.pipeline.get("selectedProcessIds") == ["p1"]
    answered = submit_creation_round_answers(
        db,
        user_id="user-2",
        draft_id=session.draftId,
        answers=[{"questionId": "q1", "processId": "p1", "field": "tool", "answer": "Outlook"}],
        message="Ответы раунда",
    )
    assert answered.pipeline.get("questionnaire", {}).get("q1") == "Outlook"
    assert answered.resultDocument or answered.pipeline


def test_question_queue_prefilled_after_process_select() -> None:
    from app.services.regulation_creation.pipeline import select_processes
    from app.services.regulation_creation.question_queue import queue_depth, replenish_queue

    state = {
        "processes": [
            {
                "id": "p1",
                "title": "Календарь",
                "roleStatus": "unclear",
                "knownFacts": {},
                "sourceRefs": [],
            }
        ],
        "functions": [],
        "pipeline": {"stage": "select", "blocks": []},
    }
    out = select_processes(state, ["p1"])
    assert queue_depth(out) >= 3
    assert all(item.get("processId") == "p1" for item in out.get("questionQueue") or [])


def test_apply_collect_answer_updates_queue_without_llm() -> None:
    from app.services.regulation_creation.interview import append_user_turn, remember_assistant_question
    from app.services.regulation_creation.pipeline import select_processes
    from app.services.regulation_creation.question_queue import (
        build_fastpath_reply_from_queue,
        peek_queue_head,
        queue_depth,
        replenish_queue,
    )

    state = select_processes(
        {
            "processes": [
                {
                    "id": "p1",
                    "title": "Календарь",
                    "roleStatus": "belongs",
                    "knownFacts": {},
                    "sourceRefs": [],
                }
            ],
            "functions": [],
            "pipeline": {"stage": "select", "blocks": []},
        },
        ["p1"],
    )
    head = peek_queue_head(state)
    assert head is not None
    state, _ = remember_assistant_question(
        state,
        message=head["text"],
        quick_answers=head.get("options") or [],
        function_id=head.get("processId") or "",
        field=head.get("field") or "",
        process_id=head.get("processId") or "",
    )
    state = append_user_turn(state, "Outlook", [])
    assert state["processes"][0]["knownFacts"].get("workLocation") == "Outlook"
    state = replenish_queue(state, target=5)
    assert queue_depth(state) >= 2
    pipeline = state.get("pipeline") or {}
    reply = build_fastpath_reply_from_queue(
        interview=state,
        pipeline=pipeline,
        force_create=False,
    )
    assert reply
    assert "collect-p1-" in reply


def test_prefetch_skips_unselected_processes() -> None:
    from app.services.regulation_creation.pipeline import select_processes
    from app.services.regulation_creation.question_queue import enqueue_questions, replenish_queue

    state = select_processes(
        {
            "processes": [
                {"id": "p1", "title": "Календарь", "roleStatus": "unclear", "knownFacts": {}, "sourceRefs": []},
                {"id": "p2", "title": "Отчёты", "roleStatus": "unclear", "knownFacts": {}, "sourceRefs": []},
            ],
            "functions": [],
            "pipeline": {"stage": "select", "blocks": []},
        },
        ["p1"],
    )
    out = enqueue_questions(
        state,
        [
            {"id": "q1", "processId": "p1", "field": "trigger", "text": "Триггер p1?"},
            {"id": "q2", "processId": "p2", "field": "trigger", "text": "Триггер p2?"},
        ],
    )
    process_ids = {item.get("processId") for item in out.get("questionQueue") or []}
    assert "p2" not in process_ids
    assert "p1" in process_ids


def test_queue_dedupe_on_replenish() -> None:
    from app.services.regulation_creation.pipeline import select_processes
    from app.services.regulation_creation.question_queue import enqueue_questions, queue_depth

    state = select_processes(
        {
            "processes": [
                {"id": "p1", "title": "Календарь", "roleStatus": "unclear", "knownFacts": {}, "sourceRefs": []},
            ],
            "functions": [],
            "pipeline": {"stage": "select", "blocks": []},
        },
        ["p1"],
    )
    initial = queue_depth(state)
    duplicate = (state.get("questionQueue") or [])[0]
    out = enqueue_questions(state, [duplicate, duplicate])
    assert queue_depth(out) == initial


def test_extract_populates_deterministic_queue_without_llm() -> None:
    from app.services.regulation_creation.interview import merge_agent_payload
    from app.services.regulation_creation.question_queue import queue_depth

    state = {
        "attachments": [{"id": "f1", "name": "duties.docx", "kind": "text", "text": "Совет директоров"}],
        "processes": [],
        "functions": [],
        "pipeline": {"stage": "extract"},
    }
    payload = {
        "status": "need_more",
        "message": "Это ваша обязанность по организации заседаний Совета директоров?",
        "quickAnswers": ["Да", "Нет"],
        "interview": {
            "processes": [
                {
                    "id": "p1",
                    "title": "Организация заседаний Совета директоров",
                    "actor": "Помощник ПСД",
                    "roleStatus": "unclear",
                    "knownFacts": {},
                    "sourceRefs": [{"file": "duties.docx", "quote": "Совет директоров"}],
                },
                {
                    "id": "p2",
                    "title": "Другая функция",
                    "actor": "Помощник ПСД",
                    "roleStatus": "unclear",
                    "knownFacts": {},
                    "sourceRefs": [],
                },
            ]
        },
        "pipeline": {"stage": "interview"},
    }
    out = merge_agent_payload(state, payload)
    assert out["pipeline"]["stage"] == "select"
    assert queue_depth(out) >= 8
    assert all(item.get("source") == "collect" for item in out.get("questionQueue") or [])
    estimate = out["pipeline"].get("estimatedRemainingQuestions") or {}
    assert int(estimate.get("min") or 0) >= 8


def test_turn_payload_skips_llm_on_select_and_uses_fastpath_after_select() -> None:
    from app.services.regulation_creation.pipeline import select_processes
    from app.services.regulation_creation.question_queue import build_fastpath_reply_from_queue

    state = select_processes(
        {
            "processes": [
                {
                    "id": "p1",
                    "title": "Календарь",
                    "roleStatus": "unclear",
                    "knownFacts": {},
                    "sourceRefs": [],
                }
            ],
            "functions": [],
            "pipeline": {"stage": "select", "blocks": []},
        },
        ["p1"],
    )
    pipeline = state.get("pipeline") or {}
    reply = build_fastpath_reply_from_queue(interview=state, pipeline=pipeline, force_create=False)
    assert reply
    assert "collect-p1-" in reply


def test_extract_does_not_surface_llm_message_as_question() -> None:
    from app.models.regulation import RegulationCreationMessage

    db = _session()
    user = AppUser(id="user-extract", fio="Extract User", position="промпт-инженер 2 категории")
    db.add(user)
    db.commit()
    session = start_creation_session(db, user_id=user.id)
    draft = db.query(RegulationCreationDraft).filter(RegulationCreationDraft.id == session.draftId).one()
    payload = {
        "status": "need_more",
        "message": (
            "В приложенном документе организация подготовки заседаний Совета директоров "
            "отнесена к Помощнику ПСД. Эта работа входит в ваши обязанности как промпт-инженера 2 категории?"
        ),
        "quickAnswers": ["Да", "Нет"],
        "interview": {
            "processes": [
                {
                    "id": "p1",
                    "title": "Организация заседаний Совета директоров",
                    "actor": "Помощник ПСД",
                    "roleStatus": "unclear",
                    "knownFacts": {},
                    "sourceRefs": [],
                }
            ]
        },
        "pipeline": {"stage": "interview"},
    }
    _apply_agent_reply(
        db,
        user_id=user.id,
        draft=draft,
        raw=json.dumps(payload, ensure_ascii=False),
    )
    db.commit()
    messages = [
        item.content
        for item in db.query(RegulationCreationMessage)
        .filter(RegulationCreationMessage.draft_id == draft.id, RegulationCreationMessage.role == "assistant")
        .all()
    ]
    assert messages
    assert payload["message"] not in messages[-1]
    assert "Отметьте" in messages[-1] or "выделить процессы" in messages[-1]


def test_ownership_question_is_deterministic_template() -> None:
    from app.services.regulation_creation.question_queue import all_ownership_questions, populate_queue_after_extract

    state = set_interview_position(
        {
            "processes": [
                {
                    "id": "p1",
                    "title": "Организация заседаний Совета директоров",
                    "actor": "Помощник ПСД",
                    "roleStatus": "unclear",
                    "knownFacts": {},
                    "sourceRefs": [],
                }
            ],
            "pipeline": {"stage": "select", "blocks": []},
        },
        "промпт-инженер 2 категории",
    )
    ownership = all_ownership_questions(state, all_candidates=True)
    assert len(ownership) == 1
    item = ownership[0]
    assert item["source"] == "ownership"
    assert item["field"] == "roleStatus"
    assert "Помощник ПСД" in item["text"]
    assert "промпт-инженер 2 категории" in item["text"]
    assert "ownership-p1" == item["id"]

    out = populate_queue_after_extract(state)
    queue = out.get("questionQueue") or []
    assert any(entry.get("source") == "ownership" for entry in queue)


def test_no_sdk_invoke_during_collect_with_nonempty_queue() -> None:
    from app.services.regulation_creation.pipeline import select_processes
    from app.services.regulation_creation.service import _turn_payload

    db = _session()
    user = AppUser(id="user-queue", fio="Queue User", position="Помощник ПСД")
    db.add(user)
    db.commit()
    state = select_processes(
        {
            "position": "Помощник ПСД",
            "processes": [
                {
                    "id": "p1",
                    "title": "Календарь",
                    "roleStatus": "belongs",
                    "knownFacts": {},
                    "sourceRefs": [],
                }
            ],
            "functions": [],
            "pipeline": {"stage": "select", "blocks": []},
        },
        ["p1"],
    )
    draft = RegulationCreationDraft(id="draft-queue-1", user_id=user.id, status="interview", interview_json=state)
    db.add(draft)
    db.commit()
    turn = _turn_payload(db, draft, message="", force_create=False)
    assert not turn.sdkPrompt.strip()
    assert turn.prefetchedReply
    assert turn.queueDepth >= 1


def test_extract_with_blocks_only_forces_select_and_syncs_processes() -> None:
    from app.services.regulation_creation.interview import merge_agent_payload

    state = {
        "attachments": [{"id": "f1", "name": "duties.txt", "kind": "text", "text": "Календарь"}],
        "processes": [],
        "functions": [],
        "pipeline": {"stage": "extract"},
    }
    payload = {
        "status": "need_more",
        "message": "Сразу задаю вопрос по регламенту",
        "pipeline": {
            "stage": "interview",
            "blocks": [{"id": "b-p1", "processId": "p1", "title": "Календарь"}],
        },
    }
    out = merge_agent_payload(state, payload)
    assert out["pipeline"]["stage"] == "select"
    assert out["pipeline"]["selectedProcessIds"] == []
    assert not out.get("currentQuestion")
    assert any(item.get("id") == "p1" for item in out.get("processes") or [])


def test_extract_with_candidates_has_no_current_question() -> None:
    from app.services.regulation_creation.interview import merge_agent_payload

    state = {
        "attachments": [{"id": "f1", "name": "duties.txt", "kind": "text", "text": "Совет директоров"}],
        "processes": [],
        "functions": [],
        "pipeline": {"stage": "extract"},
    }
    payload = {
        "status": "need_more",
        "message": "Это ваша обязанность?",
        "interview": {
            "processes": [
                {
                    "id": "p1",
                    "title": "Организация заседаний",
                    "actor": "Помощник ПСД",
                    "roleStatus": "unclear",
                    "knownFacts": {},
                    "sourceRefs": [],
                }
            ]
        },
        "pipeline": {"stage": "interview"},
    }
    out = merge_agent_payload(state, payload)
    assert out["pipeline"]["stage"] == "select"
    assert out["pipeline"]["interviewPhase"] == "select"
    assert not out.get("currentQuestion")


def test_turn_payload_blocks_fastpath_before_process_selection() -> None:
    from app.services.regulation_creation.service import _turn_payload

    db = _session()
    user = AppUser(id="user-select-block", fio="Select User", position="Инженер")
    db.add(user)
    db.commit()
    draft = RegulationCreationDraft(
        id="draft-select-block",
        user_id=user.id,
        status="interview",
        interview_json={
            "position": "Инженер",
            "processes": [
                {
                    "id": "p1",
                    "title": "Календарь",
                    "roleStatus": "unclear",
                    "knownFacts": {},
                    "sourceRefs": [],
                }
            ],
            "pipeline": {"stage": "select", "blocks": [{"id": "b-p1", "processId": "p1", "title": "Календарь"}]},
        },
    )
    db.add(draft)
    db.commit()
    turn = _turn_payload(db, draft, message="", force_create=False)
    assert not turn.prefetchedReply
    assert not turn.sdkPrompt.strip()
