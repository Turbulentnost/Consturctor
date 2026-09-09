from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.regulation import RegulationCreationDraft
from app.models.user import AppUser
from app.services.regulation_creation.interview import (
    append_user_turn,
    build_creation_prompt,
    build_followup_creation_prompt,
    creation_interviewer_rules,
    document_from_interview,
    interview_progress,
    interview_write_document,
    interview_use_tools,
    leading_question_text,
    set_sdk_agent_id,
    document_has_full_text,
    is_process_select_message,
    is_replacement_garbage,
    merge_agent_payload,
    parse_selected_process_ids,
    question_for_selected_processes,
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
    list_creation_sessions,
    persist_creation_turn,
    resume_creation_session,
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
    assert "inputs" in prompt
    assert "deadlines" in prompt
    assert "workLocation" in prompt
    assert "steps" in prompt
    assert "это не лимит в N вопросов" in prompt
    assert "Не злоупотребляй" in prompt
    assert "interview.processes" in prompt
    assert "answerSufficiency" in prompt
    assert "nextQuestion" in prompt
    assert "самостоятельный регламент процесса" in prompt


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


def test_process_select_message_accepts_mark_process_numbers() -> None:
    assert is_process_select_message(
        "Отметьте номера процессов, которые вы сами выполняете на этой должности"
    )
    assert is_process_select_message("Отметьте нужные процессы из списка")
    assert not is_process_select_message("В какой системе вы готовите повестку?")


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


def test_outlook_calendar_closes_work_location() -> None:
    payload = _ready_payload(
        {
            "id": "f1",
            "title": "Организация заседаний Совета директоров",
            "actor": "Помощник ПСД",
            "roleStatus": "belongs",
            "tool": "MS Outlook, вкладка Календарь: смотрит загруженность сотрудника",
            "periodicity": "",
            "triggerAction": "",
            "userAction": "",
        }
    )
    state = merge_agent_payload({}, payload)

    blocker = ready_blocker(payload, state)

    assert "tool" not in state["functions"][0]["openGaps"]
    assert blocker is not None
    assert blocker.field == "periodicity"


def test_ready_with_critical_process_unknown_is_blocked() -> None:
    payload = {
        "status": "ready",
        "message": "Готово",
        "interview": {
            "functions": [
                {
                    "id": "f1",
                    "title": "Организация заседаний СД",
                    "actor": "Помощник ПСД",
                    "roleStatus": "belongs",
                    "tool": "MS Outlook, вкладка Календарь: смотрит загруженность сотрудника",
                    "periodicity": "Перед каждым заседанием",
                    "triggerAction": "Согласована повестка заседания",
                    "userAction": "Создает событие в календаре Outlook",
                }
            ],
            "processes": [
                {
                    "id": "f1",
                    "title": "Организация заседаний СД",
                    "roleStatus": "belongs",
                    "knownFacts": {
                        "workLocation": "MS Outlook, вкладка Календарь",
                        "frequency": "Перед каждым заседанием",
                        "trigger": "Согласована повестка заседания",
                        "steps": ["Создает событие в календаре Outlook"],
                    },
                    "unknowns": [
                        {
                            "field": "outputs",
                            "reason": "Неясно, какой результат должен быть подтвержден после планирования.",
                            "critical": True,
                        }
                    ],
                }
            ],
        },
        "document": {
            "title": "Регламент",
            "sections": [
                {
                    "title": "Организация заседаний",
                    "paragraphs": [
                        (
                            "Процесс нужен для подготовки заседания Совета директоров и фиксации "
                            "планируемого события в календаре организации."
                        ),
                        (
                            "После согласования повестки пользователь открывает календарь Outlook "
                            "и создает событие для дальнейшего согласования участников."
                        ),
                    ],
                    "items": [],
                }
            ],
        },
    }
    state = merge_agent_payload({}, payload)

    blocker = ready_blocker(payload, state)

    assert blocker is not None
    assert blocker.field == "outputs"
    assert "что пользователь делает" in blocker.message


def test_partial_answer_records_sufficiency_without_backend_question() -> None:
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

    assert state["answerSufficiency"]["status"] == "partial"
    assert state["askedQuestions"][-1]["sufficiency"] == "partial"


def test_apply_agent_reply_keeps_sdk_need_more_question() -> None:
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
                "message": "Кого пользователь добавляет в приглашение Outlook и какой результат должен получить?",
                "nextQuestion": {
                    "processId": "f1",
                    "targetFact": "steps",
                    "alreadyKnown": ["Место работы: 1С"],
                    "missingFact": "кого добавляют в приглашение и какой результат создается",
                    "whyThisQuestion": "Без этого нельзя описать действие пользователя.",
                    "text": "Кого пользователь добавляет в приглашение и какой результат должен получить?",
                },
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
    assert message.content == "Кого пользователь добавляет в приглашение и какой результат должен получить?"
    assert not message.structured_json.get("blockedReady")
    assert draft.interview_json["currentQuestion"]["field"] == "userAction"


def test_repeated_question_is_recorded_without_rewriting_sdk_text() -> None:
    question = "В какой системе вы проверяете комплектность материалов?"
    state, first = remember_assistant_question({}, message=question, function_id="f1", field="tool")
    state, second = remember_assistant_question(state, message=question, function_id="f1", field="tool")

    assert first == question
    assert second == question
    assert state["askedQuestions"][-1]["duplicate"] is True


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
    assert document["sections"][0]["title"] == "Сводка на неделю"
    assert any("Excel" in item for item in document["sections"][0]["items"])


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


def test_creation_history_is_sorted_by_updated_at() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    now = datetime.now(timezone.utc)
    older = RegulationCreationDraft(
        id="draft-old",
        user_id="user-1",
        status="closed",
        interview_json={"functions": [{"id": "f1", "title": "Старый процесс"}]},
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    newer = RegulationCreationDraft(
        id="draft-new",
        user_id="user-1",
        status="interview",
        draft_document_json={"title": "Новый регламент"},
        created_at=now - timedelta(days=1),
        updated_at=now,
    )
    db.add_all([older, newer])
    db.commit()

    history = list_creation_sessions(db, user_id="user-1")

    assert [item.draftId for item in history.items] == ["draft-new", "draft-old"]
    assert history.items[0].title == "Новый регламент"
    assert history.items[1].title == "Старый процесс"
    assert history.items[0].canContinue is True


def test_creation_history_marks_finalized_as_not_continueable() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(
        id="draft-final",
        user_id="user-1",
        status="finalized",
        result_regulation_id="reg-1",
        draft_document_json={"title": "Готовый регламент"},
    )
    db.add(draft)
    db.commit()

    history = list_creation_sessions(db, user_id="user-1")

    assert history.items[0].draftId == "draft-final"
    assert history.items[0].hasResult is True
    assert history.items[0].canContinue is False


def test_resume_closed_creation_session_clears_archived_sdk_agent() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    draft = RegulationCreationDraft(
        id="draft-closed",
        user_id="user-1",
        status="closed",
        cursor_agent_id="agent-archived",
        latest_run_id="run-archived",
        interview_json={"sdk_agent_id": "agent-archived", "functions": []},
    )
    db.add(draft)
    db.commit()

    session = resume_creation_session(db, user_id="user-1", draft_id="draft-closed")

    db.refresh(draft)
    assert session.draftId == "draft-closed"
    assert session.status == "interview"
    assert draft.cursor_agent_id == ""
    assert draft.latest_run_id == ""
    assert session.sdkAgentId == ""


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


def test_leading_question_text_keeps_prose_before_json() -> None:
    assert leading_question_text(
        "В какой системе вы смотрите календарь?\n\n"
        '{"status":"need_more","message":"В какой системе вы смотрите календарь?"}'
    ) == "В какой системе вы смотрите календарь?"
    assert leading_question_text('{"status":"need_more","message":"Вопрос"}') == ""


def test_parse_agent_response_reads_prose_then_json() -> None:
    parsed = _parse_agent_response(
        "В какой системе вы смотрите календарь?\n"
        '{"status":"need_more","message":"","quickAnswers":["Outlook"]}'
    )
    assert parsed["status"] == "need_more"
    assert parsed["message"] == "В какой системе вы смотрите календарь?"
    assert parsed["quickAnswers"] == ["Outlook"]


def test_parse_agent_response_accepts_question_status() -> None:
    parsed = _parse_agent_response(
        '{"status":"question","message":"В каком разделе 1С?","quickAnswers":["Документы"]}'
    )
    assert parsed["status"] == "need_more"
    assert parsed["message"] == "В каком разделе 1С?"
    assert parsed["quickAnswers"] == ["Документы"]


def test_followup_prompt_asks_for_plain_question_first() -> None:
    prompt = build_followup_creation_prompt(
        message="Outlook, календарь",
        force_create=False,
        state={"selectedProcessIds": ["p1"], "position": "Помощник"},
    )
    rules = creation_interviewer_rules()
    assert "Не начинай ответ с фигурной скобки" in prompt
    assert "Не начинай ответ с фигурной скобки" in rules
    assert "только текст следующего вопроса" in prompt
    assert "без инструментов" in prompt
    assert "текущему незакрытому процессу" in prompt
    assert "Не читай interview.json" in prompt
    assert "selectedProcessIds" in prompt
    assert "строго по одному текущему процессу" in rules
    assert "Прочитай обновлённый interview.json" not in prompt
    assert not interview_write_document({"selectedProcessIds": ["p1"]})
    assert interview_write_document({"document_write_required": True})
    assert interview_write_document({}, force_create=True)
    assert interview_use_tools(
        {
            "attachments": [{"name": "a.txt", "text": "Календарь"}],
            "processes": [],
        }
    )
    assert not interview_use_tools(
        {
            "attachments": [{"name": "a.txt", "text": "Календарь"}],
            "processes": [{"id": "p1", "title": "Календарь"}],
            "sdk_agent_id": "local-1",
        }
    )
    assert interview_use_tools(
        {"processes": [{"id": "p1", "title": "Календарь"}], "sdk_agent_id": "local-1"},
        new_attachments=True,
    )
    assert interview_use_tools({}, force_create=True)


def test_followup_turn_uses_short_interviewer_rules() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    db.commit()
    session = start_creation_session(db, user_id="user-1")
    draft = db.get(RegulationCreationDraft, session.draftId)
    assert draft is not None
    draft.interview_json = set_sdk_agent_id(draft.interview_json, "local-agent-1")
    db.add(draft)
    db.commit()
    turn = persist_creation_turn(
        db,
        user_id="user-1",
        draft_id=session.draftId,
        request=RegulationCreationSendRequest(message="Смотрю календарь в Outlook"),
    )
    assert turn.sdkAgentId == "local-agent-1"
    assert turn.writeDocument is False
    assert turn.useTools is False
    assert "Не начинай ответ с фигурной скобки" in turn.sdkRules
    assert "только текст вопроса" in turn.sdkRules
    assert "Ответ всегда строго JSON" not in turn.sdkRules
    assert turn.sdkPrompt.startswith("Продолжи то же интервью текстом, без инструментов")
    assert "Не читай interview.json" in turn.sdkPrompt
    assert "без инструментов" in turn.sdkRules


def test_first_file_turn_enables_read_tools() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    db.commit()
    session = start_creation_session(db, user_id="user-1")
    turn = persist_creation_turn(
        db,
        user_id="user-1",
        draft_id=session.draftId,
        request=RegulationCreationSendRequest(message="Разбери файл"),
        files=[("duties.txt", "Пользователь ведет календарь совещаний.".encode("utf-8"))],
    )
    assert turn.useTools is True
    assert turn.writeDocument is False
    assert "materials/" in turn.sdkPrompt
    assert "Пользователь ведет календарь совещаний." not in turn.sdkPrompt
    assert "без инструментов" not in turn.sdkRules


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


def test_parse_selected_process_ids_normalizes_block_ids() -> None:
    assert parse_selected_process_ids(
        "Выбраны процессы: b-p5\n- b-p5: Ведение тем совещаний"
    ) == ["p5"]
    assert parse_selected_process_ids("Выбраны процессы: p1, p4") == ["p1", "p4"]
    assert parse_selected_process_ids("Это не выбор процессов") == []


def test_normalize_recovers_selected_ids_from_turns() -> None:
    state = merge_agent_payload(
        {
            "turns": [
                {
                    "role": "user",
                    "message": "Выбраны процессы: b-p5\n- b-p5: Ведение тем",
                    "attachments": [],
                }
            ]
        },
        {},
    )
    assert state["selectedProcessIds"] == ["p5"]


def test_append_user_turn_stores_selected_process_ids() -> None:
    state = append_user_turn({}, "Выбраны процессы: b-p5\n- b-p5: Ведение тем", [])
    assert state["selectedProcessIds"] == ["p5"]
    prompt = build_creation_prompt(
        state=state,
        message="Выбраны процессы: b-p5",
        initial=False,
        force_create=False,
    )
    assert "selectedProcessIds" in prompt
    assert "не проси отметить процессы снова" in prompt.casefold()
    assert "pipeline.stage='select'" in prompt


def test_apply_agent_reply_rewrites_select_after_choice() -> None:
    from app.models.regulation import RegulationCreationMessage

    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    state = append_user_turn(
        {
            "processes": [
                {
                    "id": "p4",
                    "title": "Ведение тем регулярных совещаний",
                    "roleStatus": "belongs",
                    "knownFacts": {},
                    "unknowns": [
                        {
                            "field": "trigger",
                            "question": "Что запускает ведение тем?",
                            "critical": True,
                        }
                    ],
                }
            ]
        },
        "Выбраны процессы: p4\n- p4: Ведение тем регулярных совещаний",
        [],
    )
    draft = RegulationCreationDraft(
        id="draft-select-after-choice",
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
                "message": (
                    "Из документа извлечены процессы. Отметьте нужные — дальше спрошу "
                    "только то, чего не удалось однозначно взять из текста документа."
                ),
                "pipeline": {"stage": "select"},
                "quickAnswers": ["p4"],
            },
            ensure_ascii=False,
        ),
    )
    db.commit()

    message = (
        db.query(RegulationCreationMessage)
        .filter(RegulationCreationMessage.draft_id == "draft-select-after-choice")
        .one()
    )
    text = message.content.casefold()
    assert "отметьте" not in text
    assert "извлечены процессы" not in text
    assert "ведение тем" in text or "запускает" in text
    assert (message.structured_json.get("pipeline") or {}).get("stage") == "questions"
    assert draft.interview_json["selectedProcessIds"] == ["p4"]


