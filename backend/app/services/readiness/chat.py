from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.regulation import (
    AgentDraft,
    QuestionChatMessage,
    QuestionChatSession,
    ReadinessRun,
    RegulationDocument,
)
from app.schemas.regulation import (
    AgentReadinessResult,
    QuestionChatMessageResult,
    QuestionChatSendRequest,
    QuestionChatSessionResult,
    ReadinessAnswerRequest,
    RegulationParseResult,
)
from app.services.agents import sync_draft_progress
from app.services.readiness.service import ReadinessError, answer_readiness_question


def create_or_get_question_chat(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    question_id: str,
) -> QuestionChatSessionResult:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    readiness = _get_readiness(db, draft)
    question = next((item for item in readiness.questions if item.questionId == question_id), None)
    if question is None:
        raise ReadinessError("Вопрос не найден", status_code=404)
    session = (
        db.query(QuestionChatSession)
        .filter(QuestionChatSession.draft_id == draft_id, QuestionChatSession.question_id == question_id)
        .first()
    )
    if session is None:
        context = _context(db, draft, readiness, question_id)
        session = QuestionChatSession(
            id=f"qchat-{uuid4().hex[:12]}",
            draft_id=draft_id,
            readiness_run_id=draft.readiness_run_id,
            question_id=question_id,
            function_id=question.functionId,
            target_field=question.targetField,
            status="answered" if question.answered else "active",
            context_json=context,
        )
        db.add(session)
        db.flush()
        db.add(
            QuestionChatMessage(
                id=f"qmsg-{uuid4().hex[:12]}",
                session_id=session.id,
                role="assistant",
                content=_initial_prompt(context),
                structured_json={},
            )
        )
        db.commit()
        db.refresh(session)
    return _session_result(db, session)


def get_question_chat(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    question_id: str,
) -> QuestionChatSessionResult:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    session = (
        db.query(QuestionChatSession)
        .filter(
            QuestionChatSession.draft_id == draft.id,
            QuestionChatSession.question_id == question_id,
        )
        .first()
    )
    if session is None:
        return create_or_get_question_chat(db, user_id=user_id, draft_id=draft_id, question_id=question_id)
    return _session_result(db, session)


