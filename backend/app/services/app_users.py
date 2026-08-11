from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.db.session import SessionLocal
from app.models.user import AppUser

logger = logging.getLogger(__name__)


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


def upsert_app_user(*, user_id: str, fio: str, department: str) -> AppUser:
    with SessionLocal() as db:
        user = db.get(AppUser, user_id)
        if user is None:
            user = AppUser(id=user_id, fio=fio, department=department or "")
            db.add(user)
            logger.info("Created app user id=%s", user_id)
        else:
            user.fio = fio
            user.department = department or ""
            logger.info("Updated app user id=%s", user_id)
        db.commit()
        db.refresh(user)
        # Detach fields we need after session closes.
        db.expunge(user)
        return user


def get_app_user(user_id: str) -> AppUser | None:
    with SessionLocal() as db:
        user = db.get(AppUser, user_id)
        if user is None:
            return None
        db.expunge(user)
        return user


def resolve_avatar_file(user_id: str) -> Path | None:
    user = get_app_user(user_id)
    if user is None or not user.avatar_path:
        return None
    path = Path(user.avatar_path)
    if not path.is_absolute():
        path = settings.avatar_storage_dir / path
    return path if path.is_file() else None


_ALLOWED_AVATAR_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class AvatarError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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
