from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import jwt

from app.config import settings


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: str
    fio: str | None = None
    department: str | None = None
    position: str | None = None


def create_access_token(
    *,
    user_id: str,
    fio: str,
    department: str = "",
    position: str = "",
) -> str:
    now = datetime.now(UTC)
    issued_at = int(now.timestamp())
    payload = {
        "sub": user_id,
        "fio": fio,
        "department": department,
        "position": position,
        "iat": issued_at,
        "exp": issued_at + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def validate_token(token: str) -> AuthContext:
    if not token:
        raise ValueError("Invalid token")

    auth_base = (settings.auth_server_url or "").strip().rstrip("/")
    if auth_base:
        try:
            return _validate_via_auth_server(token, auth_base)
        except ValueError:
            pass

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid token") from exc

    return _auth_from_payload(payload)


def _validate_via_auth_server(token: str, auth_base: str) -> AuthContext:
    import httpx

    url = f"{auth_base}/api/v1/auth/me"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise ValueError("Invalid token") from exc
    if response.status_code >= 400:
        raise ValueError("Invalid token")
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Invalid token")
    user_id = str(data.get("id") or "").strip()
    if not user_id:
        raise ValueError("Invalid token payload")
    return AuthContext(
        user_id=user_id,
        fio=str(data.get("fio") or "") or None,
        department=str(data.get("department") or "") or None,
        position=str(data.get("position") or "") or None,
    )


def _auth_from_payload(payload: dict) -> AuthContext:
    user_id = payload.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise ValueError("Invalid token payload")

    fio = payload.get("fio")
    department = payload.get("department")
    position = payload.get("position")
    return AuthContext(
        user_id=user_id,
        fio=fio if isinstance(fio, str) else None,
        department=department if isinstance(department, str) else None,
        position=position if isinstance(position, str) else None,
    )
