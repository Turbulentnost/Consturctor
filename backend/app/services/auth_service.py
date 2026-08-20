from __future__ import annotations

import asyncio
import logging

import httpx

from app.clients.erp_sql import (
    AmbiguousUserError,
    ErpSqlError,
    UserNotFoundError,
    find_user_by_fio,
    find_user_by_id,
    get_user_profile_by_fio,
    list_departments,
    search_user_fios,
)
from app.config import settings
from app.core.jwt import create_access_token
from app.schemas.auth import LoginResponse, UserOut
from app.services import app_users
from app.services.local_auth import (
    LocalAuthError,
    find_local_user_by_fio,
    is_local_user_id,
    list_local_user_fios,
    register_local_user,
    verify_password_hash,
)
from tools.onec.password import verify_password

logger = logging.getLogger(__name__)

# Локальные оверрайды должности по подстроке ФИО (без учёта ь/ъ).
_POSITION_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("комарков", "менеджер тендерного офиса"),
    ("жалыбин", "Промпт-инженер 2 категории"),
)


def registration_enabled() -> bool:
    return settings.auth_stub or settings.allow_local_registration


def _normalize_fio_key(value: str) -> str:
    text = (value or "").casefold()
    for ch in ("ь", "ъ", "\u0301"):
        text = text.replace(ch, "")
    return text


def _apply_position_override(fio: str, position: str) -> str:
    key = _normalize_fio_key(fio)
    for needle, override in _POSITION_OVERRIDES:
        if _normalize_fio_key(needle) in key:
            return override
    return position or ""


def _erp_login_error_message(exc: ErpSqlError) -> str:
    text = str(exc)
    if "IM002" in text or "driver not found" in text.lower():
        return (
            "ODBC к базе 1С не настроен. Установите «ODBC Driver 18 for SQL Server» "
            "или укажите ERP_SQL_DRIVER=SQL Server в backend\\.env и перезапустите gateway."
        )
    if "18456" in text:
        return (
            "Нет доступа к SQL Server erp_pm под вашей учётной записью Windows. "
            "Откройте SSMS с тем же логином или задайте ERP_SQL_USER/ERP_SQL_PASSWORD "
            "и ERP_SQL_TRUSTED_CONNECTION=no в backend\\.env."
        )
    return f"Сервис аутентификации 1С недоступен: {text}"


def _stub_login(fio: str) -> LoginResponse:
    if settings.dev_mode:
        department = "Разработка платформы"
        position = "Разработчик"
    else:
        department = "Demo (AUTH_STUB)"
        position = ""
    position = _apply_position_override(fio, position)
    token = create_access_token(
        user_id="auth-stub",
        fio=fio,
        department=department,
        position=position,
    )
    logger.info("AUTH_STUB login: fio=%s dev_mode=%s", fio, settings.dev_mode)
    user = _to_user_out(
        user_id="auth-stub",
        fio=fio,
        department=department,
        position=position,
    )
    return LoginResponse(access_token=token, user=user)


def _to_user_out(*, user_id: str, fio: str, department: str, position: str = "") -> UserOut:
    try:
        app_user = app_users.upsert_app_user(
            user_id=user_id,
            fio=fio,
            department=department or "",
            position=position or "",
        )
        return app_users.to_user_out(app_user)
    except Exception:
        logger.exception("Failed to upsert app user id=%s, using JWT profile", user_id)
        return UserOut(
            id=user_id,
            fio=fio,
            department=department or "",
            position=position or "",
        )


def _skip_login_fio() -> str:
    if not settings.skip_login and not settings.skip_login_fio.strip():
        return ""
    return (settings.skip_login_fio or settings.erp_login or "").strip()


def _issue_login(*, user_id: str, fio: str, department: str = "", position: str = "") -> LoginResponse:
    position = _apply_position_override(fio, position)
    token = create_access_token(
        user_id=user_id,
        fio=fio,
        department=department or "",
        position=position or "",
    )
    user_out = _to_user_out(
        user_id=user_id,
        fio=fio,
        department=department or "",
        position=position or "",
    )
    return LoginResponse(access_token=token, user=user_out)


def _login_skip(fio: str) -> LoginResponse:
    target = fio.strip() or _skip_login_fio()
    if settings.erp_password and _auth_server_base():
        try:
            return _login_via_auth_server(target, settings.erp_password)
        except AuthError:
            logger.warning("Skip-login via AUTH_SERVER failed, using local profile")

    try:
        erp_user = find_user_by_fio(target)
    except (UserNotFoundError, AmbiguousUserError, ErpSqlError):
        erp_user = None
    if erp_user is not None:
        department = erp_user.department
        position = erp_user.position
        if not department or not position:
            try:
                profile = get_user_profile_by_fio(erp_user.fio)
                department = department or profile.department
                position = position or profile.position
            except ErpSqlError:
                pass
        return _issue_login(
            user_id=erp_user.id,
            fio=erp_user.fio,
            department=department or "",
            position=position or "",
        )

    try:
        app_user = app_users.get_app_user_by_fio(target)
    except Exception:
        app_user = None
    if app_user is not None:
        return _issue_login(
            user_id=app_user.id,
            fio=app_user.fio,
            department=app_user.department or "",
            position=app_user.position or "",
        )

    return _issue_login(
        user_id="dev-skip-zhalybin",
        fio=target,
        department="Сектор по внедрению искусственного интеллекта",
        position="Промпт-инженер 2 категории",
    )