def test_interview_progress_starts_on_first_selected_process() -> None:
    progress = interview_progress(
        {
            "selectedProcessIds": ["p1", "p2"],
            "processes": [
                {
                    "id": "p1",
                    "title": "Подготовка к Совету",
                    "roleStatus": "belongs",
                    "knownFacts": {},
                    "unknowns": [],
                },
                {
                    "id": "p2",
                    "title": "Протокол",
                    "roleStatus": "belongs",
                    "knownFacts": {},
                    "unknowns": [],
                },
            ],
        }
    )
    assert progress["visible"] is True
    assert progress["currentProcessId"] == "p1"
    assert progress["currentProcessIndex"] == 1
    assert progress["processCount"] == 2
    assert progress["currentProcessTitle"] == "Подготовка к Совету"
    assert progress["remaining"] >= 5
    assert progress["answered"] == 0
    assert progress["total"] == progress["answered"] + progress["remaining"]


def test_interview_progress_moves_to_second_process_when_first_closed() -> None:
    closed_facts = {
        "inputs": ["повестка Совета"],
        "outputs": ["пакет к заседанию"],
        "deadlines": "за двое суток до Совета",
        "workLocation": "1С ERP, раздел Задачи директорам",
        "frequency": "перед каждым Советом директоров",
        "steps": ["открыть раздел", "поставить задачи директорам и главным бухгалтерам"],
    }
    progress = interview_progress(
        {
            "selectedProcessIds": ["p1", "p2"],
            "processes": [
                {
                    "id": "p1",
                    "title": "Подготовка к Совету",
                    "roleStatus": "belongs",
                    "knownFacts": closed_facts,
                    "unknowns": [],
                },
                {
                    "id": "p2",
                    "title": "Протокол",
                    "roleStatus": "belongs",
                    "knownFacts": {"workLocation": "Word, файл протокола"},
                    "unknowns": [{"field": "inputs", "reason": "неясен вход", "critical": True}],
                },
            ],
        }
    )
    assert progress["currentProcessId"] == "p2"
    assert progress["currentProcessIndex"] == 2
    assert progress["answered"] >= 5
    assert progress["remaining"] >= 1
    assert progress["remaining"] < progress["total"]


