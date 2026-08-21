from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from app.config import settings


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: str
    fio: str | None = None
    department: str | None = None
    position: str | None = None
    session_id: str = ""


def create_access_token(
    *,
    user_id: str,
    fio: str,
    department: str = "",
    position: str = "",
    session_id: str = "",
) -> str:
    now = datetime.now(UTC)
    sid = (session_id or "").strip() or str(uuid4())
    payload = {
        "sub": user_id,
        "fio": fio,
        "department": department,
        "position": position,
        "sid": sid,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def validate_token(token: str) -> AuthContext:
    if not token:
        raise ValueError("Invalid token")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid token") from exc

    user_id = payload.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise ValueError("Invalid token payload")

    fio = payload.get("fio")
    department = payload.get("department")
    position = payload.get("position")
    session_id = payload.get("sid")
    return AuthContext(
        user_id=user_id,
        fio=fio if isinstance(fio, str) else None,
        department=department if isinstance(department, str) else None,
        position=position if isinstance(position, str) else None,
        session_id=session_id if isinstance(session_id, str) else "",
    )