def send_question_chat_message(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    question_id: str,
    request: QuestionChatSendRequest,
) -> QuestionChatSessionResult:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    session = db.query(QuestionChatSession).filter(
        QuestionChatSession.draft_id == draft_id,
        QuestionChatSession.question_id == question_id,
    ).first()
    if session is None:
        create_or_get_question_chat(db, user_id=user_id, draft_id=draft_id, question_id=question_id)
        session = db.query(QuestionChatSession).filter(
            QuestionChatSession.draft_id == draft_id,
            QuestionChatSession.question_id == question_id,
        ).first()
    assert session is not None
    user_text = request.message.strip()
    db.add(
        QuestionChatMessage(
            id=f"qmsg-{uuid4().hex[:12]}",
            session_id=session.id,
            role="user",
            content=user_text,
            structured_json={},
        )
    )
    structured = _extract_structured_answer(user_text, session.context_json)
    if structured["isComplete"]:
        readiness = answer_readiness_question(
            db,
            user_id=user_id,
            regulation_id=draft.regulation_id,
            readiness_run_id=draft.readiness_run_id,
            request=ReadinessAnswerRequest(questionId=question_id, answer=str(structured["answer"])),
        )
        sync_draft_progress(db, draft_id=draft.id, readiness=readiness)
        session.status = "answered"
        assistant_text = "Ответ принят. Я подготовил проект изменения регламента для согласования."
    else:
        session.status = "needs_clarification"
        assistant_text = _follow_up_prompt(session.context_json)
    db.add(
        QuestionChatMessage(
            id=f"qmsg-{uuid4().hex[:12]}",
            session_id=session.id,
            role="assistant",
            content=assistant_text,
            structured_json=structured,
        )
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_result(db, session)


def _get_draft(db: Session, *, user_id: str, draft_id: str) -> AgentDraft:
    draft = db.query(AgentDraft).filter(AgentDraft.id == draft_id, AgentDraft.user_id == user_id).first()
    if draft is None:
        raise ReadinessError("Черновик агента не найден", status_code=404)
    if not draft.readiness_run_id:
        raise ReadinessError("Для черновика ещё не создана проверка готовности", status_code=409)
    return draft


def _get_readiness(db: Session, draft: AgentDraft) -> AgentReadinessResult:
    run = db.query(ReadinessRun).filter(ReadinessRun.id == draft.readiness_run_id).first()
    if run is None:
        raise ReadinessError("Проверка готовности не найдена", status_code=404)
    return AgentReadinessResult.model_validate(run.result_json)


def _context(db: Session, draft: AgentDraft, readiness: AgentReadinessResult, question_id: str) -> dict:
    doc = db.query(RegulationDocument).filter(RegulationDocument.id == draft.regulation_id).first()
    result = RegulationParseResult.model_validate(doc.result_json) if doc is not None else None
    question = next(item for item in readiness.questions if item.questionId == question_id)
    function = next((item for item in readiness.functions if item.functionId == question.functionId), None)
    fragments = {fragment.fragmentId: fragment for fragment in (result.fragments if result else [])}
    blocks = []
    for block_id in question.affectedBlocks:
        fragment = fragments.get(block_id)
        if fragment is not None:
            blocks.append({"blockId": fragment.fragmentId, "section": fragment.section, "text": fragment.text})
    return {
        "question": question.model_dump(mode="json"),
        "function": function.model_dump(mode="json") if function is not None else {},
        "affectedBlocks": blocks,
        "draft": {"title": draft.title, "position": draft.position, "department": draft.department},
    }


def _initial_prompt(context: dict) -> str:
    question = context.get("question") or {}
    blocks = context.get("affectedBlocks") or []
    quote = blocks[0]["text"] if blocks else question.get("sourceEvidence", {}).get("quote", "")
    return (
        f"{question.get('question', 'Нужно уточнение по регламенту')}\n\n"
        f"Зачем спрашиваю: {question.get('reason', '')}\n\n"
        f"Связанный фрагмент регламента: «{quote[:700]}»\n\n"
        "Ответьте своими словами. Если информации пока нет, так и напишите."
    )


def _follow_up_prompt(context: dict) -> str:
    field = (context.get("question") or {}).get("targetField", "параметр")
    return (
        f"Ответ пока недостаточно конкретный для поля «{field}». "
        "Уточните, пожалуйста, конкретное правило, срок, роль или действие, которое нужно внести в регламент."
    )


def _extract_structured_answer(text: str, context: dict) -> dict:
    clean = text.strip()
    incomplete = not clean or clean.casefold() in {"не знаю", "пока неизвестно", "позже", "уточню позже"}
    return {
        "isComplete": not incomplete,
        "targetField": (context.get("question") or {}).get("targetField", ""),
        "answer": clean,
        "confidence": 0.9 if not incomplete else 0.2,
        "needsFollowUp": incomplete,
        "proposedChangeHint": "Добавить уточнение к связанному блоку регламента" if not incomplete else "",
    }


def _session_result(db: Session, session: QuestionChatSession) -> QuestionChatSessionResult:
    messages = (
        db.query(QuestionChatMessage)
        .filter(QuestionChatMessage.session_id == session.id)
        .order_by(QuestionChatMessage.created_at.asc())
        .all()
    )
    return QuestionChatSessionResult(
        sessionId=session.id,
        draftId=session.draft_id,
        readinessRunId=session.readiness_run_id,
        questionId=session.question_id,
        functionId=session.function_id,
        targetField=session.target_field,
        status=session.status,
        context=session.context_json,
        messages=[
            QuestionChatMessageResult(
                messageId=message.id,
                sessionId=message.session_id,
                role=message.role,
                content=message.content,
                structured=message.structured_json,
                createdAt=message.created_at,
            )
            for message in messages
        ],
    )