def test_merge_closes_fact_and_reduces_remaining_progress() -> None:
    state = {
        "selectedProcessIds": ["p1"],
        "position": "Помощник",
        "processes": [
            {
                "id": "p1",
                "title": "Темы совещаний",
                "roleStatus": "belongs",
                "knownFacts": {
                    "outputs": ["тема в 1С"],
                    "deadlines": "в день поручения",
                    "workLocation": "1С ERP, раздел Темы совещаний",
                    "frequency": "по мере поручений",
                    "steps": ["открыть раздел", "завести тему"],
                },
                "unknowns": [{"field": "inputs", "reason": "неясен вход", "critical": True}],
            }
        ],
        "currentQuestion": {
            "id": "q1",
            "processId": "p1",
            "field": "inputs",
            "message": "Откуда приходит запрос?",
            "answer": "Служебная записка в 1С и устное поручение",
        },
        "askedQuestions": [],
        "answers": [],
    }
    before = interview_progress(state)
    assert before["remaining"] == 1
    merged = merge_agent_payload(
        state,
        {
            "status": "need_more",
            "answerSufficiency": {
                "status": "closed",
                "processId": "p1",
                "field": "inputs",
                "answerSummary": "Служебная записка в 1С и устное поручение",
            },
            "nextQuestion": {
                "processId": "p1",
                "targetFact": "steps",
                "text": "Уточните порядок статусов темы",
            },
            "interview": {"processes": [{"id": "p1", "title": "Темы совещаний"}]},
        },
    )
    after = interview_progress(merged)
    assert "Служебная записка в 1С и устное поручение" in (
        merged["processes"][0]["knownFacts"].get("inputs") or []
    )
    assert after["remaining"] == 0
    assert after["answered"] == after["total"]


