from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.user import AppUser
from app.modules.chat.config import RR_KEY, support_user_ids
from app.services.sessions import _redis, is_user_online


def is_support_user(user: AppUser | None, user_id: str = "") -> bool:
    if user is not None and bool(getattr(user, "is_support", False)):
        return True
    return (user_id or (user.id if user else "")) in set(support_user_ids())


def eligible_support_ids(db: Session) -> list[str]:
    configured = support_user_ids()
    stmt = select(AppUser)
    if configured:
        stmt = stmt.where(or_(AppUser.id.in_(configured), AppUser.is_support.is_(True)))
    else:
        stmt = stmt.where(AppUser.is_support.is_(True))
    rows = db.execute(stmt.order_by(AppUser.id)).scalars().all()
    result: list[str] = []
    for row in rows:
        status = (getattr(row, "activity_status", None) or "online").strip()
        if status == "away":
            continue
        if not is_user_online(row.id):
            continue
        result.append(row.id)
    return result


def pick_round_robin(db: Session) -> str | None:
    candidates = eligible_support_ids(db)
    if not candidates:
        return None
    client = _redis()
    index = 0
    if client is not None:
        try:
            index = int(client.incr(RR_KEY))
        except Exception:  # noqa: BLE001
            index = 1
    else:
        index = 1
    return candidates[(index - 1) % len(candidates)]
