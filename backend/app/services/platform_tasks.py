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
RECURRENCE_LABEL = {
    "daily": "ежедневно",
    "weekly": "еженедельно",
    "monthly": "ежемесячно",
    "quarterly": "ежеквартально",
    "yearly": "ежегодно",
}
_RECURRENCE_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
MAX_BASIS_CHARS = 2000
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


def parse_recurrence(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in {"", "none", "once"}:
        return ""
    if value not in RECURRENCE_LABEL:
        raise PlatformTaskError("Периодичность: daily | weekly | monthly | quarterly | yearly или пусто")
    return value


def parse_optional_moment(raw: str | None) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise PlatformTaskError(f"Дата в формате ISO 8601, получено: {text}") from exc


def shift_period(moment: datetime, recurrence: str) -> datetime:
    """Тот же час по Москве через период. 31 января + месяц = 28 (29) февраля."""
    import calendar
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    msk = ZoneInfo("Europe/Moscow")
    local = _utc(moment).astimezone(msk)
    if recurrence == "daily":
        return _utc((local + timedelta(days=1)).astimezone(timezone.utc))
    if recurrence == "weekly":
        return _utc((local + timedelta(days=7)).astimezone(timezone.utc))
    months = _RECURRENCE_MONTHS[recurrence]
    total = local.month - 1 + months
    year, month = local.year + total // 12, total % 12 + 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day).astimezone(timezone.utc)


def _moscow(value: datetime) -> str:
    from zoneinfo import ZoneInfo

    return _utc(value).astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")


def end_of_day(moment: datetime | None = None) -> datetime:
    """23:59 московского дня, в котором наступил moment."""
    from zoneinfo import ZoneInfo

    msk = ZoneInfo("Europe/Moscow")
    local = _utc(moment or datetime.now(timezone.utc)).astimezone(msk)
    return local.replace(hour=23, minute=59, second=0, microsecond=0).astimezone(timezone.utc)


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


def awaiting_review(task: PlatformTask) -> bool:
    """Исполнитель закрыл задачу, постановщик ещё не принял результат."""
    return task.status in {"done", "rejected"} and task.accepted_at is None


def task_out(task: PlatformTask, files: list[PlatformTaskFile], *, user_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    mine = user_id == task.assignee_user_id
    authored = user_id == task.author_user_id
    review = awaiting_review(task)
    review_due = _utc(task.review_due_at) if task.review_due_at else None
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
        "awaiting_review": review,
        "review_due_at": review_due.isoformat() if review_due else None,
        "review_overdue": bool(review and review_due and review_due < now),
        "accepted_at": _utc(task.accepted_at).isoformat() if task.accepted_at else None,
        "rework_count": int(task.rework_count or 0),
        "basis": task.basis or "",
        "recurrence": task.recurrence or "",
        "recurrence_until": _utc(task.recurrence_until).isoformat() if task.recurrence_until else None,
        "series_id": task.series_id or "",
        "source": task.source or "",
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
    basis: str = "",
    recurrence: str = "",
    recurrence_until: datetime | None = None,
) -> dict[str, Any]:
    text, basis_text, recurrence = _check_fields(description, priority, due_at, basis, recurrence, recurrence_until)
    now = datetime.now(timezone.utc)
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
    task_id = str(uuid.uuid4())
    task = PlatformTask(
        id=task_id,
        author_user_id=author_id,
        author_fio=author_fio,
        assignee_user_id=assignee.id,
        assignee_fio=member.fio,
        description=text,
        priority=priority,
        posted_at=now,
        due_at=_utc(due_at),
        status="open",
        basis=basis_text,
        recurrence=recurrence,
        recurrence_until=_utc(recurrence_until) if recurrence and recurrence_until else None,
        series_id=task_id if recurrence else "",
    )
    db.add(task)
    db.commit()
    _notify(
        db,
        sender_id=author_id,
        recipient_id=assignee.id,
        title=f"Новая задача от {author_fio}",
        body=_task_body(task),
    )
    return task_out(task, [], user_id=author_id)


def create_agent_task(
    db: Session,
    *,
    source: str,
    source_ref: str,
    author_label: str,
    notify_sender_id: str,
    assignee_user_id: str,
    description: str,
    basis: str,
    due_at: datetime,
    priority: str = "normal",
    recurrence: str = "",
    recurrence_until: datetime | None = None,
) -> dict[str, Any]:
    """Задача от системы по документу: без проверки подчинённости, результат принимается сразу."""
    text, basis_text, recurrence = _check_fields(description, priority, due_at, basis, recurrence, recurrence_until)
    if not basis_text:
        raise PlatformTaskError("У задачи от агента должно быть основание")
    member = db.scalar(select(OrgMember).where(OrgMember.user_id == assignee_user_id).limit(1))
    user = db.get(AppUser, assignee_user_id)
    if member is None and user is None:
        raise PlatformTaskError("Исполнитель не найден", 404)
    assignee = user or _ensure_app_user(db, member)
    now = datetime.now(timezone.utc)
    task_id = str(uuid.uuid4())
    task = PlatformTask(
        id=task_id,
        author_user_id=source,
        author_fio=author_label,
        assignee_user_id=assignee.id,
        assignee_fio=(member.fio if member else assignee.fio) or assignee.fio,
        description=text,
        priority=priority,
        posted_at=now,
        due_at=_utc(due_at),
        status="open",
        basis=basis_text,
        recurrence=recurrence,
        recurrence_until=_utc(recurrence_until) if recurrence and recurrence_until else None,
        series_id=task_id if recurrence else "",
        source=source,
        source_ref=source_ref[:256],
    )
    db.add(task)
    db.commit()
    _notify(
        db,
        sender_id=notify_sender_id,
        recipient_id=assignee.id,
        title=f"Новая задача: {author_label}"[:256],
        body=_task_body(task),
    )
    return task_out(task, [], user_id=assignee.id)


def _check_fields(
    description: str,
    priority: str,
    due_at: datetime,
    basis: str,
    recurrence: str,
    recurrence_until: datetime | None,
) -> tuple[str, str, str]:
    text = (description or "").strip()
    if not text:
        raise PlatformTaskError("Опишите задачу")
    if priority not in PRIORITIES:
        raise PlatformTaskError("Приоритет: high | normal | low")
    if _utc(due_at) <= datetime.now(timezone.utc):
        raise PlatformTaskError("Срок исполнения должен быть позже текущего момента")
    basis_text = (basis or "").strip()
    if len(basis_text) > MAX_BASIS_CHARS:
        raise PlatformTaskError(f"Основание не длиннее {MAX_BASIS_CHARS} символов")
    period = parse_recurrence(recurrence)
    if period and recurrence_until is not None and _utc(recurrence_until) <= _utc(due_at):
        raise PlatformTaskError("Повторять до — позже срока первой задачи")
    return text, basis_text, period


def _task_body(task: PlatformTask) -> str:
    lines = [task.description[:400], f"Срок: {_moscow(task.due_at)}, приоритет {PRIORITY_LABEL[task.priority]}."]
    if task.recurrence:
        until = f" до {_moscow(task.recurrence_until)}" if task.recurrence_until else ""
        lines.append(f"Повторяется {RECURRENCE_LABEL[task.recurrence]}{until}.")
    if task.basis:
        lines.append(f"Основание: {task.basis[:300]}")
    return "\n".join(lines)


def is_agent_task(task: PlatformTask) -> bool:
    return bool(task.source)


def spawn_recurring(db: Session) -> int:
    """Пришло время следующего повторения — ставим его тому же исполнителю."""
    now = datetime.now(timezone.utc)
    rows = list(
        db.execute(
            select(PlatformTask)
            .where(PlatformTask.recurrence != "", PlatformTask.next_spawned_at.is_(None))
            .limit(500)
        ).scalars()
    )
    created: list[PlatformTask] = []
    for task in rows:
        if task.recurrence not in RECURRENCE_LABEL:
            task.next_spawned_at = now
            continue
        posted = shift_period(task.posted_at, task.recurrence)
        if posted > now:
            continue
        due = shift_period(task.due_at, task.recurrence)
        while due <= now:
            posted, due = shift_period(posted, task.recurrence), shift_period(due, task.recurrence)
        task.next_spawned_at = now
        if task.recurrence_until is not None and due > _utc(task.recurrence_until):
            continue
        child = PlatformTask(
            id=str(uuid.uuid4()),
            author_user_id=task.author_user_id,
            author_fio=task.author_fio,
            assignee_user_id=task.assignee_user_id,
            assignee_fio=task.assignee_fio,
            description=task.description,
            priority=task.priority,
            posted_at=min(posted, now),
            due_at=due,
            status="open",
            basis=task.basis,
            recurrence=task.recurrence,
            recurrence_until=task.recurrence_until,
            series_id=task.series_id or task.id,
            source=task.source,
            source_ref=task.source_ref,
        )
        db.add(child)
        created.append(child)
    if rows:
        db.commit()
    for child in created:
        _notify(
            db,
            sender_id=child.author_user_id if not child.source else child.assignee_user_id,
            recipient_id=child.assignee_user_id,
            title=f"Периодическая задача от {child.author_fio}"[:256],
            body=_task_body(child),
        )
    return len(created)


def change_status(db: Session, *, user_id: str, task_id: str, action: str, comment: str = "") -> dict[str, Any]:
    task = _get(db, task_id, user_id)
    if task.assignee_user_id != user_id:
        raise PlatformTaskError("Исполнить или отклонить задачу может только исполнитель", 403)
    if task.status != "open":
        raise PlatformTaskError("Задача уже закрыта")
    note = comment.strip()
    if action == "reject" and not note:
        raise PlatformTaskError("Укажите причину отклонения")
    now = datetime.now(timezone.utc)
    task.status = "done" if action == "done" else "rejected"
    task.status_comment = note
    task.status_at = now
    task.accepted_at = None
    if is_agent_task(task):
        # Принимать результат некому: задачу поставила система по документу.
        task.accepted_at = now
        task.review_due_at = None
        db.commit()
        return task_out(task, _files_by_task(db, [task.id]).get(task.id, []), user_id=user_id)
    # Приёмка — задача постановщику на остаток дня. Не принял до 23:59 — уходит на доработку.
    task.review_due_at = end_of_day(now)
    db.commit()
    verb = "исполнил" if action == "done" else "отклонил"
    _notify(
        db,
        sender_id=user_id,
        recipient_id=task.author_user_id,
        title=f"Примите задачу: {task.assignee_fio} {verb}",
        body=(
            task.description[:400]
            + (f"\nКомментарий: {note}" if note else "")
            + f"\nПринять до {_moscow(task.review_due_at)}, иначе задача вернётся на доработку."
        ),
    )
    return task_out(task, _files_by_task(db, [task.id]).get(task.id, []), user_id=user_id)


def _to_rework(task: PlatformTask, *, comment: str, now: datetime) -> None:
    """Вернуть задачу исполнителю с тем же сроком."""
    task.status = "open"
    task.status_comment = comment
    task.status_at = now
    task.review_due_at = None
    task.accepted_at = None
    task.rework_count = int(task.rework_count or 0) + 1
    # Новый круг работы: просрочку по этому сроку сообщаем заново.
    task.overdue_notified_at = None


def review_task(db: Session, *, user_id: str, task_id: str, action: str, comment: str = "") -> dict[str, Any]:
    """Постановщик принимает результат либо возвращает задачу на доработку."""
    task = _get(db, task_id, user_id)
    if task.author_user_id != user_id:
        raise PlatformTaskError("Принять результат или вернуть на доработку может только постановщик", 403)
    if not awaiting_review(task):
        raise PlatformTaskError("Задача не на приёмке")
    if action not in {"accept", "rework"}:
        raise PlatformTaskError("Действие: accept | rework")
    note = comment.strip()
    now = datetime.now(timezone.utc)
    if action == "accept":
        task.accepted_at = now
        task.review_due_at = None
        if note:
            task.status_comment = (task.status_comment + f"\nПриёмка: {note}").strip()
        title = f"{task.author_fio} принял задачу"
        body = task.description[:400] + (f"\nКомментарий: {note}" if note else "")
    else:
        if not note:
            raise PlatformTaskError("Напишите, что доработать")
        _to_rework(task, comment=f"На доработку: {note}", now=now)
        title = f"{task.author_fio} вернул задачу на доработку"
        body = f"{task.description[:400]}\nЧто доработать: {note}\nСрок тот же: {_moscow(task.due_at)}."
    db.commit()
    _notify(db, sender_id=user_id, recipient_id=task.assignee_user_id, title=title, body=body)
    return task_out(task, _files_by_task(db, [task.id]).get(task.id, []), user_id=user_id)


def return_unreviewed(db: Session) -> int:
    """Постановщик не принял результат до конца дня — задача уходит на доработку с тем же сроком."""
    now = datetime.now(timezone.utc)
    rows = list(
        db.execute(
            select(PlatformTask)
            .where(
                PlatformTask.status.in_(("done", "rejected")),
                PlatformTask.accepted_at.is_(None),
                PlatformTask.review_due_at.is_not(None),
                PlatformTask.review_due_at < now,
            )
            .limit(200)
        ).scalars()
    )
    for task in rows:
        _to_rework(task, comment="Возврат на доработку: постановщик не принял результат до конца дня", now=now)
    if rows:
        db.commit()
    for task in rows:
        body = (
            f"{task.description[:400]}\nПостановщик не принял результат до конца дня. "
            f"Срок тот же: {_moscow(task.due_at)}."
        )
        _notify(
            db,
            sender_id=task.author_user_id,
            recipient_id=task.assignee_user_id,
            title=f"Задача вернулась на доработку: {task.author_fio}",
            body=body,
        )
        _notify(
            db,
            sender_id=task.assignee_user_id,
            recipient_id=task.author_user_id,
            title=f"Приёмка просрочена: задача снова у {task.assignee_fio}",
            body=body,
        )
    return len(rows)


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
            sender_id=task.author_user_id if not is_agent_task(task) else task.assignee_user_id,
            recipient_id=task.assignee_user_id,
            title=f"Просрочена задача от {task.author_fio}",
            body=body,
        )
        if is_agent_task(task):
            continue
        _notify(
            db,
            sender_id=task.assignee_user_id,
            recipient_id=task.author_user_id,
            title=f"Просрочена задача: исполнитель {task.assignee_fio}",
            body=body,
        )
    return len(rows)
