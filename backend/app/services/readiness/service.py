from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.regulation import ReadinessRun, RegulationDocument, RegulationRevision, RoleMatchRun
from app.schemas.regulation import (
    AgentReadinessResult,
    ChangeDecisionRequest,
    ReadinessAnswer,
    ReadinessAnswerRequest,
    ReadinessFieldStatus,
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
    change = change_from_answer(
        change_id=f"CH-{len(readiness.changes) + 1:03d}",
        question=question,
        answer=answer,
        result=RegulationParseResult.model_validate(doc.result_json),
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
    document_path, protocol_path, message, source_html, revised_html, diff_blocks = create_llm_revision_files(
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
        sourcePreviewHtml=source_html,
        revisedPreviewHtml=revised_html,
        diffBlocks=diff_blocks,
        downloadUrl=f"/api/v1/regulations/{regulation_id}/revisions/{revision_id}/download?kind=document",
        protocolUrl=f"/api/v1/regulations/{regulation_id}/revisions/{revision_id}/download?kind=protocol",
        message=message,
    )
    db.add(run)
    db.merge(
        RegulationRevision(
            id=revision_id,
            regulation_id=regulation_id,
            readiness_run_id=readiness_run_id,
            user_id=user_id,
            document_path=str(document_path),
            protocol_path=str(protocol_path),
            result_json=revision.model_dump(mode="json"),
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