def test_merge_closes_previous_fact_when_next_target_changes() -> None:
    state = {
        "selectedProcessIds": ["p1"],
        "processes": [
            {
                "id": "p1",
                "title": "Темы совещаний",
                "roleStatus": "belongs",
                "knownFacts": {
                    "outputs": ["тема в 1С"],
                    "deadlines": "в день поручения",
                    "workLocation": "1С ERP, раздел Темы совещаний",
                    "frequency": "по мере поручений",
                    "steps": ["завести тему"],
                },
                "unknowns": [],
            }
        ],
        "currentQuestion": {
            "id": "q2",
            "processId": "p1",
            "field": "inputs",
            "answer": "Только служебная записка в 1С",
        },
        "askedQuestions": [],
        "answers": [],
    }
    merged = merge_agent_payload(
        state,
        {
            "status": "need_more",
            "nextQuestion": {
                "processId": "p1",
                "targetFact": "frequency",
                "text": "Как часто?",
            },
        },
    )
    assert merged["processes"][0]["knownFacts"]["inputs"] == ["Только служебная записка в 1С"]
    assert interview_progress(merged)["remaining"] == 0


def test_process_display_title_hides_internal_ids() -> None:
    from app.services.regulation_creation.interview import _process_display_title

    assert (
        _process_display_title({"id": "f6", "title": "f6"}, index=6) == "Процесс 6"
    )
    assert (
        _process_display_title(
            {
                "id": "f6",
                "title": "f6",
                "knownFacts": {"steps": ["Снять документ с контроля"]},
            },
            index=6,
        )
        == "Снять документ с контроля"
    )
    state = {
        "selectedProcessIds": ["f6"],
        "processes": [
            {
                "id": "f6",
                "title": "Контроль поручений",
                "roleStatus": "unclear",
                "knownFacts": {},
                "unknowns": [],
            }
        ],
    }
    merged = merge_agent_payload(
        state,
        {"interview": {"processes": [{"id": "f6", "title": "f6", "roleStatus": "unclear"}]}},
    )
    assert merged["processes"][0]["title"] == "Контроль поручений"
    progress = interview_progress(merged)
    assert progress["currentProcessTitle"] == "Контроль поручений"
    blocker = question_for_selected_processes(merged)
    assert blocker is not None
    assert "f6" not in blocker.message
    assert "Контроль поручений" in blocker.message


