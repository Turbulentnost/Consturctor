from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.regulation import (
    AgentDraft,
    QuestionChatMessage,
    QuestionChatSession,
    ReadinessRun,
    RegulationDocument,
    RoleMatchRun,
)
from app.schemas.regulation import (
    AgentReadinessResult,
    QuestionChatMessageResult,
    QuestionChatSendRequest,
    QuestionChatSessionResult,
    ReadinessAnswerRequest,
    ReadinessQuestion,
    ReadinessSourceEvidence,
    RegulationParseResult,
    RoleMatchResult,
)
from app.services.agents import sync_draft_progress
from app.services.readiness.llm_interview import adapt_after_answer, generate_initial_question
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
        initial = generate_initial_question(context, _pending_questions(readiness, question.functionId))
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
                content=str(initial.get("assistantMessage") or _initial_prompt(context)),
                structured_json=initial,
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


def get_latest_question_chat(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
) -> QuestionChatSessionResult:
    _get_draft(db, user_id=user_id, draft_id=draft_id)
    session = (
        db.query(QuestionChatSession)
        .filter(QuestionChatSession.draft_id == draft_id)
        .order_by(QuestionChatSession.updated_at.desc(), QuestionChatSession.created_at.desc())
        .first()
    )
    if session is None:
        raise ReadinessError("История уточнения для черновика пока не создана", status_code=404)
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
    readiness = _get_readiness(db, draft)
    pending = _pending_questions(readiness, session.function_id)
    structured = adapt_after_answer(
        session.context_json,
        pending,
        answer=user_text,
        history=_message_history(db, session.id),
        turn_count=_user_turn_count(db, session.id),
    )
    fallback_structured = _extract_structured_answer(user_text, session.context_json, readiness)
    if not fallback_structured["isComplete"]:
        structured["answeredQuestionIds"] = []
        structured["remainingQuestionIds"] = [str(item.get("questionId") or "") for item in pending]
        structured["stopInterview"] = False
    if not structured.get("answeredQuestionIds") and fallback_structured["isComplete"]:
        structured["answeredQuestionIds"] = [item["questionId"] for item in fallback_structured["relatedAnswers"]]
        structured["remainingQuestionIds"] = [
            str(item.get("questionId") or "")
            for item in pending
            if str(item.get("questionId") or "") not in set(structured["answeredQuestionIds"])
        ]
    structured["isComplete"] = bool(structured.get("answeredQuestionIds"))
    structured["targetField"] = session.target_field
    structured["answer"] = user_text
    structured["relatedAnswers"] = [
        {"questionId": qid, "answer": user_text}
        for qid in structured.get("answeredQuestionIds", [])
    ]
    if structured["isComplete"]:
        applied = []
        clarifying_prompt = _last_assistant_prompt(db, session.id)
        for item in structured["relatedAnswers"]:
            readiness = answer_readiness_question(
                db,
                user_id=user_id,
                regulation_id=draft.regulation_id,
                readiness_run_id=draft.readiness_run_id,
                request=ReadinessAnswerRequest(
                    questionId=str(item["questionId"]),
                    answer=str(item["answer"]),
                    clarifyingPrompt=clarifying_prompt,
                ),
            )
            applied.append(item)
        readiness = _apply_adaptive_question_state(
            db,
            user_id=user_id,
            regulation_id=draft.regulation_id,
            readiness_run_id=draft.readiness_run_id,
            function_id=session.function_id,
            structured=structured,
            context=session.context_json,
        )
        sync_draft_progress(db, draft_id=draft.id, readiness=readiness)
        session.status = "answered" if _function_interview_done(readiness, session.function_id, structured) else "active"
        assistant_text = str(structured.get("assistantMessage") or _accepted_answer_text(applied))
    else:
        session.status = "needs_clarification"
        assistant_text = str(structured.get("followUpQuestion") or _follow_up_prompt(session.context_json))
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
    blocks = _context_blocks(db, draft, readiness, question, fragments)
    return {
        "question": question.model_dump(mode="json"),
        "function": function.model_dump(mode="json") if function is not None else {},
        "blocks": blocks,
        "affectedBlocks": blocks,
        "draft": {"title": draft.title, "position": draft.position, "department": draft.department},
    }


