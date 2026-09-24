from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.db.session import SessionLocal, get_db
from app.models.user import AppUser
from app.services import org_structure, platform_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform-tasks", tags=["platform-tasks"])


class PlatformTaskCreate(BaseModel):
    assignee_fio: str = Field(..., min_length=3)
    description: str = Field(..., min_length=1, max_length=4000)
    priority: str = "normal"
    due_at: str


class PlatformTaskStatus(BaseModel):
    comment: str = ""


def _raise(exc: Exception) -> None:
    if isinstance(exc, platform_tasks.PlatformTaskError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    if isinstance(exc, org_structure.OrgStructureError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise exc


def _actor_fio(db: Session, auth: AuthContext) -> str:
    user = db.get(AppUser, auth.user_id)
    fio = (user.fio if user else "") or (auth.fio or "")
    if not fio.strip():
        raise HTTPException(status_code=403, detail="Не удалось определить ФИО пользователя")
    return fio.strip()


def run_org_sync() -> dict[str, Any]:
    db = SessionLocal()
    try:
        return org_structure.sync_org_structure(db)
    finally:
        db.close()


@router.get("/org/status")
def read_org_status(_: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return org_structure.org_status(db)


@router.post("/org/sync")
async def start_org_sync(_: AuthContext = Depends(get_current_user)) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(run_org_sync)
    except org_structure.OrgStructureError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/assignees")
def read_assignees(
    search: str = "",
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        rows = org_structure.assignable_members(db, _actor_fio(db, auth), search=search)
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    return {
        "items": [
            {"fio": row.fio, "user_id": row.user_id, "position": row.position, "department": row.department}
            for row in rows
        ]
    }


@router.get("")
def read_tasks(auth: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"items": platform_tasks.list_tasks(db, user_id=auth.user_id)}


@router.post("")
def create_task(
    body: PlatformTaskCreate,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return platform_tasks.create_task(
            db,
            author_id=auth.user_id,
            author_fio=_actor_fio(db, auth),
            assignee_fio=body.assignee_fio,
            description=body.description,
            priority=body.priority,
            due_at=platform_tasks.parse_due(body.due_at),
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
        raise


@router.post("/{task_id}/done")
def mark_done(
    task_id: str,
    body: PlatformTaskStatus | None = None,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return platform_tasks.change_status(
            db, user_id=auth.user_id, task_id=task_id, action="done", comment=(body.comment if body else "")
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
        raise


@router.post("/{task_id}/reject")
def reject(
    task_id: str,
    body: PlatformTaskStatus,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return platform_tasks.change_status(
            db, user_id=auth.user_id, task_id=task_id, action="reject", comment=body.comment
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
        raise


@router.post("/{task_id}/accept")
def accept(
    task_id: str,
    body: PlatformTaskStatus | None = None,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return platform_tasks.review_task(
            db, user_id=auth.user_id, task_id=task_id, action="accept", comment=(body.comment if body else "")
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
        raise


@router.post("/{task_id}/rework")
def rework(
    task_id: str,
    body: PlatformTaskStatus,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return platform_tasks.review_task(
            db, user_id=auth.user_id, task_id=task_id, action="rework", comment=body.comment
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
        raise


@router.post("/{task_id}/files")
def upload_file(
    task_id: str,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return platform_tasks.add_file(
            db,
            user_id=auth.user_id,
            task_id=task_id,
            filename=file.filename or "file",
            content_type=file.content_type or "",
            stream=file.file,
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
        raise


@router.get("/{task_id}/files/{file_id}")
def download_file(
    task_id: str,
    file_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        row = platform_tasks.file_for_download(db, user_id=auth.user_id, task_id=task_id, file_id=file_id)
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
        raise
    return FileResponse(row.storage_path, media_type=row.content_type, filename=row.filename)


async def platform_task_scheduler() -> None:
    """Оргструктура: при старте, если пусто или старше 12 ч, и дальше раз в 12 ч. Просрочка — раз в минуту."""
    from datetime import datetime, timedelta, timezone

    await asyncio.sleep(30)
    next_sync = datetime.now(timezone.utc)
    while True:
        db = SessionLocal()
        try:
            status = org_structure.org_status(db)
            synced = status.get("synced_at") or ""
            stale = not synced or datetime.fromisoformat(str(synced)) < datetime.now(timezone.utc) - timedelta(hours=12)
            sent = platform_tasks.notify_overdue(db)
            if sent:
                logger.info("platform tasks: overdue notifications for %s tasks", sent)
            returned = platform_tasks.return_unreviewed(db)
            if returned:
                logger.info("platform tasks: %s tasks returned to rework (review expired)", returned)
        except Exception:
            logger.exception("platform task scheduler tick failed")
            stale = False
        finally:
            db.close()
        if stale and datetime.now(timezone.utc) >= next_sync:
            next_sync = datetime.now(timezone.utc) + timedelta(hours=1)
            try:
                await asyncio.to_thread(run_org_sync)
            except Exception:
                logger.warning("org structure sync failed", exc_info=True)
        await asyncio.sleep(60)
