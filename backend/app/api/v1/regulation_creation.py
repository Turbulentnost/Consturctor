from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.schemas.regulation import RegulationCreationSendRequest, RegulationCreationSession
from app.services.regulation_creation import (
    RegulationCreationError,
    get_creation_document,
    get_creation_session,
    send_creation_message,
    start_creation_session,
    stream_creation_message,
    terminate_active_creation_sessions,
)

router = APIRouter(prefix="/regulation-creation", tags=["regulation-creation"])


async def _parse_send_payload(request: Request) -> tuple[RegulationCreationSendRequest, list[tuple[str, bytes]]]:
    content_type = (request.headers.get("content-type") or "").lower()
    files: list[tuple[str, bytes]] = []
    if "multipart/form-data" in content_type:
        form = await request.form()
        message = str(form.get("message") or "")
        uploads = form.getlist("files")
        for item in uploads:
            filename = str(getattr(item, "filename", None) or "file")
            read = getattr(item, "read", None)
            if read is None:
                continue
            data = await read()
            if data:
                files.append((filename, bytes(data)))
        return RegulationCreationSendRequest(message=message), files
    body = await request.json()
    return RegulationCreationSendRequest.model_validate(body), files


@router.post("/sessions", response_model=RegulationCreationSession)
async def create_regulation_creation_session(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RegulationCreationSession:
    try:
        return start_creation_session(db, user_id=auth.user_id)
    except RegulationCreationError as exc:
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
            payload_err = {"type": "error", "message": exc.message}
            yield "event: error\n"
            yield f"data: {json.dumps(payload_err, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
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
