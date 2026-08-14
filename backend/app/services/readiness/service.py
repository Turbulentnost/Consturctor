from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.regulation import AgentDraft, ReadinessRun, RegulationDocument, RegulationRevision, RoleMatchRun
from app.schemas.regulation import (
    AgentReadinessResult,
    ChangeDecisionRequest,
    ReadinessAnswer,
    ReadinessAnswerRequest,
    ReadinessFieldStatus,
    ReadinessQuestion,
    ReadinessSourceEvidence,
    RegulationParseResult,
    RegulationRevisionResult,
    RoleMatchResult,
)
from app.services.readiness.analyzer import analyze_readiness
from app.services.readiness.change_planner import change_from_answer
from app.services.readiness.impact import transaction_for_change
from app.services.readiness.revision_composer import create_llm_revision_files


class ReadinessError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_readiness_run(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    role_match_run_id: str,
) -> AgentReadinessResult:
    doc, role_run = _get_doc_and_role_run(
        db,
        user_id=user_id,
        regulation_id=regulation_id,
        role_match_run_id=role_match_run_id,
    )
    role_result = RoleMatchResult.model_validate(role_run.result_json)
    result = RegulationParseResult.model_validate(doc.result_json)
    functions = [
        match.function
        for match in role_result.matches
        if match.function is not None and match.status != "rejected"
    ] or role_result.functions
    readiness_run_id = f"ready-run-{uuid4().hex[:12]}"
    readiness = analyze_readiness(
        readiness_run_id=readiness_run_id,
        regulation_id=regulation_id,
        role_match_run_id=role_match_run_id,
        functions=functions,
        result=result,
    )
    _prepend_cursor_questions(readiness, role_result)
    run = ReadinessRun(
        id=readiness_run_id,
        regulation_id=regulation_id,
        role_match_run_id=role_match_run_id,
        user_id=user_id,
        result_json=readiness.model_dump(mode="json"),
    )
    run = db.merge(run)
    db.commit()
    db.refresh(run)
    return AgentReadinessResult.model_validate(run.result_json)


def _prepend_cursor_questions(readiness: AgentReadinessResult, role_result: RoleMatchResult) -> None:
    audit = role_result.audit or {}
    raw_questions = audit.get("cursorQuestions") if isinstance(audit, dict) else []
    if not isinstance(raw_questions, list) or not raw_questions:
        return
    block_by_function = {
        function.functionId: function.targetBlockId
        for function in role_result.functions or []
        if function.functionId and function.targetBlockId
    }
    existing = {(item.functionId, item.targetField, item.question.strip()) for item in readiness.questions}
    cursor_questions: list[ReadinessQuestion] = []
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        function_id = str(raw.get("functionId") or "").strip()
        question = str(raw.get("question") or "").strip()
        if not function_id or not question:
            continue
        target_field = _readiness_field(str(raw.get("targetField") or "inputs"))
        key = (function_id, target_field, question)
        if key in existing:
            continue
        existing.add(key)
        idx = len(cursor_questions) + 1
        source_refs = raw.get("sourceRefs") if isinstance(raw.get("sourceRefs"), list) else []
        block_id = _first_source_block(source_refs) or block_by_function.get(function_id, "")
        context = str(raw.get("context") or "").strip()
        related = [str(item) for item in raw.get("relatedFunctionIds") or [] if str(item).strip()]
        reason_parts = []
        if context:
            reason_parts.append(context)
        if related:
            reason_parts.append("Связанные функции: " + ", ".join(related))
        affected_blocks = [block_id] if block_id else []
        for related_id in related:
            related_block = block_by_function.get(related_id)
            if related_block and related_block not in affected_blocks:
                affected_blocks.append(related_block)
        cursor_questions.append(
            ReadinessQuestion(
                questionId=f"CUR-Q-{idx:03d}",
                functionId=function_id,
                targetField=target_field,
                severity="important",
                question=question,
                reason="\n".join(reason_parts),
                sourceEvidence=ReadinessSourceEvidence(
                    quote=context[:1000],
                    blockId=block_id,
                ),
                answerType=_answer_type_for_cursor(target_field),
                options=["указать ответ", "не требуется", "пока неизвестно"],
                affectedBlocks=affected_blocks,
            )
        )
    if not cursor_questions:
        return
    readiness.questions = cursor_questions + [
        item
        for item in readiness.questions
        if not any(item.functionId == cur.functionId and item.question == cur.question for cur in cursor_questions)
    ]
    readiness.status = "needs_answers" if readiness.questions else readiness.status


def _readiness_field(value: str) -> str:
    allowed = {
        "trigger",
        "inputs",
        "system",
        "result",
        "recipient",
        "conditions",
        "deadline",
        "errors",
        "approval",
        "permissions",
        "control",
        "kpi",
    }
    return value if value in allowed else "inputs"


def _answer_type_for_cursor(field: str) -> str:
    if field == "deadline":
        return "duration"
    if field in {"recipient", "approval"}:
        return "role"
    if field in {"system", "permissions"}:
        return "system"
    return "text"