def _context_blocks(
    db: Session,
    draft: AgentDraft,
    readiness: AgentReadinessResult,
    question: ReadinessQuestion,
    fragments: dict,
) -> list[dict]:
    function = next((item for item in readiness.functions if item.functionId == question.functionId), None)
    role_run = db.query(RoleMatchRun).filter(RoleMatchRun.id == draft.role_match_run_id).first()
    role_result = RoleMatchResult.model_validate(role_run.result_json) if role_run is not None else None
    source_ids = [
        question.sourceEvidence.blockId,
        function.targetBlockId if function is not None else "",
        *question.affectedBlocks,
    ]
    if function is not None:
        for field in function.fields:
            source_ids.extend(item.fragmentId for item in field.evidence)
    if role_result is not None:
        for match in role_result.matches:
            if match.function is not None and match.function.functionId == question.functionId:
                source_ids.append(match.fragmentId)
                source_ids.extend(item.fragmentId for item in match.evidence)
    blocks: list[dict] = []
    seen: set[str] = set()
    for block_id in source_ids:
        _append_block(blocks, seen, fragments.get(block_id), relation="source", reason="Функциональный блок")
    for block in list(blocks):
        fragment = fragments.get(block["blockId"])
        if fragment is None or fragment.context is None:
            continue
        _append_block(
            blocks,
            seen,
            fragments.get(fragment.context.previousFragmentId or ""),
            relation="related",
            reason="Предыдущий смысловой блок",
        )
        _append_block(
            blocks,
            seen,
            fragments.get(fragment.context.nextFragmentId or ""),
            relation="related",
            reason="Следующий смысловой блок",
        )
    return blocks[:8]


def _append_block(blocks: list[dict], seen: set[str], fragment, *, relation: str, reason: str) -> None:
    if fragment is None or fragment.fragmentId in seen:
        return
    seen.add(fragment.fragmentId)
    blocks.append(
        {
            "blockId": fragment.fragmentId,
            "relation": relation,
            "reason": reason,
            "page": fragment.page,
            "section": fragment.section,
            "text": fragment.text,
        }
    )


def _initial_prompt(context: dict) -> str:
    question = context.get("question") or {}
    blocks = context.get("blocks") or context.get("affectedBlocks") or []
    quote = blocks[0]["text"] if blocks else question.get("sourceEvidence", {}).get("quote", "")
    return (
        f"{question.get('question', 'Нужно уточнение по регламенту')}\n\n"
        f"Зачем спрашиваю: {question.get('reason', '')}\n\n"
        f"Связанный фрагмент регламента: «{quote[:700]}»\n\n"
        "Ответьте своими словами. Если информации пока нет, так и напишите."
    )


def _pending_questions(readiness: AgentReadinessResult, function_id: str) -> list[dict]:
    questions = [
        item
        for item in readiness.questions
        if not item.answered and (not function_id or item.functionId == function_id)
    ]
    return [item.model_dump(mode="json") for item in sorted(questions, key=lambda item: (_severity_rank(item.severity), item.questionId))]


def _message_history(db: Session, session_id: str) -> list[dict]:
    messages = (
        db.query(QuestionChatMessage)
        .filter(QuestionChatMessage.session_id == session_id)
        .order_by(QuestionChatMessage.created_at.asc())
        .all()
    )
    return [
        {"role": message.role, "content": message.content, "structured": message.structured_json}
        for message in messages
    ]


def _last_assistant_prompt(db: Session, session_id: str) -> str:
    message = (
        db.query(QuestionChatMessage)
        .filter(QuestionChatMessage.session_id == session_id, QuestionChatMessage.role == "assistant")
        .order_by(QuestionChatMessage.created_at.desc())
        .first()
    )
    return (message.content or "").strip() if message is not None else ""


def _user_turn_count(db: Session, session_id: str) -> int:
    return (
        db.query(QuestionChatMessage)
        .filter(QuestionChatMessage.session_id == session_id, QuestionChatMessage.role == "user")
        .count()
    )


