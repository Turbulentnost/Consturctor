from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import AppUser

ALLOWED = {"online", "busy", "away"}


def set_activity(db: Session, user_id: str, status: str) -> AppUser:
    value = (status or "").strip()
    if value not in ALLOWED:
        raise ValueError("Недопустимый статус")
    user = db.get(AppUser, user_id)
    if user is None:
        raise ValueError("Пользователь не найден")
    user.activity_status = value
    return user
