from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.regulation import AgentDraft, ReadinessRun, RegulationDocument, RoleMatchRun
from app.schemas.regulation import (
    AgentDraftDetail,
    AgentDraftListResult,
    AgentSuggestion,
    AgentSuggestionListResult,
    AgentDraftStatusRequest,
    AgentDraftSummary,
    AgentReadinessResult,
    RoleMatchResult,
)
from app.services.agent_platform import sync_draft_to_platform_card
from app.services.readiness.service import create_readiness_run
from app.services.regulation import RegulationError, parse_upload
from app.services.role_matching import RoleMatchError, create_role_match_run

logger = logging.getLogger(__name__)


class AgentDraftError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_or_get_draft(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    role_match_run_id: str,
) -> AgentDraftDetail:
    existing = (
        db.query(AgentDraft)
        .filter(AgentDraft.role_match_run_id == role_match_run_id, AgentDraft.user_id == user_id)
        .first()
    )
    if existing is not None:
        return _draft_detail(db, existing)
    doc, role_run = _get_doc_and_role_run(
        db,
        user_id=user_id,
        regulation_id=regulation_id,
        role_match_run_id=role_match_run_id,
    )
    role_result = RoleMatchResult.model_validate(role_run.result_json)
    title = f"{role_result.profile.canonicalTitle or role_run.position}: {doc.file_name}"
    draft = AgentDraft(
        id=f"agent-draft-{uuid4().hex[:12]}",
        user_id=user_id,
        regulation_id=regulation_id,
        role_match_run_id=role_match_run_id,
        title=title[:512],
        position=role_result.profile.canonicalTitle or role_run.position,
        department=role_result.profile.department or role_run.department,
        status="draft",
        progress=0,
        result_json={"roleMatchRunId": role_match_run_id, "regulationFileName": doc.file_name},
    )
    draft = db.merge(draft)
    db.commit()
    db.refresh(draft)
    return _draft_detail(db, draft)


def list_drafts(db: Session, *, user_id: str) -> AgentDraftListResult:
    items = (
        db.query(AgentDraft)
        .filter(AgentDraft.user_id == user_id)
        .order_by(AgentDraft.updated_at.desc())
        .all()
    )
    return AgentDraftListResult(items=[_draft_summary(item) for item in items])


def get_draft(db: Session, *, user_id: str, draft_id: str) -> AgentDraftDetail:
    return _draft_detail(db, _get_draft(db, user_id=user_id, draft_id=draft_id))


def delete_draft(db: Session, *, user_id: str, draft_id: str) -> None:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    db.delete(draft)
    db.commit()


def delete_draft_suggestion(db: Session, *, user_id: str, draft_id: str, agent_id: str) -> None:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    data = dict(draft.result_json or {})
    suggestions = [item for item in data.get("agentSuggestions") or [] if isinstance(item, dict)]
    remaining = [item for item in suggestions if str(item.get("agentId") or "") != agent_id]
    if len(remaining) == len(suggestions):
        raise AgentDraftError("Черновик ИИ-агента не найден", status_code=404)
    if remaining:
        draft.result_json = {**data, "agentSuggestions": remaining}
        db.add(draft)
    else:
        db.delete(draft)
    db.commit()


def ensure_draft_readiness(db: Session, *, user_id: str, draft_id: str) -> AgentDraftDetail:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    if not draft.readiness_run_id:
        readiness = create_readiness_run(
            db,
            user_id=user_id,
            regulation_id=draft.regulation_id,
            role_match_run_id=draft.role_match_run_id,
        )
        draft.readiness_run_id = readiness.readinessRunId
        draft.progress = readiness.score
        draft.status = _status_from_readiness(readiness)
        draft.result_json = {**(draft.result_json or {}), "readinessRunId": readiness.readinessRunId}
        db.add(draft)
        db.commit()
        db.refresh(draft)
    return _draft_detail(db, draft)


def update_draft_status(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    request: AgentDraftStatusRequest,
) -> AgentDraftDetail:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    draft.status = request.status
    if request.status == "ready":
        draft.result_json = _ensure_agent_suggestions(db, draft)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    try:
        sync_draft_to_platform_card(db, draft)
    except Exception:
        logger.exception("Failed to sync draft %s to platform agent card", draft.id)
    return _draft_detail(db, draft)


def reanalyze_revision_document(db: Session, *, user_id: str, draft_id: str) -> AgentSuggestionListResult:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    data = draft.result_json or {}
    source_path = data.get("pdfPath") or data.get("documentPath")
    if not source_path:
        raise AgentDraftError("Сформированный документ для повторного анализа не найден", status_code=404)
    path = Path(str(source_path))
    if not path.is_file():
        raise AgentDraftError("Файл сформированного документа не найден", status_code=404)
    content_type = "application/pdf" if path.suffix.casefold() == ".pdf" else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if path.suffix.casefold() == ".docx"
        else "application/octet-stream"
    )
    try:
        result = parse_upload(
            db,
            user_id=user_id,
            filename=path.name,
            content_type=content_type,
            data=path.read_bytes(),
        )
        role_result = create_role_match_run(
            db,
            user_id=user_id,
            regulation_id=result.regulationId,
            position=draft.position,
            department=draft.department,
        )
        suggestions = _agent_suggestions_from_role_result(role_result)
        draft.status = "ready"
        draft.progress = 100
        draft.result_json = {
            **(draft.result_json or {}),
            "agentSuggestions": [item.model_dump(mode="json") for item in suggestions],
            "suggestionRegulationId": result.regulationId,
            "suggestionRoleMatchRunId": role_result.runId,
        }
        db.add(draft)
        db.commit()
        return AgentSuggestionListResult(items=suggestions)
    except AgentDraftError:
        raise
    except (RegulationError, RoleMatchError) as exc:
        status_code = getattr(exc, "status_code", 400)
        message = getattr(exc, "message", str(exc))
        raise AgentDraftError(message, status_code=status_code) from exc
    except Exception as exc:  # noqa: BLE001
        raise AgentDraftError(f"Не удалось повторно проанализировать документ: {exc}") from exc


