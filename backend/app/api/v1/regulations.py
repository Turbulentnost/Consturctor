from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.models.regulation import RegulationRevision
from app.schemas.regulation import (
    AgentDraftDetail,
    RegulationParseResult,
    AgentReadinessResult,
    ChangeDecisionRequest,
    ReadinessAnswerRequest,
    RegulationRevisionResult,
    RoleMatchDecisionRequest,
    RoleMatchRequest,
    RoleMatchResult,
)
from app.services.agents import AgentDraftError, create_or_get_draft
from app.services.app_users import get_app_user
from app.services.regulation import RegulationError, get_result, parse_upload
from app.services.role_matching import (
    RoleMatchError,
    create_role_match_run,
    get_role_match_run,
    update_match_status,
)
from app.services.readiness import (
    ReadinessError,
    answer_readiness_question,
    create_readiness_run,
    finalize_readiness_run,
    get_readiness_run,
    update_change_status,
)

router = APIRouter(prefix="/regulations", tags=["regulations"])


@router.post("/upload", response_model=RegulationParseResult)
async def upload_regulation(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
) -> RegulationParseResult:
    data = await file.read()
    try:
        return parse_upload(
            db,
            user_id=auth.user_id,
            filename=file.filename or "regulation",
            content_type=file.content_type or "",
            data=data,
        )
    except RegulationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{regulation_id}", response_model=RegulationParseResult)
async def get_regulation(
    regulation_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationParseResult:
    try:
        return get_result(db, regulation_id=regulation_id, user_id=auth.user_id)
    except RegulationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{regulation_id}/role-matches", response_model=RoleMatchResult)
async def create_role_matches(
    regulation_id: str,
    request: RoleMatchRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoleMatchResult:
    user = get_app_user(auth.user_id)
    position = (request.position or "").strip() or ((user.position if user else "") or "").strip()
    department = (request.department or "").strip() or ((user.department if user else "") or "").strip()
    try:
        return create_role_match_run(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            position=position,
            department=department,
        )
    except RoleMatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{regulation_id}/role-matches/{run_id}", response_model=RoleMatchResult)
async def get_role_matches(
    regulation_id: str,
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoleMatchResult:
    try:
        return get_role_match_run(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            run_id=run_id,
        )
    except RoleMatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{regulation_id}/role-matches/{run_id}/draft", response_model=AgentDraftDetail)
async def create_role_match_draft(
    regulation_id: str,
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentDraftDetail:
    try:
        return create_or_get_draft(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            role_match_run_id=run_id,
        )
    except AgentDraftError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch(
    "/{regulation_id}/role-matches/{run_id}/{match_id}",
    response_model=RoleMatchResult,
)
async def decide_role_match(
    regulation_id: str,
    run_id: str,
    match_id: str,
    request: RoleMatchDecisionRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoleMatchResult:
    try:
        return update_match_status(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            run_id=run_id,
            match_id=match_id,
            status=request.status,
        )
    except RoleMatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/{regulation_id}/role-matches/{run_id}/readiness",
    response_model=AgentReadinessResult,
)
async def create_readiness(
    regulation_id: str,
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentReadinessResult:
    try:
        return create_readiness_run(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            role_match_run_id=run_id,
        )
    except ReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{regulation_id}/readiness/{readiness_run_id}", response_model=AgentReadinessResult)
async def get_readiness(
    regulation_id: str,
    readiness_run_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentReadinessResult:
    try:
        return get_readiness_run(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            readiness_run_id=readiness_run_id,
        )
    except ReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/{regulation_id}/readiness/{readiness_run_id}/answers",
    response_model=AgentReadinessResult,
)
async def answer_readiness(
    regulation_id: str,
    readiness_run_id: str,
    request: ReadinessAnswerRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentReadinessResult:
    try:
        return answer_readiness_question(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            readiness_run_id=readiness_run_id,
            request=request,
        )
    except ReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch(
    "/{regulation_id}/readiness/{readiness_run_id}/changes/{change_id}",
    response_model=AgentReadinessResult,
)
async def decide_change(
    regulation_id: str,
    readiness_run_id: str,
    change_id: str,
    request: ChangeDecisionRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentReadinessResult:
    try:
        return update_change_status(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            readiness_run_id=readiness_run_id,
            change_id=change_id,
            request=request,
        )
    except ReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/{regulation_id}/readiness/{readiness_run_id}/finalize",
    response_model=RegulationRevisionResult,
)
async def finalize_readiness(
    regulation_id: str,
    readiness_run_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationRevisionResult:
    try:
        return finalize_readiness_run(
            db,
            user_id=auth.user_id,
            regulation_id=regulation_id,
            readiness_run_id=readiness_run_id,
        )
    except ReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{regulation_id}/revisions/{revision_id}/download")
async def download_revision(
    regulation_id: str,
    revision_id: str,
    kind: str = "document",
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    revision = (
        db.query(RegulationRevision)
        .filter(
            RegulationRevision.id == revision_id,
            RegulationRevision.regulation_id == regulation_id,
            RegulationRevision.user_id == auth.user_id,
        )
        .first()
    )
    if revision is None:
        raise HTTPException(status_code=404, detail="Версия регламента не найдена")
    path = Path(revision.protocol_path if kind == "protocol" else revision.document_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл версии не найден")
    return FileResponse(str(path), filename=path.name)