def _login_local_user(fio: str, password: str) -> LoginResponse:
    user = find_local_user_by_fio(fio)
    if user is None or not user.password_hash:
        raise AuthError("Неверный логин или пароль", status_code=401)
    if not verify_password_hash(user.password_hash, password):
        raise AuthError("Неверный логин или пароль", status_code=401)
    token = create_access_token(
        user_id=user.id,
        fio=user.fio,
        department=user.department or "",
        position=user.position or "",
    )
    logger.info("Local user logged in: id=%s", user.id)
    return LoginResponse(access_token=token, user=app_users.to_user_out(user))


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def register(fio: str, password: str, department: str = "") -> LoginResponse:
    if not registration_enabled():
        raise AuthError("Регистрация отключена на этом сервере", status_code=403)
    try:
        user = await asyncio.to_thread(
            register_local_user,
            fio=fio,
            password=password,
            department=department,
        )
    except LocalAuthError as exc:
        raise AuthError(exc.message, status_code=exc.status_code) from exc
    token = create_access_token(
        user_id=user.id,
        fio=user.fio,
        department=user.department or "",
        position=user.position or "",
    )
    logger.info("Local user registered: id=%s", user.id)
    return LoginResponse(access_token=token, user=app_users.to_user_out(user))


def _auth_server_base() -> str:
    return settings.auth_server_url.strip().rstrip("/")


def _login_via_auth_server(fio: str, password: str) -> LoginResponse:
    base = _auth_server_base()
    if not base:
        raise AuthError("Сервис аутентификации недоступен", status_code=503)

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                f"{base}/api/v1/auth/login",
                json={"fio": fio, "password": password},
            )
    except httpx.HTTPError as exc:
        logger.warning("Auth server login failed: %s", exc)
        raise AuthError("Сервис аутентификации недоступен", status_code=503) from exc

    if response.status_code == 401:
        raise AuthError("Неверный логин или пароль", status_code=401)
    if response.status_code >= 400:
        detail = ""
        try:
            payload = response.json()
            detail = str(payload.get("detail") or "")
        except Exception:
            detail = response.text[:200]
        logger.warning("Auth server login HTTP %s: %s", response.status_code, detail)
        raise AuthError(detail or "Сервис аутентификации недоступен", status_code=503)

    payload = response.json()
    user = payload.get("user") or {}
    user_id = str(user.get("id") or "").strip()
    user_fio = str(user.get("fio") or fio).strip()
    department = str(user.get("department") or "")
    position = _apply_position_override(user_fio, str(user.get("position") or ""))
    if not user_id:
        raise AuthError("Сервис аутентификации недоступен", status_code=503)

    token = create_access_token(
        user_id=user_id,
        fio=user_fio,
        department=department,
        position=position,
    )
    user_out = _to_user_out(
        user_id=user_id,
        fio=user_fio,
        department=department,
        position=position,
    )
    logger.info("User logged in via AUTH_SERVER: id=%s", user_id)
    return LoginResponse(access_token=token, user=user_out)


def _list_user_fios_via_auth_server(search: str | None) -> list[str]:
    base = _auth_server_base()
    if not base:
        raise AuthError("Не удалось загрузить список пользователей", status_code=503)
    params = {"search": search} if search else None
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{base}/api/v1/auth/users", params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Auth server user list failed: %s", exc)
        raise AuthError("Не удалось загрузить список пользователей", status_code=503) from exc
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    return [str(item) for item in items if str(item).strip()]


