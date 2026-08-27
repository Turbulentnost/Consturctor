from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.orchestrator import (
    OrchestratorEnsureIn,
    OrchestratorOut,
    OrchestratorPatchIn,
    OrchestratorSaveIn,
)
from app.services.orchestrator.service import (
    OrchestratorError,
    apply_tile_updates,
    ensure_orchestrator,
    get_orchestrator,
    save_formed,
)

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


def _raise(exc: OrchestratorError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/me", response_model=OrchestratorOut)
@router.get("/", response_model=OrchestratorOut)
@router.get("", response_model=OrchestratorOut)
def read_orchestrator(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrchestratorOut:
    return get_orchestrator(
        db,
        user_id=auth.user_id,
        fio=auth.fio or "",
        position=auth.position or "",
    )


@router.post("/ensure", response_model=OrchestratorOut)
def ensure_orchestrator_endpoint(
    body: OrchestratorEnsureIn | None = None,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrchestratorOut:
    payload = body or OrchestratorEnsureIn()
    try:
        return ensure_orchestrator(
            db,
            user_id=auth.user_id,
            mode=payload.mode,
            fio=auth.fio or "",
            position=auth.position or "",
        )
    except OrchestratorError as exc:
        _raise(exc)
        raise


@router.post("/me", response_model=OrchestratorOut)
@router.post("/", response_model=OrchestratorOut)
@router.post("", response_model=OrchestratorOut)
def save_orchestrator_endpoint(
    body: OrchestratorSaveIn,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrchestratorOut:
    try:
        return save_formed(
            db,
            user_id=auth.user_id,
            tiles=body.tiles,
            summary=body.summary,
            sdk_agent_id=body.sdk_agent_id,
            fio=auth.fio or "",
            position=auth.position or "",
        )
    except OrchestratorError as exc:
        _raise(exc)
        raise


@router.patch("/tiles", response_model=OrchestratorOut)
def patch_orchestrator_tiles(
    body: OrchestratorPatchIn,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrchestratorOut:
    try:
        return apply_tile_updates(
            db,
            user_id=auth.user_id,
            updates=body.tiles,
            sdk_agent_id=body.sdk_agent_id,
            fio=auth.fio or "",
            position=auth.position or "",
        )
    except OrchestratorError as exc:
        _raise(exc)
        raise