def _apply_adaptive_question_state(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    readiness_run_id: str,
    function_id: str,
    structured: dict,
    context: dict,
) -> AgentReadinessResult:
    run = db.query(ReadinessRun).filter(
        ReadinessRun.id == readiness_run_id,
        ReadinessRun.user_id == user_id,
        ReadinessRun.regulation_id == regulation_id,
    ).first()
    if run is None:
        raise ReadinessError("Проверка готовности не найдена", status_code=404)
    readiness = AgentReadinessResult.model_validate(run.result_json)
    _append_new_questions(readiness, function_id=function_id, structured=structured, context=context)
    readiness.questions = _reorder_questions(readiness.questions, function_id, structured)
    run.result_json = readiness.model_dump(mode="json")
    db.add(run)
    db.commit()
    db.refresh(run)
    return AgentReadinessResult.model_validate(run.result_json)


def _append_new_questions(
    readiness: AgentReadinessResult,
    *,
    function_id: str,
    structured: dict,
    context: dict,
) -> None:
    existing_text = {_normalize_question(item.question) for item in readiness.questions if item.functionId == function_id}
    for item in structured.get("newQuestions") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or item.get("assistantMessage") or "").strip()
        if not text or _normalize_question(text) in existing_text:
            continue
        current = context.get("question") or {}
        try:
            readiness.questions.append(
                ReadinessQuestion(
                    questionId=f"Q-{len(readiness.questions) + 1:03d}",
                    functionId=function_id,
                    targetField=str(item.get("targetField") or current.get("targetField") or "conditions"),
                    severity=str(item.get("severity") or current.get("severity") or "important"),
                    question=text,
                    reason=str(item.get("reason") or "Уточняющий вопрос LLM по связанному блоку"),
                    sourceEvidence=ReadinessSourceEvidence.model_validate(
                        current.get("sourceEvidence") or {}
                    ),
                    answerType=str(item.get("answerType") or current.get("answerType") or "text"),
                    options=[str(x) for x in item.get("quickAnswers") or []],
                    affectedBlocks=[str(x) for x in current.get("affectedBlocks") or []],
                )
            )
            existing_text.add(_normalize_question(text))
        except Exception:
            continue


def _reorder_questions(
    questions: list[ReadinessQuestion],
    function_id: str,
    structured: dict,
) -> list[ReadinessQuestion]:
    remaining_order = {
        str(qid): index
        for index, qid in enumerate(structured.get("remainingQuestionIds") or [])
    }
    return sorted(
        questions,
        key=lambda item: (
            1 if item.answered else 0,
            0 if item.functionId == function_id else 1,
            remaining_order.get(item.questionId, 100),
            _severity_rank(item.severity),
            item.questionId,
        ),
    )


def _function_interview_done(readiness: AgentReadinessResult, function_id: str, structured: dict) -> bool:
    if structured.get("stopInterview"):
        return True
    return not any(not item.answered and item.functionId == function_id for item in readiness.questions)


def _normalize_question(text: str) -> str:
    return " ".join(text.casefold().split())


def _follow_up_prompt(context: dict) -> str:
    field = (context.get("question") or {}).get("targetField", "параметр")
    return (
        f"Ответ пока недостаточно конкретный для поля «{field}». "
        "Уточните, пожалуйста, конкретное правило, срок, роль или действие, которое нужно внести в регламент."
    )


def _extract_structured_answer(text: str, context: dict, readiness: AgentReadinessResult) -> dict:
    clean = text.strip()
    current = context.get("question") or {}
    incomplete = _needs_clarification(clean)
    related_answers = []
    if not incomplete:
        related_answers.append(
            {
                "questionId": current.get("questionId", ""),
                "targetField": current.get("targetField", ""),
                "answer": clean,
            }
        )
        related_answers.extend(_related_answers(clean, current, readiness))
    return {
        "isComplete": not incomplete,
        "targetField": (context.get("question") or {}).get("targetField", ""),
        "answer": clean,
        "relatedAnswers": related_answers,
        "confidence": 0.9 if not incomplete else 0.2,
        "needsFollowUp": incomplete,
        "followUpQuestion": _follow_up_from_answer(clean, context) if incomplete else "",
        "proposedChangeHint": "Добавить уточнение к связанному блоку регламента" if not incomplete else "",
    }


def _needs_clarification(text: str) -> bool:
    clean = text.strip().casefold()
    if not clean or clean in {"не знаю", "пока неизвестно", "позже", "уточню позже"}:
        return True
    vague = {"по ситуации", "как обычно", "на усмотрение", "пока непонятно"}
    return clean in vague or (len(clean) < 6 and clean not in {"да", "нет"})


