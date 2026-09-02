from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.jwt import AuthContext, validate_token
from app.services.sessions import is_current_session

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
    if not is_current_session(auth.user_id, auth.session_id, client=auth.client):
        raise HTTPException(status_code=401, detail="Сеанс завершён на другом устройстве")
    return auth