async def login(fio: str, password: str) -> LoginResponse:
    fio = fio.strip()
    skip_fio = _skip_login_fio()
    if skip_fio and (not fio or _normalize_fio_key(fio) == _normalize_fio_key(skip_fio)):
        logger.warning("Skip-login enabled, issuing session for %s", skip_fio)
        return await asyncio.to_thread(_login_skip, skip_fio)
    if not fio or not password:
        raise AuthError("Неверный логин или пароль", status_code=401)

    local_user = await asyncio.to_thread(find_local_user_by_fio, fio)
    if local_user is not None and local_user.password_hash:
        return await asyncio.to_thread(_login_local_user, fio, password)

    try:
        erp_user = await asyncio.to_thread(find_user_by_fio, fio)
    except UserNotFoundError as exc:
        raise AuthError("Неверный логин или пароль", status_code=401) from exc
    except AmbiguousUserError as exc:
        raise AuthError("Найдено несколько пользователей с таким ФИО", status_code=409) from exc
    except ErpSqlError as exc:
        if _auth_server_base():
            logger.warning("ERP SQL unavailable, login via AUTH_SERVER")
            return await asyncio.to_thread(_login_via_auth_server, fio, password)
        if settings.auth_stub:
            logger.warning("ERP SQL unavailable, using AUTH_STUB login for %s", fio)
            return _stub_login(fio)
        logger.exception("ERP SQL error during login")
        raise AuthError(_erp_login_error_message(exc), status_code=503) from exc
    except Exception as exc:
        if settings.auth_stub:
            logger.warning(
                "ERP SQL unavailable (%s), using AUTH_STUB login for %s",
                exc,
                fio,
            )
            return _stub_login(fio)
        logger.exception("Unexpected ERP SQL error during login")
        raise AuthError("Сервис авторизации временно недоступен", status_code=503) from exc

    data = erp_user.data or b""
    if not data or not verify_password(data, password):
        raise AuthError("Неверный логин или пароль", status_code=401)

    department = erp_user.department
    position = erp_user.position
    if not department or not position:
        try:
            profile = await asyncio.to_thread(get_user_profile_by_fio, erp_user.fio)
            department = department or profile.department
            position = position or profile.position
        except ErpSqlError:
            logger.warning("Could not load department/position for user id=%s", erp_user.id)
    position = _apply_position_override(erp_user.fio, position)

    token = create_access_token(
        user_id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
        position=position or "",
    )
    user_out = await asyncio.to_thread(
        _to_user_out,
        user_id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
        position=position or "",
    )
    logger.info("User logged in: id=%s", erp_user.id)
    return LoginResponse(access_token=token, user=user_out)


async def list_user_fios(search: str | None = None) -> list[str]:
    local_items = await asyncio.to_thread(list_local_user_fios, search)
    try:
        erp_items = await asyncio.to_thread(search_user_fios, search)
    except ErpSqlError:
        if _auth_server_base():
            logger.warning("ERP SQL unavailable, listing users via AUTH_SERVER")
            try:
                return await asyncio.to_thread(_list_user_fios_via_auth_server, search)
            except AuthError:
                return local_items
        return local_items
    merged: list[str] = []
    seen: set[str] = set()
    for item in erp_items + local_items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


async def list_department_names() -> list[str]:
    try:
        return await asyncio.to_thread(list_departments)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error listing departments")
        raise AuthError("Не удалось загрузить список отделов", status_code=503) from exc


async def get_current_user_profile(user_id: str, fio_hint: str | None = None) -> UserOut:
    if user_id == "auth-stub":
        app_user = app_users.get_app_user(user_id)
        if app_user is not None:
            return app_users.to_user_out(app_user)
        return UserOut(
            id=user_id,
            fio=fio_hint or "Demo",
            department="Demo (AUTH_STUB)",
            position="",
        )

    if is_local_user_id(user_id):
        app_user = app_users.get_app_user(user_id)
        if app_user is None:
            raise AuthError("Пользователь не найден", status_code=404)
        return app_users.to_user_out(app_user)

    try:
        erp_user = await asyncio.to_thread(find_user_by_id, user_id)
    except ErpSqlError as exc:
        app_user = app_users.get_app_user(user_id)
        if app_user is not None:
            logger.warning("ERP SQL unavailable, using local profile for id=%s", user_id)
            return app_users.to_user_out(app_user)
        if fio_hint:
            logger.warning("ERP SQL unavailable, using JWT profile for id=%s", user_id)
            return _to_user_out(user_id=user_id, fio=fio_hint, department="", position="")
        logger.exception("ERP SQL error loading profile")
        raise AuthError("Сервис аутентификации недоступен", status_code=503) from exc

    if erp_user is None:
        app_user = app_users.get_app_user(user_id)
        if app_user is not None:
            return app_users.to_user_out(app_user)
        if fio_hint:
            return _to_user_out(user_id=user_id, fio=fio_hint, department="", position="")
        raise AuthError("Пользователь не найден", status_code=404)

    department = erp_user.department
    position = erp_user.position
    if not department or not position:
        try:
            profile = await asyncio.to_thread(
                get_user_profile_by_fio,
                erp_user.fio or (fio_hint or ""),
            )
            department = department or profile.department
            position = position or profile.position
        except ErpSqlError:
            logger.warning("Could not refresh department/position for user id=%s", user_id)
    position = _apply_position_override(erp_user.fio or (fio_hint or ""), position)

    return await asyncio.to_thread(
        _to_user_out,
        user_id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
        position=position or "",
    )
