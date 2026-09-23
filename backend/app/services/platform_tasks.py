"""Задачи платформы: постановка сотруднику, исполнение, отклонение, файлы, уведомления."""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.org import OrgMember
from app.models.platform_task import PlatformTask, PlatformTaskFile
from app.models.user import AppUser
from app.schemas.notification import NotificationCreate
from app.services.notifications.service import create_notification
from app.services.org_structure import boss_keys, fio_key, member_by_fio

logger = logging.getLogger(__name__)

PRIORITIES = ("high", "normal", "low")
PRIORITY_LABEL = {"high": "высокий", "normal": "обычный", "low": "низкий"}
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_TASK = 10


class PlatformTaskError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def parse_due(raw: str) -> datetime:
    text = (raw or "").strip()
    if not text:
        raise PlatformTaskError("Укажите срок исполнения")
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise PlatformTaskError(f"Срок в формате ISO 8601, получено: {text}") from exc


def _moscow(value: datetime) -> str:
    from zoneinfo import ZoneInfo

    return _utc(value).astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")


def _ensure_app_user(db: Session, member: OrgMember) -> AppUser:
    """Исполнитель мог ещё не входить в Оркестратор — заводим его по учётке 1С, чтобы дошло уведомление."""
    user = db.get(AppUser, member.user_id)
    if user is None:
        user = AppUser(id=member.user_id, fio=member.fio, position=member.position, department=member.department)
        db.add(user)
        db.flush()
    return user


def _notify(db: Session, *, sender_id: str, recipient_id: str, title: str, body: str) -> None:
    try:
        create_notification(
            db,
            sender_user_id=sender_id,
            payload=NotificationCreate(recipient_user_id=recipient_id, title=title[:256], body=body),
        )
    except Exception:  # noqa: BLE001 — задача важнее уведомления
        logger.exception("platform task notification failed: %s → %s", sender_id, recipient_id)


def _visible(task: PlatformTask, user_id: str) -> bool:
    return user_id in {task.author_user_id, task.assignee_user_id}


def _get(db: Session, task_id: str, user_id: str) -> PlatformTask:
    task = db.get(PlatformTask, task_id)
    if task is None or not _visible(task, user_id):
        raise PlatformTaskError("Задача не найдена", 404)
    return task


