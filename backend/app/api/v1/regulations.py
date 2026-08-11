from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.regulation import (
    RegulationParseResult,
    RoleMatchDecisionRequest,
    RoleMatchRequest,
    RoleMatchResult,
)
from app.services.app_users import get_app_user
from app.services.regulation import RegulationError, get_result, parse_upload
from app.services.role_matching import (
    RoleMatchError,
    create_role_match_run,
    get_role_match_run,
    update_match_status,
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
