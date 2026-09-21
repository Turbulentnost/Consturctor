from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.core.jwt import AuthContext, validate_token
from app.services.app_users import is_admin_user
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
    if not settings.auth_skip_session_lock and not is_current_session(
        auth.user_id, auth.session_id, client=auth.client
    ):
        raise HTTPException(status_code=401, detail="Сеанс завершён на другом устройстве")
    if not auth.onec_catalog_ref_key:
        from app.services.app_users import get_app_user

        cached = get_app_user(auth.user_id)
        ref = (cached.onec_catalog_ref_key or "").strip() if cached is not None else ""
        if ref:
            auth = AuthContext(
                user_id=auth.user_id,
                fio=auth.fio,
                department=auth.department,
                position=auth.position,
                session_id=auth.session_id,
                client=auth.client,
                onec_catalog_ref_key=ref,
            )
    return auth


def require_admin_user(auth: AuthContext = Depends(get_current_user)) -> AuthContext:
    if not is_admin_user(auth.fio or ""):
        raise HTTPException(status_code=403, detail="Доступ только для администратора")
    return auth