def _first_source_block(source_refs: list) -> str:
    for ref in source_refs:
        if isinstance(ref, dict):
            block_id = str(ref.get("fragmentId") or "").strip()
            if block_id:
                return block_id
    return ""


def get_readiness_run(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    readiness_run_id: str,
) -> AgentReadinessResult:
    return AgentReadinessResult.model_validate(
        _get_readiness(db, user_id=user_id, regulation_id=regulation_id, readiness_run_id=readiness_run_id).result_json
    )


def answer_readiness_question(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    readiness_run_id: str,
    request: ReadinessAnswerRequest,
) -> AgentReadinessResult:
    run = _get_readiness(db, user_id=user_id, regulation_id=regulation_id, readiness_run_id=readiness_run_id)
    doc = _get_document(db, user_id=user_id, regulation_id=regulation_id)
    readiness = AgentReadinessResult.model_validate(run.result_json)
    question = next((item for item in readiness.questions if item.questionId == request.questionId), None)
    if question is None:
        raise ReadinessError("Вопрос не найден", status_code=404)
    answer = ReadinessAnswer(
        answerId=f"ANSWER-{len(readiness.answers) + 1:03d}",
        questionId=question.questionId,
        answer=request.answer.strip(),
    )
    readiness.answers.append(answer)
    for item in readiness.questions:
        if item.questionId == question.questionId:
            item.answered = True
            item.answer = answer.answer
            break
    _apply_answer_to_field(readiness, question.functionId, question.targetField, answer.answer)
    related_field_answers = {
        item.targetField: item.answer.strip()
        for item in readiness.questions
        if item.functionId == question.functionId
        and item.answered
        and item.answer.strip()
        and item.questionId != question.questionId
    }
    change = change_from_answer(
        change_id=f"CH-{len(readiness.changes) + 1:03d}",
        question=question,
        answer=answer,
        result=RegulationParseResult.model_validate(doc.result_json),
        related_field_answers=related_field_answers,
        clarifying_prompt=request.clarifyingPrompt.strip(),
    )
    readiness.changes.append(change)
    readiness.transactions.append(transaction_for_change(change, index=len(readiness.transactions) + 1))
    _refresh_summary(readiness)
    run.result_json = readiness.model_dump(mode="json")
    db.add(run)
    db.commit()
    db.refresh(run)
    return AgentReadinessResult.model_validate(run.result_json)


def update_change_status(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    readiness_run_id: str,
    change_id: str,
    request: ChangeDecisionRequest,
) -> AgentReadinessResult:
    run = _get_readiness(db, user_id=user_id, regulation_id=regulation_id, readiness_run_id=readiness_run_id)
    readiness = AgentReadinessResult.model_validate(run.result_json)
    change = next((item for item in readiness.changes if item.changeId == change_id), None)
    if change is None:
        raise ReadinessError("Изменение не найдено", status_code=404)
    change.status = request.status
    if request.after.strip():
        change.after = request.after.strip()
    _refresh_summary(readiness)
    run.result_json = readiness.model_dump(mode="json")
    db.add(run)
    db.commit()
    db.refresh(run)
    return AgentReadinessResult.model_validate(run.result_json)


def finalize_readiness_run(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    readiness_run_id: str,
) -> RegulationRevisionResult:
    run = _get_readiness(db, user_id=user_id, regulation_id=regulation_id, readiness_run_id=readiness_run_id)
    doc = _get_document(db, user_id=user_id, regulation_id=regulation_id)
    readiness = AgentReadinessResult.model_validate(run.result_json)
    revision_id = f"rev-{uuid4().hex[:12]}"
    output_dir = Path(doc.storage_path).parent / "revisions" / revision_id
    (
        document_path,
        protocol_path,
        pdf_path,
        message,
        source_html,
        revised_html,
        diff_blocks,
        source_preview_pages,
        revised_preview_pages,
    ) = create_llm_revision_files(
        source_path=Path(doc.storage_path),
        output_dir=output_dir,
        result=RegulationParseResult.model_validate(doc.result_json),
        readiness=readiness,
    )
    readiness.status = "finalized"
    run.result_json = readiness.model_dump(mode="json")
    revision = RegulationRevisionResult(
        revisionId=revision_id,
        regulationId=regulation_id,
        readinessRunId=readiness_run_id,
        documentPath=str(document_path),
        protocolPath=str(protocol_path),
        pdfPath=str(pdf_path) if pdf_path is not None else "",
        sourcePreviewHtml=source_html,
        revisedPreviewHtml=revised_html,
        sourcePreviewPages=[
            {
                "page": item["page"],
                "imageUrl": f"/api/v1/regulations/{regulation_id}/revisions/{revision_id}/preview/source/{item['page']}",
            }
            for item in source_preview_pages
        ],
        revisedPreviewPages=[
            {
                "page": item["page"],
                "imageUrl": f"/api/v1/regulations/{regulation_id}/revisions/{revision_id}/preview/revised/{item['page']}",
            }
            for item in revised_preview_pages
        ],
        diffBlocks=diff_blocks,
        downloadUrl=f"/api/v1/regulations/{regulation_id}/revisions/{revision_id}/download?kind=document",
        pdfDownloadUrl=(
            f"/api/v1/regulations/{regulation_id}/revisions/{revision_id}/download?kind=pdf"
            if pdf_path is not None
            else ""
        ),
        protocolUrl=f"/api/v1/regulations/{regulation_id}/revisions/{revision_id}/download?kind=protocol",
        message=message,
    )
    db.add(run)
    draft = db.query(AgentDraft).filter(
        AgentDraft.user_id == user_id,
        AgentDraft.readiness_run_id == readiness_run_id,
    ).first()
    if draft is not None:
        draft.status = "finalized"
        draft.progress = 100
        draft.result_json = {
            **(draft.result_json or {}),
            "revisionId": revision_id,
            "documentPath": str(document_path),
            "protocolPath": str(protocol_path),
            "pdfPath": str(pdf_path) if pdf_path is not None else "",
        }
        db.add(draft)
    db.merge(
        RegulationRevision(
            id=revision_id,
            regulation_id=regulation_id,
            readiness_run_id=readiness_run_id,
            user_id=user_id,
            document_path=str(document_path),
            protocol_path=str(protocol_path),
            result_json={
                **revision.model_dump(mode="json"),
                "_sourcePreviewPaths": source_preview_pages,
                "_revisedPreviewPaths": revised_preview_pages,
            },
        )
    )
    db.commit()
    return revision


