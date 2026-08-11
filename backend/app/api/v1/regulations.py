from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.regulation import RegulationParseResult
from app.services.regulation import RegulationError, get_result, parse_upload

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