def task_out(task: PlatformTask, files: list[PlatformTaskFile], *, user_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    mine = user_id == task.assignee_user_id
    authored = user_id == task.author_user_id
    return {
        "id": task.id,
        "author_user_id": task.author_user_id,
        "author_fio": task.author_fio,
        "assignee_user_id": task.assignee_user_id,
        "assignee_fio": task.assignee_fio,
        "description": task.description,
        "priority": task.priority,
        "posted_at": _utc(task.posted_at).isoformat(),
        "due_at": _utc(task.due_at).isoformat(),
        "status": task.status,
        "status_comment": task.status_comment,
        "status_at": _utc(task.status_at).isoformat() if task.status_at else None,
        "overdue": task.status == "open" and _utc(task.due_at) < now,
        "role": "both" if mine and authored else "assignee" if mine else "author",
        "files": [{"id": f.id, "filename": f.filename, "size": f.size} for f in files],
    }


def _files_by_task(db: Session, task_ids: list[str]) -> dict[str, list[PlatformTaskFile]]:
    grouped: dict[str, list[PlatformTaskFile]] = {task_id: [] for task_id in task_ids}
    if task_ids:
        rows = db.execute(
            select(PlatformTaskFile)
            .where(PlatformTaskFile.task_id.in_(task_ids))
            .order_by(PlatformTaskFile.created_at)
        ).scalars()
        for row in rows:
            grouped.setdefault(row.task_id, []).append(row)
    return grouped


def list_tasks(db: Session, *, user_id: str) -> list[dict[str, Any]]:
    tasks = list(
        db.execute(
            select(PlatformTask)
            .where(or_(PlatformTask.author_user_id == user_id, PlatformTask.assignee_user_id == user_id))
            .order_by(PlatformTask.due_at.asc())
            .limit(1000)
        ).scalars()
    )
    files = _files_by_task(db, [task.id for task in tasks])
    return [task_out(task, files.get(task.id, []), user_id=user_id) for task in tasks]


def create_task(
    db: Session,
    *,
    author_id: str,
    author_fio: str,
    assignee_fio: str,
    description: str,
    priority: str,
    due_at: datetime,
) -> dict[str, Any]:
    text = description.strip()
    if not text:
        raise PlatformTaskError("Опишите задачу")
    if priority not in PRIORITIES:
        raise PlatformTaskError("Приоритет: high | normal | low")
    now = datetime.now(timezone.utc)
    if _utc(due_at) <= now:
        raise PlatformTaskError("Срок исполнения должен быть позже текущего момента")
    member = member_by_fio(db, assignee_fio)
    if member is None or not member.user_id:
        raise PlatformTaskError("Сотрудник не найден в оргструктуре или у него нет учётной записи 1С", 404)
    if fio_key(member.fio) == fio_key(author_fio):
        raise PlatformTaskError("Нельзя поставить задачу самому себе")
    if fio_key(member.fio) in boss_keys(db, author_fio):
        raise PlatformTaskError(f"{member.fio} — ваш руководитель: ставить задачи вышестоящим нельзя", 403)
    if db.get(AppUser, author_id) is None:
        raise PlatformTaskError("Автор задачи не найден среди пользователей Оркестратора", 403)
    assignee = _ensure_app_user(db, member)
    task = PlatformTask(
        id=str(uuid.uuid4()),
        author_user_id=author_id,
        author_fio=author_fio,
        assignee_user_id=assignee.id,
        assignee_fio=member.fio,
        description=text,
        priority=priority,
        posted_at=now,
        due_at=_utc(due_at),
        status="open",
    )
    db.add(task)
    db.commit()
    _notify(
        db,
        sender_id=author_id,
        recipient_id=assignee.id,
        title=f"Новая задача от {author_fio}",
        body=f"{text[:400]}\nСрок: {_moscow(task.due_at)}, приоритет {PRIORITY_LABEL[priority]}.",
    )
    return task_out(task, [], user_id=author_id)


def change_status(db: Session, *, user_id: str, task_id: str, action: str, comment: str = "") -> dict[str, Any]:
    task = _get(db, task_id, user_id)
    if task.assignee_user_id != user_id:
        raise PlatformTaskError("Исполнить или отклонить задачу может только исполнитель", 403)
    if task.status != "open":
        raise PlatformTaskError("Задача уже закрыта")
    note = comment.strip()
    if action == "reject" and not note:
        raise PlatformTaskError("Укажите причину отклонения")
    task.status = "done" if action == "done" else "rejected"
    task.status_comment = note
    task.status_at = datetime.now(timezone.utc)
    db.commit()
    verb = "исполнил" if action == "done" else "отклонил"
    _notify(
        db,
        sender_id=user_id,
        recipient_id=task.author_user_id,
        title=f"{task.assignee_fio} {verb} задачу",
        body=task.description[:400] + (f"\nКомментарий: {note}" if note else ""),
    )
    return task_out(task, _files_by_task(db, [task.id]).get(task.id, []), user_id=user_id)


_SAFE_NAME = re.compile(r"[^\w.\-() ]+", re.UNICODE)


def add_file(
    db: Session, *, user_id: str, task_id: str, filename: str, content_type: str, stream: BinaryIO
) -> dict[str, Any]:
    task = _get(db, task_id, user_id)
    if task.author_user_id != user_id:
        raise PlatformTaskError("Файлы прикладывает постановщик задачи", 403)
    existing = _files_by_task(db, [task.id]).get(task.id, [])
    if len(existing) >= MAX_FILES_PER_TASK:
        raise PlatformTaskError(f"Не больше {MAX_FILES_PER_TASK} файлов на задачу")
    file_id = str(uuid.uuid4())
    safe = _SAFE_NAME.sub("_", Path(filename or "file").name).strip() or "file"
    folder = settings.platform_task_storage_dir / task.id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{file_id}_{safe}"
    with target.open("wb") as handle:
        shutil.copyfileobj(stream, handle, length=1024 * 1024)
    size = target.stat().st_size
    if size > MAX_FILE_BYTES:
        target.unlink(missing_ok=True)
        raise PlatformTaskError("Файл больше 25 МБ")
    row = PlatformTaskFile(
        id=file_id,
        task_id=task.id,
        filename=Path(filename or safe).name,
        content_type=content_type or "application/octet-stream",
        size=size,
        storage_path=str(target),
        uploaded_by=user_id,
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "filename": row.filename, "size": row.size}


def file_for_download(db: Session, *, user_id: str, task_id: str, file_id: str) -> PlatformTaskFile:
    _get(db, task_id, user_id)
    row = db.get(PlatformTaskFile, file_id)
    if row is None or row.task_id != task_id or not Path(row.storage_path).is_file():
        raise PlatformTaskError("Файл не найден", 404)
    return row


def notify_overdue(db: Session) -> int:
    """Один раз на задачу: срок прошёл, а она открыта — пишем обоим."""
    now = datetime.now(timezone.utc)
    rows = list(
        db.execute(
            select(PlatformTask)
            .where(
                PlatformTask.status == "open",
                PlatformTask.due_at < now,
                PlatformTask.overdue_notified_at.is_(None),
            )
            .limit(200)
        ).scalars()
    )
    for task in rows:
        task.overdue_notified_at = now
    if rows:
        db.commit()
    for task in rows:
        body = f"{task.description[:400]}\nСрок был: {_moscow(task.due_at)}."
        _notify(
            db,
            sender_id=task.author_user_id,
            recipient_id=task.assignee_user_id,
            title=f"Просрочена задача от {task.author_fio}",
            body=body,
        )
        _notify(
            db,
            sender_id=task.assignee_user_id,
            recipient_id=task.author_user_id,
            title=f"Просрочена задача: исполнитель {task.assignee_fio}",
            body=body,
        )
    return len(rows)