def _apply_answer_to_field(
    readiness: AgentReadinessResult,
    function_id: str,
    field_name: str,
    answer: str,
) -> None:
    if not answer.strip() or answer.strip().casefold() == "пока неизвестно":
        return
    for function in readiness.functions:
        if function.functionId != function_id:
            continue
        for field in function.fields:
            if field.field == field_name:
                field.status = "not_applicable" if answer.strip().casefold() in {"не требуется", "срок не устанавливается"} else "confirmed"
                field.evidence = []
                break
        function.score = _function_score(function.fields)
        function.blockingReasons = [
            field.reason
            for field in function.fields
            if field.required and field.severity == "blocking" and field.status in {"missing", "ambiguous", "conflict", "inferred"}
        ]
        break


def _refresh_summary(readiness: AgentReadinessResult) -> None:
    readiness.score = round(sum(item.score for item in readiness.functions) / max(1, len(readiness.functions)))
    readiness.blocking = _summary(readiness, "blocking")
    readiness.important = _summary(readiness, "important")
    readiness.optional = _summary(readiness, "optional")
    unanswered = [item for item in readiness.questions if not item.answered]
    pending_changes = [item for item in readiness.changes if item.status == "pending"]
    if unanswered:
        readiness.status = "needs_answers"
    elif pending_changes:
        readiness.status = "needs_approval"
    else:
        readiness.status = "ready"


def _summary(readiness: AgentReadinessResult, severity: str) -> list[str]:
    out: list[str] = []
    for function in readiness.functions:
        for field in function.fields:
            if field.severity == severity and field.status in {"missing", "ambiguous", "conflict", "inferred"}:
                text = f"{function.title}: {field.reason}"
                if text not in out:
                    out.append(text)
    return out


def _function_score(fields: list[ReadinessFieldStatus]) -> int:
    relevant = [field for field in fields if field.status != "not_applicable"]
    if not relevant:
        return 100
    good = sum(1 for field in relevant if field.status in {"confirmed", "inherited"})
    partial = sum(1 for field in relevant if field.status == "inferred")
    return round(((good + partial * 0.5) / len(relevant)) * 100)


def _get_doc_and_role_run(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    role_match_run_id: str,
) -> tuple[RegulationDocument, RoleMatchRun]:
    doc = _get_document(db, user_id=user_id, regulation_id=regulation_id)
    run = (
        db.query(RoleMatchRun)
        .filter(
            RoleMatchRun.id == role_match_run_id,
            RoleMatchRun.user_id == user_id,
            RoleMatchRun.regulation_id == regulation_id,
        )
        .first()
    )
    if run is None:
        raise ReadinessError("Запуск поиска функций не найден", status_code=404)
    return doc, run


def _get_document(db: Session, *, user_id: str, regulation_id: str) -> RegulationDocument:
    doc = (
        db.query(RegulationDocument)
        .filter(RegulationDocument.id == regulation_id, RegulationDocument.user_id == user_id)
        .first()
    )
    if doc is None:
        raise ReadinessError("Регламент не найден", status_code=404)
    return doc


def _get_readiness(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    readiness_run_id: str,
) -> ReadinessRun:
    run = (
        db.query(ReadinessRun)
        .filter(
            ReadinessRun.id == readiness_run_id,
            ReadinessRun.user_id == user_id,
            ReadinessRun.regulation_id == regulation_id,
        )
        .first()
    )
    if run is None:
        raise ReadinessError("Проверка готовности не найдена", status_code=404)
    return run
