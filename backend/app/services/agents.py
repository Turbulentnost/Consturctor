from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.regulation import AgentDraft, ReadinessRun, RegulationDocument, RoleMatchRun
from app.schemas.regulation import (
    AgentDraftDetail,
    AgentDraftListResult,
    AgentDraftStatusRequest,
    AgentDraftSummary,
    AgentReadinessResult,
    RoleMatchResult,
)
from app.services.readiness.service import create_readiness_run


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
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _draft_detail(db, draft)


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