def _related_answers(text: str, current: dict, readiness: AgentReadinessResult) -> list[dict]:
    current_question_id = str(current.get("questionId") or "")
    current_function_id = str(current.get("functionId") or "")
    out = []
    for question in readiness.questions:
        if question.answered or question.questionId == current_question_id:
            continue
        if current_function_id and question.functionId != current_function_id:
            continue
        if _answer_mentions_field(text, question.targetField):
            out.append(
                {
                    "questionId": question.questionId,
                    "targetField": question.targetField,
                    "answer": text.strip(),
                }
            )
    return out


def _answer_mentions_field(text: str, field: str) -> bool:
    clean = text.casefold()
    signals = {
        "trigger": ("когда", "после", "при ", "по поручению", "график", "появлен"),
        "deadline": ("срок", "день", "час", "минут", "недел", "рабоч"),
        "errors": ("ошиб", "сбой", "невозмож", "не получится", "отказ"),
        "escalation": ("эскал", "переда", "руковод", "начальник"),
        "recipient": ("переда", "кому", "получател", "руковод"),
        "approval": ("подтверд", "соглас", "утвержд", "одобр"),
        "inputs": ("данн", "документ", "файл", "заявк", "информац", "вход"),
        "system": ("систем", "crm", "erp", "битрикс", "1с"),
        "result": ("результ", "отчет", "отчёт", "сформир", "готов"),
        "control": ("контрол", "провер", "монитор"),
        "conditions": ("если", "услов", "случа"),
        "branches": ("если", "иначе", "вариант", "или"),
        "permissions": ("доступ", "прав", "учетн", "учётн"),
        "restrictions": ("нельзя", "запрет", "огранич"),
        "kpi": ("kpi", "метрик", "показател"),
    }
    return any(signal in clean for signal in signals.get(field, ()))


def _reprioritize_questions(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    readiness_run_id: str,
    answer: str,
) -> AgentReadinessResult:
    run = db.query(ReadinessRun).filter(
        ReadinessRun.id == readiness_run_id,
        ReadinessRun.user_id == user_id,
        ReadinessRun.regulation_id == regulation_id,
    ).first()
    if run is None:
        raise ReadinessError("Проверка готовности не найдена", status_code=404)
    readiness = AgentReadinessResult.model_validate(run.result_json)
    priorities = _field_priorities_from_answer(answer)
    readiness.questions = sorted(
        readiness.questions,
        key=lambda item: (
            1 if item.answered else 0,
            priorities.get(item.targetField, 10),
            _severity_rank(item.severity),
            item.questionId,
        ),
    )
    run.result_json = readiness.model_dump(mode="json")
    db.add(run)
    db.commit()
    db.refresh(run)
    return AgentReadinessResult.model_validate(run.result_json)


def _field_priorities_from_answer(answer: str) -> dict[str, int]:
    clean = answer.casefold()
    priorities: dict[str, int] = {}
    if any(token in clean for token in ("если", "иначе", "ошиб", "сбой", "невозможно")):
        priorities.update({"errors": 0, "branches": 1, "conditions": 2})
    if any(token in clean for token in ("руковод", "соглас", "подтверд", "переда")):
        priorities.update({"approval": 0, "escalation": 1, "recipient": 2})
    if any(token in clean for token in ("срок", "день", "час", "минут")):
        priorities["deadline"] = 0
    return priorities


def _severity_rank(severity: str) -> int:
    return {"blocking": 0, "important": 1, "optional": 2}.get(severity, 3)


def _accepted_answer_text(applied: list[dict]) -> str:
    if len(applied) <= 1:
        return "Понял. Я предлагаю дополнить пункт регламента так:"
    return f"Понял. Этот ответ закрывает сразу {len(applied)} уточнения. Я подготовил проекты изменений регламента."


def _follow_up_from_answer(text: str, context: dict) -> str:
    question = context.get("question") or {}
    if text.strip().casefold() == "пока неизвестно":
        return "Понял. Тогда уточните, кто сможет определить это правило и когда к нему можно вернуться?"
    return (
        "Пока не хватает конкретики. Опишите правило так, как оно должно попасть в регламент: "
        "когда начинается действие, кто отвечает, какой результат ожидается или что делать при исключении."
    )


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
