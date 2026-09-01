from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.regulation import (
    RegulationCreationApplyRequest,
    RegulationCreationSendRequest,
    RegulationCreationSession,
    RegulationCreationTurn,
)
from app.services.regulation_creation import (
    RegulationCreationError,
    apply_creation_reply,
    get_active_creation_session,
    get_creation_document,
    get_creation_session,
    peek_creation_turn,
    persist_creation_turn,
    send_creation_message,
    start_creation_session,
    stream_creation_message,
    terminate_active_creation_sessions,
)

router = APIRouter(prefix="/regulation-creation", tags=["regulation-creation"])
logger = logging.getLogger(__name__)


async def _parse_send_payload(request: Request) -> tuple[RegulationCreationSendRequest, list[tuple[str, bytes]]]:
    content_type = (request.headers.get("content-type") or "").lower()
    files: list[tuple[str, bytes]] = []
    if "multipart/form-data" in content_type:
        form = await request.form()
        message = str(form.get("message") or "")
        uploads = list(form.getlist("files")) + list(form.getlist("file"))
        for item in uploads:
            read = getattr(item, "read", None)
            if read is None:
                continue
            data = await read()
            filename = str(getattr(item, "filename", None) or "file")
            if data:
                files.append((filename, bytes(data)))
        return RegulationCreationSendRequest(message=message), files
    body = await request.json()
    return RegulationCreationSendRequest.model_validate(body), files


@router.post("/sessions", response_model=RegulationCreationSession)
async def create_regulation_creation_session(
    fresh: bool = Query(False),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationSession:
    try:
        return start_creation_session(db, user_id=auth.user_id, fresh=fresh)
    except RegulationCreationError as exc:
        logger.warning(
            "reg_create turn failed draft_id=%s status=%s detail=%s",
            draft_id,
            exc.status_code,
            ascii(exc.message),
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/sessions/active", response_model=RegulationCreationSession)
async def read_active_regulation_creation_session(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationSession:
    session = get_active_creation_session(db, user_id=auth.user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Нет активного черновика")
    return session


@router.get("/sessions/{draft_id}/turn", response_model=RegulationCreationTurn)
async def peek_regulation_creation_turn(
    draft_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationTurn:
    try:
        return peek_creation_turn(db, user_id=auth.user_id, draft_id=draft_id)
    except RegulationCreationError as exc:
        logger.warning(
            "reg_create message failed draft_id=%s status=%s detail=%s",
            draft_id,
            exc.status_code,
            ascii(exc.message),
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/sessions/{draft_id}/document")
async def download_regulation_creation_document(
    draft_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        path = get_creation_document(db, user_id=auth.user_id, draft_id=draft_id)
    except RegulationCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return FileResponse(
        str(path),
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


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


@router.post("/sessions/{draft_id}/turns", response_model=RegulationCreationTurn)
async def persist_regulation_creation_turn(
    draft_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationTurn:
    try:
        payload, files = await _parse_send_payload(request)
        return persist_creation_turn(
            db,
            user_id=auth.user_id,
            draft_id=draft_id,
            request=payload,
            files=files,
        )
    except RegulationCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/sessions/{draft_id}/apply", response_model=RegulationCreationSession)
async def apply_regulation_creation_reply(
    draft_id: str,
    request: RegulationCreationApplyRequest,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationSession:
    try:
        return apply_creation_reply(
            db,
            user_id=auth.user_id,
            draft_id=draft_id,
            request=request,
        )
    except RegulationCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/sessions/{draft_id}/messages", response_model=RegulationCreationSession)
async def send_regulation_creation_session_message(
    draft_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationSession:
    try:
        payload, files = await _parse_send_payload(request)
        return send_creation_message(
            db,
            user_id=auth.user_id,
            draft_id=draft_id,
            request=payload,
            files=files,
        )
    except RegulationCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ошибка обработки сообщения: {exc}") from exc


@router.post("/sessions/{draft_id}/messages/stream")
async def stream_regulation_creation_session_message(
    draft_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    try:
        payload, files = await _parse_send_payload(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("reg_create stream payload parse failed draft_id=%s detail=%s", draft_id, ascii(str(exc)))
        raise HTTPException(status_code=400, detail=f"Некорректный запрос: {exc}") from exc

    def generate():
        try:
            for item in stream_creation_message(
                db,
                user_id=auth.user_id,
                draft_id=draft_id,
                request=payload,
                files=files,
            ):
                yield f"event: {item.get('type', 'message')}\n"
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        except RegulationCreationError as exc:
            logger.warning(
                "reg_create stream failed draft_id=%s status=%s detail=%s",
                draft_id,
                exc.status_code,
                ascii(exc.message),
            )
            payload_err = {"type": "error", "message": exc.message}
            yield "event: error\n"
            yield f"data: {json.dumps(payload_err, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("reg_create stream unexpected failed draft_id=%s detail=%s", draft_id, ascii(str(exc)))
            payload_err = {"type": "error", "message": f"Ошибка создания регламента: {exc}"}
            yield "event: error\n"
            yield f"data: {json.dumps(payload_err, ensure_ascii=False)}\n\n"

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
