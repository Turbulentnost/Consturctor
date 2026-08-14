from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.regulation import RegulationCreationSendRequest, RegulationCreationSession
from app.services.regulation_creation import (
    RegulationCreationError,
    get_creation_session,
    send_creation_message,
    start_creation_session,
    stream_creation_message,
    terminate_active_creation_sessions,
)

router = APIRouter(prefix="/regulation-creation", tags=["regulation-creation"])


@router.post("/sessions", response_model=RegulationCreationSession)
async def create_regulation_creation_session(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationSession:
    try:
        return start_creation_session(db, user_id=auth.user_id)
    except RegulationCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/sessions/{draft_id}", response_model=RegulationCreationSession)
async def read_regulation_creation_session(
    draft_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationSession:
    try:
        return get_creation_session(db, user_id=auth.user_id, draft_id=draft_id)
    except RegulationCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/sessions/{draft_id}/messages", response_model=RegulationCreationSession)
async def send_regulation_creation_session_message(
    draft_id: str,
    request: RegulationCreationSendRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationSession:
    try:
        return send_creation_message(db, user_id=auth.user_id, draft_id=draft_id, request=request)
    except RegulationCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/sessions/{draft_id}/messages/stream")
async def stream_regulation_creation_session_message(
    draft_id: str,
    request: RegulationCreationSendRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    def generate():
        try:
            for item in stream_creation_message(db, user_id=auth.user_id, draft_id=draft_id, request=request):
                yield f"event: {item.get('type', 'message')}\n"
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        except RegulationCreationError as exc:
            payload = {"type": "error", "message": exc.message}
            yield "event: error\n"
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sessions/terminate-active")
async def terminate_regulation_creation_sessions(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return terminate_active_creation_sessions(db, user_id=auth.user_id)
    except RegulationCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