def test_quick_answers_has_no_system_defaults() -> None:
    from app.services.regulation_creation.service import _quick_answers

    assert _quick_answers(None) == []
    assert _quick_answers([]) == []
    assert _quick_answers(["Оставить", "В 1С ERP, раздел Темы"]) == ["В 1С ERP, раздел Темы"]


def test_gap_constatation_becomes_question() -> None:
    from app.services.regulation_creation.interview import _question_message_for_process_gap
    from app.services.regulation_creation.service import _should_replace_with_gap_question

    statement = (
        "По процессу «Подготовка заседаний Совета директоров»: "
        "срок рассылки материалов упомянут в приёмке, но конкретный срок в тексте не раскрыт"
    )
    assert _should_replace_with_gap_question(statement) is True
    asked = _question_message_for_process_gap(
        title="Подготовка заседаний Совета директоров",
        field="deadlines",
        hint="срок рассылки материалов упомянут в приёмке, но конкретный срок в тексте не раскрыт",
    )
    assert "?" in asked
    assert "Уточните" in asked or "Как это устроено" in asked

    blocker = question_for_selected_processes(
        {
            "selectedProcessIds": ["p2"],
            "position": "Секретарь",
            "processes": [
                {
                    "id": "p2",
                    "title": "Подготовка заседаний Совета директоров",
                    "roleStatus": "belongs",
                    "knownFacts": {},
                    "unknowns": [
                        {
                            "field": "deadlines",
                            "critical": True,
                            "reason": (
                                "срок рассылки материалов упомянут в приёмке, "
                                "но конкретный срок в тексте не раскрыт"
                            ),
                        }
                    ],
                }
            ],
        }
    )
    assert blocker is not None
    assert "?" in blocker.message
    assert "не раскрыт" in blocker.message.lower()
    assert blocker.message.rstrip().endswith("?")


