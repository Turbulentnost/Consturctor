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
    if not path.is_file():
        return None
    return f"/api/v1/auth/users/{user.id}/avatar"


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
