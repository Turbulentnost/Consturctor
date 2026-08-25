from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import get_db
from app.modules.chat.bus.producer import enqueue_command
from app.modules.chat.domain.files import resolve_stored, save_staging
from app.modules.chat.models import ChatAttachment
from app.modules.chat.queries import list_directory, list_messages, list_support_tickets, list_threads
from app.modules.chat.schemas import ActivityIn, ChatCommandIn

router = APIRouter(prefix="/chat", tags=["chat"])


def _enqueue(auth: AuthContext, body: dict) -> dict:
    payload = dict(body)
    payload["user_id"] = auth.user_id
    try:
        client_id = enqueue_command(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"accepted": True, "client_id": client_id}


@router.get("/threads")
def threads(
    search: str = "",
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": list_threads(db, auth.user_id, search)}


@router.get("/threads/{thread_id}/messages")
def messages(
    thread_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return {"items": list_messages(db, auth.user_id, thread_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/directory")
def directory(
    search: str = "",
    _: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": list_directory(db, search)}


@router.get("/support/queue")
def support_queue(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return {"items": list_support_tickets(db, auth.user_id, "queue")}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/support/mine")
def support_mine(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return {"items": list_support_tickets(db, auth.user_id, "mine")}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/support/all")
def support_all(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return {"items": list_support_tickets(db, auth.user_id, "all")}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/commands")
def commands(body: ChatCommandIn, auth: AuthContext = Depends(get_current_user)) -> dict:
    return _enqueue(auth, body.model_dump())


@router.post("/files")
async def upload_file(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_current_user),
) -> dict:
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл больше 20 МБ")
    return save_staging(auth.user_id, file.filename or "file", data, file.content_type or "")


@router.get("/files/{file_id}")
def download_file(
    file_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    from sqlalchemy import select

    from app.modules.chat.models import ChatMessage, ChatThreadMember

    row = db.get(ChatAttachment, file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    message = db.get(ChatMessage, row.message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    member = db.execute(
        select(ChatThreadMember).where(
            ChatThreadMember.thread_id == message.thread_id,
            ChatThreadMember.user_id == auth.user_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=403, detail="Нет доступа")
    path = resolve_stored(row.storage_path)
    if path is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    from app.modules.chat.crypto import decrypt_bytes, is_encrypted_file

    data = path.read_bytes()
    if is_encrypted_file(data):
        try:
            data = decrypt_bytes(data)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Не удалось расшифровать файл") from exc
    return Response(
        content=data,
        media_type=row.mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{row.filename}"'},
    )


@router.patch("/me/activity")
def set_activity(body: ActivityIn, auth: AuthContext = Depends(get_current_user)) -> dict:
    return _enqueue(auth, {"type": "set_activity", "status": body.status})