def test_foreign_role_answer_marks_process_and_skips_it() -> None:
    state = {
        "selectedProcessIds": ["f5", "f6"],
        "position": "Помощник",
        "processes": [
            {
                "id": "f5",
                "title": "Календарь",
                "roleStatus": "belongs",
                "knownFacts": {
                    "inputs": ["запрос"],
                    "outputs": ["событие"],
                    "deadlines": "в день",
                    "workLocation": "Outlook, календарь",
                    "frequency": "по запросу",
                    "steps": ["создать событие"],
                },
                "unknowns": [],
            },
            {
                "id": "f6",
                "title": "Контроль сроков входящих",
                "roleStatus": "unclear",
                "knownFacts": {},
                "unknowns": [],
            },
        ],
        "functions": [],
        "currentQuestion": {
            "id": "q9",
            "processId": "f6",
            "field": "roleStatus",
            "message": "Процесс относится к вашей должности?",
        },
        "askedQuestions": [],
        "answers": [],
    }
    updated = append_user_turn(state, "Нет, другая роль", [])
    assert updated["processes"][1]["roleStatus"] == "foreign"
    assert updated["processes"][1]["roleConfirmedByUser"] is True
    assert "f6" not in updated["selectedProcessIds"]
    assert question_for_selected_processes(updated) is None

    merged = merge_agent_payload(
        updated,
        {
            "status": "need_more",
            "interview": {
                "processes": [
                    {
                        "id": "f6",
                        "title": "Контроль сроков входящих",
                        "roleStatus": "unclear",
                    }
                ]
            },
            "nextQuestion": {
                "processId": "f6",
                "targetFact": "roleStatus",
                "text": "Процесс относится к вашей должности?",
            },
        },
    )
    assert merged["processes"][1]["roleStatus"] == "foreign"
    progress = interview_progress(merged)
    assert progress["currentProcessId"] != "f6"


