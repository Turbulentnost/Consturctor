from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import regulation as _regulation_models  # noqa: F401
from app.models import user as _user_models  # noqa: F401
from app.models.regulation import RegulationDocument, RoleMatchRun
from app.schemas.regulation import (
    FunctionActor,
    MatchEvidence,
    RegulationFragment,
    RegulationParseResult,
    RoleFunction,
    RoleMatchResult,
    RoleProfile,
    QuestionChatSendRequest,
)
from app.services.agents import create_or_get_draft, delete_draft, ensure_draft_readiness, list_drafts
from app.services.readiness.chat import create_or_get_question_chat, send_question_chat_message


def test_agent_draft_created_once_and_user_scoped() -> None:
    db = _memory_session()
    _seed_role_run(db, user_id="user-1", regulation_id="reg-1", run_id="run-1")
    _seed_role_run(db, user_id="user-2", regulation_id="reg-2", run_id="run-2")

    first = create_or_get_draft(db, user_id="user-1", regulation_id="reg-1", role_match_run_id="run-1")
    second = create_or_get_draft(db, user_id="user-1", regulation_id="reg-1", role_match_run_id="run-1")

    assert first.draftId == second.draftId
    assert [item.draftId for item in list_drafts(db, user_id="user-1").items] == [first.draftId]
    assert list_drafts(db, user_id="user-2").items == []

    delete_draft(db, user_id="user-1", draft_id=first.draftId)
    assert list_drafts(db, user_id="user-1").items == []


def test_question_chat_incomplete_then_complete_answer_creates_change() -> None:
    db = _memory_session()
    _seed_role_run(db, user_id="user-1", regulation_id="reg-1", run_id="run-1")
    draft = create_or_get_draft(db, user_id="user-1", regulation_id="reg-1", role_match_run_id="run-1")
    draft = ensure_draft_readiness(db, user_id="user-1", draft_id=draft.draftId)
    assert draft.readiness is not None
    question_id = draft.readiness.questions[0].questionId

    chat = create_or_get_question_chat(db, user_id="user-1", draft_id=draft.draftId, question_id=question_id)
    assert chat.context["question"]["questionId"] == question_id
    assert chat.messages[0].role == "assistant"

    chat = send_question_chat_message(
        db,
        user_id="user-1",
        draft_id=draft.draftId,
        question_id=question_id,
        request=QuestionChatSendRequest(message="не знаю"),
    )
    assert chat.status == "needs_clarification"
    assert chat.messages[-1].structured["isComplete"] is False

    chat = send_question_chat_message(
        db,
        user_id="user-1",
        draft_id=draft.draftId,
        question_id=question_id,
        request=QuestionChatSendRequest(message="в течение 1 рабочего дня"),
    )
    updated = ensure_draft_readiness(db, user_id="user-1", draft_id=draft.draftId)

    assert chat.status == "answered"
    assert updated.readiness is not None
    assert updated.readiness.changes


def _memory_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return Session()


def _seed_role_run(db, *, user_id: str, regulation_id: str, run_id: str) -> None:
    result = _regulation_result(regulation_id)
    role_result = RoleMatchResult(
        runId=run_id,
        regulationId=regulation_id,
        profile=RoleProfile(
            requestedPosition="Промпт-инженер",
            requestedDepartment="Сектор ИИ",
            canonicalTitle="Промпт-инженер",
            department="Сектор ИИ",
        ),
        functions=[_function()],
    )
    db.add(
        RegulationDocument(
            id=regulation_id,
            user_id=user_id,
            file_name=f"{regulation_id}.txt",
            content_type="text/plain",
            storage_path=f"/tmp/{regulation_id}.txt",
            result_json=result.model_dump(mode="json"),
        )
    )
    db.add(
        RoleMatchRun(
            id=run_id,
            regulation_id=regulation_id,
            user_id=user_id,
            position="Промпт-инженер",
            department="Сектор ИИ",
            result_json=role_result.model_dump(mode="json"),
        )
    )
    db.commit()


def _regulation_result(regulation_id: str) -> RegulationParseResult:
    return RegulationParseResult(
        regulationId=regulation_id,
        fileName=f"{regulation_id}.txt",
        pageCount=1,
        recognitionQuality=1,
        fragments=[
            RegulationFragment(
                fragmentId="B-001",
                page=1,
                section="Функции",
                text="Промпт-инженер оформляет техническую документацию.",
            )
        ],
    )


def _function() -> RoleFunction:
    return RoleFunction(
        functionId="F-001",
        targetBlockId="B-001",
        isFunction=True,
        actor=FunctionActor(text="Промпт-инженер", canonicalPosition="Промпт-инженер", sourceBlockId="B-001"),
        action="оформляет",
        object="техническую документацию",
        evidence=[
            MatchEvidence(fragmentId="B-001", quote="Промпт-инженер оформляет техническую документацию.")
        ],
    )
