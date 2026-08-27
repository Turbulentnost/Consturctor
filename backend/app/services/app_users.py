from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db.session import SessionLocal
from app.models.user import AppUser
from app.schemas.auth import UserOut

logger = logging.getLogger(__name__)

DEPARTMENT_CHANGE_COOLDOWN = timedelta(days=14)


def avatar_url_for(user: AppUser | None) -> str | None:
    if user is None or not user.avatar_path:
        return None
    path = Path(user.avatar_path)
    if not path.is_absolute():
        path = settings.avatar_storage_dir / path
    if not path.is_file():
        return None
    version = ""
    if getattr(user, "updated_at", None) is not None:
        version = f"?v={int(user.updated_at.timestamp())}"
    return f"/api/v1/auth/users/{user.id}/avatar{version}"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def department_change_state(user: AppUser) -> tuple[bool, datetime | None]:
    changed = _as_utc(user.department_changed_at)
    if changed is None:
        return True, None
    available = changed + DEPARTMENT_CHANGE_COOLDOWN
    now = datetime.now(timezone.utc)
    if now >= available:
        return True, None
    return False, available


def to_user_out(user: AppUser) -> UserOut:
    can_change, available_at = department_change_state(user)
    return UserOut(
        id=user.id,
        fio=user.fio,
        department=user.department or "",
        position=user.position or "",
        avatar_url=avatar_url_for(user),
        can_change_department=can_change,
        department_change_available_at=available_at,
        activity_status=getattr(user, "activity_status", None) or "online",
        is_support=bool(getattr(user, "is_support", False)),
    )


def upsert_app_user(
    *,
    user_id: str,
    fio: str,
    department: str,
    position: str = "",
) -> AppUser:
    with SessionLocal() as db:
        user = db.get(AppUser, user_id)
        if user is None:
            user = AppUser(
                id=user_id,
                fio=fio,
                department=department or "",
                position=position or "",
            )
            db.add(user)
            logger.info("Created app user id=%s", user_id)
        else:
            user.fio = fio
            # Keep app department as source of truth after first login.
            if not (user.department or "").strip() and department:
                user.department = department
            # Position always refreshes from ERP when available.
            if position:
                user.position = position
            logger.info("Updated app user id=%s", user_id)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def get_app_user(user_id: str) -> AppUser | None:
    with SessionLocal() as db:
        user = db.get(AppUser, user_id)
        if user is None:
            return None
        db.expunge(user)
        return user


def find_app_user_by_fio(fio: str) -> AppUser | None:
    needle = " ".join((fio or "").split())
    if not needle:
        return None
    with SessionLocal() as db:
        user = db.execute(select(AppUser).where(AppUser.fio == needle)).scalar_one_or_none()
        if user is None:
            matches = db.execute(
                select(AppUser).where(AppUser.fio.ilike(f"%{needle}%")).limit(3)
            ).scalars().all()
            if len(matches) == 1:
                user = matches[0]
            else:
                key = needle.casefold()
                user = next(
                    (item for item in matches if (item.fio or "").casefold().startswith(key)),
                    None,
                )
        if user is None:
            return None
        db.expunge(user)
        return user


_ALLOWED_AVATAR_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def resolve_avatar_file(user_id: str) -> Path | None:
    if not user_id:
        return None
    storage = settings.avatar_storage_dir
    if storage.is_dir():
        for path in storage.glob(f"{user_id}.*"):
            if path.suffix.lower() in _ALLOWED_AVATAR_EXT and path.is_file():
                return path
    user = get_app_user(user_id)
    if user is None or not user.avatar_path:
        return None
    path = Path(user.avatar_path)
    if not path.is_absolute():
        path = storage / path
    return path if path.is_file() else None


class AvatarError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DepartmentError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def save_user_avatar(*, user_id: str, data: bytes, filename: str) -> AppUser:
    if not data:
        raise AvatarError("Пустой файл")
    if len(data) > 5 * 1024 * 1024:
        raise AvatarError("Файл больше 5 МБ")

    ext = Path(filename or "").suffix.lower()
    if ext not in _ALLOWED_AVATAR_EXT:
        raise AvatarError("Допустимы JPG, PNG, WEBP или GIF")

    settings.avatar_storage_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.avatar_storage_dir / f"{user_id}{ext}"
    for old in settings.avatar_storage_dir.glob(f"{user_id}.*"):
        if old.resolve() != dest.resolve():
            old.unlink(missing_ok=True)
    dest.write_bytes(data)

    with SessionLocal() as db:
        user = db.get(AppUser, user_id)
        if user is None:
            raise AvatarError("Пользователь не найден")
        user.avatar_path = str(dest)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        logger.info("Saved avatar for user id=%s path=%s", user_id, dest)
        return user


def update_user_department(*, user_id: str, department: str) -> AppUser:
    dept = department.strip()
    if not dept:
        raise DepartmentError("Укажите отдел")

    with SessionLocal() as db:
        user = db.get(AppUser, user_id)
        if user is None:
            raise DepartmentError("Пользователь не найден", status_code=404)

        can_change, available_at = department_change_state(user)
        if not can_change and available_at is not None:
            local = available_at.astimezone().strftime("%d.%m.%Y")
            raise DepartmentError(
                f"Отдел можно менять раз в 2 недели. Следующая смена с {local}",
                status_code=429,
            )

        if user.department.strip() == dept:
            db.expunge(user)
            return user

        user.department = dept
        user.department_changed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        logger.info("Updated department for user id=%s -> %s", user_id, dept)
        return user