def test_apply_replaces_status_statement_with_gap_question() -> None:
    from app.models.regulation import RegulationCreationMessage

    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    db.add(
        RegulationCreationDraft(
            id="draft-status-stmt",
            user_id="user-1",
            status="interview",
            interview_json={
                "selectedProcessIds": ["p5"],
                "processes": [
                    {
                        "id": "p5",
                        "title": "Ведение тем совещаний",
                        "roleStatus": "belongs",
                        "knownFacts": {
                            "inputs": ["поручение"],
                            "outputs": ["тема в 1С"],
                            "deadlines": "в день смены",
                            "workLocation": "1С ERP, раздел Темы совещаний",
                            "frequency": "по мере поручений",
                        },
                        "unknowns": [],
                    }
                ],
            },
        )
    )
    db.commit()
    draft = db.get(RegulationCreationDraft, "draft-status-stmt")
    assert draft is not None
    _apply_agent_reply(
        db,
        user_id="user-1",
        draft=draft,
        raw=json.dumps(
            {
                "status": "need_more",
                "message": (
                    "Срок правки темы зафиксирован; по ведению тем в 1C ERP больше нет пробелов "
                    "по входам, выходам, срокам, месту работы и частоте."
                ),
                "quickAnswers": [],
                "nextQuestion": {
                    "processId": "p5",
                    "targetFact": "steps",
                    "text": "Срок правки темы зафиксирован; по ведению тем больше нет пробелов.",
                },
            },
            ensure_ascii=False,
        ),
    )
    db.commit()
    message = (
        db.query(RegulationCreationMessage)
        .filter(RegulationCreationMessage.draft_id == "draft-status-stmt")
        .order_by(RegulationCreationMessage.created_at.desc())
        .first()
    )
    assert message is not None
    assert "последовательность действий" in message.content.lower() or "не видно" in message.content.lower()
    assert "больше нет пробелов" not in message.content.lower()
    assert message.structured_json.get("quickAnswers") == []


def test_session_exposes_interview_progress() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    db.commit()
    session = start_creation_session(db, user_id="user-1")
    draft = db.get(RegulationCreationDraft, session.draftId)
    assert draft is not None
    draft.interview_json = {
        "selectedProcessIds": ["p1"],
        "processes": [
            {
                "id": "p1",
                "title": "Календарь",
                "roleStatus": "belongs",
                "knownFacts": {},
                "unknowns": [],
            }
        ],
    }
    db.add(draft)
    db.commit()
    latest = get_active_creation_session(db, user_id="user-1")
    assert latest is not None
    assert latest.progress.visible is True
    assert latest.progress.currentProcessId == "p1"
    assert latest.progress.remaining >= 1


def test_apply_agent_reply_keeps_current_process_question() -> None:
    from app.models.regulation import RegulationCreationMessage

    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    db.add(
        RegulationCreationDraft(
            id="draft-progress-order",
            user_id="user-1",
            status="interview",
            interview_json={
                "selectedProcessIds": ["p1", "p2"],
                "processes": [
                    {
                        "id": "p1",
                        "title": "Подготовка к Совету",
                        "roleStatus": "belongs",
                        "knownFacts": {},
                        "unknowns": [],
                    },
                    {
                        "id": "p2",
                        "title": "Протокол",
                        "roleStatus": "belongs",
                        "knownFacts": {},
                        "unknowns": [],
                    },
                ],
            },
        )
    )
    db.commit()
    draft = db.get(RegulationCreationDraft, "draft-progress-order")
    assert draft is not None
    _apply_agent_reply(
        db,
        user_id="user-1",
        draft=draft,
        raw=json.dumps(
            {
                "status": "need_more",
                "message": "Как вы оформляете протокол после Совета?",
                "quickAnswers": ["В Word", "В 1С"],
                "nextQuestion": {
                    "processId": "p2",
                    "field": "steps",
                    "text": "Как вы оформляете протокол после Совета?",
                },
            },
            ensure_ascii=False,
        ),
    )
    db.commit()
    message = (
        db.query(RegulationCreationMessage)
        .filter(RegulationCreationMessage.draft_id == "draft-progress-order")
        .order_by(RegulationCreationMessage.created_at.desc())
        .first()
    )
    assert message is not None
    text = message.content.casefold()
    assert "протокол после совета" not in text
    assert "подготовк" in text or "запускает" in text or "шаги" in text or "где" in text
    progress = interview_progress(draft.interview_json)
    assert progress["currentProcessId"] == "p1"
    current = (draft.interview_json or {}).get("currentQuestion") or {}
    assert str(current.get("processId") or current.get("functionId") or "") == "p1"