def _agent_suggestions_from_role_result(role_result: RoleMatchResult) -> list[AgentSuggestion]:
    functions = role_result.functions or [
        match.function
        for match in role_result.matches
        if match.function is not None and match.status != "rejected"
    ]
    suggestions: list[AgentSuggestion] = []
    seen: set[str] = set()
    for index, function in enumerate(functions, start=1):
        if function is None:
            continue
        if not function.isFunction and not (function.action or function.object):
            continue
        key = function.duplicateGroup or function.functionId or f"{function.action}:{function.object}"
        if key in seen:
            continue
        seen.add(key)
        title = _agent_title_from_function(function, index)
        suggestions.append(
            AgentSuggestion(
                agentId=f"agent-suggestion-{index:03d}",
                title=title,
                description=_agent_description_from_function(function),
                regulationId=role_result.regulationId,
                roleMatchRunId=role_result.runId,
                functionId=function.functionId,
                sourceBlockId=function.targetBlockId,
            )
        )
    return suggestions


def _ensure_agent_suggestions(db: Session, draft: AgentDraft) -> dict:
    data = dict(draft.result_json or {})
    if data.get("agentSuggestions"):
        return data
    role_run = db.query(RoleMatchRun).filter(RoleMatchRun.id == draft.role_match_run_id).first()
    if role_run is None:
        return data
    role_result = RoleMatchResult.model_validate(role_run.result_json)
    suggestions = _agent_suggestions_from_role_result(role_result)
    if not suggestions:
        return data
    return {
        **data,
        "agentSuggestions": [item.model_dump(mode="json") for item in suggestions],
        "suggestionRegulationId": draft.regulation_id,
        "suggestionRoleMatchRunId": draft.role_match_run_id,
    }


def _agent_title_from_function(function, index: int) -> str:
    action = (function.action or "").strip()
    obj = (function.object or "").strip()
    if action and obj:
        return f"ИИ-агент: {action} {obj}"[:180]
    if action:
        return f"ИИ-агент: {action}"[:180]
    return f"ИИ-агент для бизнес-процесса {index}"


def _agent_description_from_function(function) -> str:
    parts = []
    if function.actor and function.actor.canonicalPosition:
        parts.append(f"Роль: {function.actor.canonicalPosition}")
    if function.conditions:
        parts.append("Условия: " + "; ".join(function.conditions[:2]))
    if function.recipient:
        parts.append(f"Получатель/участник: {function.recipient}")
    if function.explanation:
        parts.append(function.explanation)
    return "\n".join(part for part in parts if part).strip()


def sync_draft_progress(db: Session, *, draft_id: str, readiness: AgentReadinessResult) -> None:
    draft = db.query(AgentDraft).filter(AgentDraft.id == draft_id).first()
    if draft is None:
        return
    draft.readiness_run_id = readiness.readinessRunId
    draft.progress = readiness.score
    draft.status = _status_from_readiness(readiness)
    db.add(draft)
    db.commit()


def _draft_detail(db: Session, draft: AgentDraft) -> AgentDraftDetail:
    readiness = None
    if draft.readiness_run_id:
        run = db.query(ReadinessRun).filter(ReadinessRun.id == draft.readiness_run_id).first()
        if run is not None:
            readiness = AgentReadinessResult.model_validate(run.result_json)
    return AgentDraftDetail(**_draft_summary(draft).model_dump(mode="python"), readiness=readiness)


def _draft_summary(draft: AgentDraft) -> AgentDraftSummary:
    suggestions_raw = (draft.result_json or {}).get("agentSuggestions") or []
    suggestions = [
        AgentSuggestion.model_validate(item)
        for item in suggestions_raw
        if isinstance(item, dict)
    ]
    return AgentDraftSummary(
        draftId=draft.id,
        regulationId=draft.regulation_id,
        roleMatchRunId=draft.role_match_run_id,
        readinessRunId=draft.readiness_run_id,
        title=draft.title,
        position=draft.position,
        department=draft.department,
        status=draft.status,
        progress=draft.progress,
        agentSuggestions=suggestions,
        updatedAt=draft.updated_at,
        createdAt=draft.created_at,
    )


def _status_from_readiness(readiness: AgentReadinessResult) -> str:
    if readiness.status == "finalized":
        return "finalized"
    if readiness.status == "ready":
        return "ready"
    if readiness.status == "needs_approval":
        return "changes_pending"
    return "interview"


def _get_draft(db: Session, *, user_id: str, draft_id: str) -> AgentDraft:
    draft = db.query(AgentDraft).filter(AgentDraft.id == draft_id, AgentDraft.user_id == user_id).first()
    if draft is None:
        raise AgentDraftError("Черновик агента не найден", status_code=404)
    return draft


def _get_doc_and_role_run(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    role_match_run_id: str,
) -> tuple[RegulationDocument, RoleMatchRun]:
    doc = (
        db.query(RegulationDocument)
        .filter(RegulationDocument.id == regulation_id, RegulationDocument.user_id == user_id)
        .first()
    )
    if doc is None:
        raise AgentDraftError("Регламент не найден", status_code=404)
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
        raise AgentDraftError("Запуск поиска функций не найден", status_code=404)
    return doc, run
