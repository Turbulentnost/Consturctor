from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.jwt import AuthContext, validate_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    try:
        auth = validate_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Недействительный токен") from exc
    if auth.fio:
        try:
            from app.services import app_users

            app_users.upsert_app_user(
                user_id=auth.user_id,
                fio=auth.fio or "",
                department=auth.department or "",
                position=auth.position or "",
            )
        except Exception:
            pass
    return auth
