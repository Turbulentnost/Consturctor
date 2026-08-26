from __future__ import annotations

import asyncio
import logging

from app.clients.erp_sql import (
    AmbiguousUserError,
    ErpSqlError,
    UserNotFoundError,
    find_user_by_fio,
    find_user_by_id,
    get_user_profile_by_fio,
    list_departments,
    search_user_directory,
    search_user_fios,
)
from app.config import settings
from app.core.jwt import create_access_token
from app.schemas.auth import LoginResponse, UserDirectoryItem, UserOut
from app.services import app_users
from app.services.sessions import new_session_id, replace_session
from tools.onec.password import verify_password

logger = logging.getLogger(__name__)


def _trace(message: str) -> None:
    print(message, flush=True)
    logger.info(message)

# Локальные оверрайды должности по подстроке ФИО (без учёта ь/ъ).
_POSITION_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("комарков", "менеджер тендерного офиса"),
)


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


def _fio_key(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def _erp_sql_bypass_enabled() -> bool:
    return bool(settings.auth_skip_erp_sql)


def _bypass_credentials_ok(fio: str, password: str) -> bool:
    expected_fio = settings.erp_login.strip()
    expected_password = settings.erp_password
    if not expected_fio or not expected_password:
        return False
    return _fio_key(fio) == _fio_key(expected_fio) and password == expected_password


def _bypass_session_identity(fio: str) -> tuple[str, str, str, str]:
    canon = settings.erp_login.strip() or fio
    existing = app_users.find_app_user_by_fio(canon) or app_users.find_app_user_by_fio(fio)
    if existing is not None:
        return existing.id, existing.fio, existing.department or "", existing.position or ""
    user_id = settings.auth_bypass_user_id.strip()
    if not user_id:
        raise AuthError("Не задан пользователь для временного входа", status_code=503)
    return user_id, canon, "", ""


def _login_via_bypass(fio: str, password: str) -> LoginResponse:
    if not _bypass_credentials_ok(fio, password):
        raise AuthError("Неверный логин или пароль", status_code=401)
    user_id, canon_fio, department, position = _bypass_session_identity(fio)
    position = _apply_position_override(canon_fio, position)
    session_id = new_session_id()
    replace_session(user_id, session_id)
    token = create_access_token(
        user_id=user_id,
        fio=canon_fio,
        department=department,
        position=position,
        session_id=session_id,
    )
    user_out = _to_user_out(
        user_id=user_id,
        fio=canon_fio,
        department=department,
        position=position,
    )
    _trace(
        f"Auth login bypass id={user_id} fio={canon_fio} "
        f"department={department or '-'} position={position or '-'}"
    )
    return LoginResponse(access_token=token, user=user_out)


def _to_user_out(*, user_id: str, fio: str, department: str, position: str = "") -> UserOut:
    try:
        app_user = app_users.upsert_app_user(
            user_id=user_id,
            fio=fio,
            department=department or "",
            position=position or "",
        )
    except Exception as exc:
        logger.exception("Failed to upsert app user id=%s", user_id)
        raise AuthError("Не удалось сохранить пользователя в базе", status_code=503) from exc
    return app_users.to_user_out(app_user)


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


_LOCAL_DESKTOP_USERS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "anna",
        "A11ADEA24A5000000000000000000001",
        "Анна Де Армас",
        "Тест",
        "Тестовый пользователь",
    ),
    (
        "ilchenko",
        "E11C4E11K00000000000000000000001",
        "Ильченко Екатерина Александровна",
        "Корпоративное управление",
        "Корпоративный секретарь",
    ),
    (
        "mdj",
        "M11ZHALYBIN00000000000000000001",
        "Жалыбин Максим Дмитриевич",
        "Сектор по внедрению искусственного интеллекта",
        "Промпт-инженер 2 категории",
    ),
)


def _local_desktop_user(fio: str, password: str) -> tuple[str, str, str, str] | None:
    key = _fio_key(fio)
    entered = key.split()
    for stored_password, user_id, canon_fio, department, position in _LOCAL_DESKTOP_USERS:
        stored_key = _fio_key(canon_fio)
        parts = stored_key.split()
        matched = key == stored_key or (
            len(entered) >= 2 and len(parts) >= 2 and entered[0] == parts[0] and entered[1] == parts[1]
        )
        if not matched:
            continue
        if password != stored_password:
            return None
        return user_id, canon_fio, department, position
    return None


def _login_via_local_desktop(fio: str, password: str) -> LoginResponse | None:
    found = _local_desktop_user(fio, password)
    if found is None:
        return None
    user_id, canon_fio, department, position = found
    session_id = new_session_id()
    replace_session(user_id, session_id)
    token = create_access_token(
        user_id=user_id,
        fio=canon_fio,
        department=department,
        position=position,
        session_id=session_id,
    )
    user_out = _to_user_out(
        user_id=user_id,
        fio=canon_fio,
        department=department,
        position=position,
    )
    _trace(f"Auth login local-desktop id={user_id} fio={canon_fio}")
    return LoginResponse(access_token=token, user=user_out)


async def login(fio: str, password: str) -> LoginResponse:
    fio = fio.strip()
    if not fio or not password:
        raise AuthError("Неверный логин или пароль", status_code=401)

    _trace(f"Auth login start fio={fio}")
    local = await asyncio.to_thread(_login_via_local_desktop, fio, password)
    if local is not None:
        return local
    if _erp_sql_bypass_enabled():
        return await asyncio.to_thread(_login_via_bypass, fio, password)

    try:
        erp_user = await asyncio.to_thread(find_user_by_fio, fio)
    except UserNotFoundError as exc:
        raise AuthError("Неверный логин или пароль", status_code=401) from exc
    except AmbiguousUserError as exc:
        raise AuthError("Найдено несколько пользователей с таким ФИО", status_code=409) from exc
    except ErpSqlError as exc:
        logger.exception("ERP SQL error during login")
        raise AuthError("Сервис аутентификации недоступен", status_code=503) from exc

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

    session_id = new_session_id()
    replace_session(erp_user.id, session_id)
    token = create_access_token(
        user_id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
        position=position or "",
        session_id=session_id,
    )
    user_out = await asyncio.to_thread(
        _to_user_out,
        user_id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
        position=position or "",
    )
    _trace(
        f"Auth login ok id={erp_user.id} fio={erp_user.fio} "
        f"department={department or '-'} position={position or '-'}"
    )
    return LoginResponse(access_token=token, user=user_out)


async def list_user_fios(search: str | None = None) -> list[str]:
    if _erp_sql_bypass_enabled():
        fio = settings.erp_login.strip()
        if not fio:
            return []
        if search and _fio_key(search) not in _fio_key(fio):
            return []
        return [fio]
    try:
        return await asyncio.to_thread(search_user_fios, search)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error listing users")
        raise AuthError("Не удалось загрузить список пользователей", status_code=503) from exc


async def list_user_directory(search: str | None = None) -> list[UserDirectoryItem]:
    if _erp_sql_bypass_enabled():
        fio = settings.erp_login.strip()
        if not fio:
            return []
        if search and _fio_key(search) not in _fio_key(fio):
            return []
        return [UserDirectoryItem(id="local", fio=fio)]
    try:
        rows = await asyncio.to_thread(search_user_directory, search)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error listing user directory")
        raise AuthError("Не удалось загрузить список пользователей", status_code=503) from exc
    return [UserDirectoryItem(id=row.id, fio=row.fio) for row in rows]


async def list_department_names() -> list[str]:
    try:
        return await asyncio.to_thread(list_departments)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error listing departments")
        raise AuthError("Не удалось загрузить список отделов", status_code=503) from exc


async def get_current_user_profile(user_id: str, fio_hint: str | None = None) -> UserOut:
    if _erp_sql_bypass_enabled():
        app_user = app_users.get_app_user(user_id)
        if app_user is None and fio_hint:
            app_user = app_users.find_app_user_by_fio(fio_hint)
        if app_user is not None:
            return app_users.to_user_out(app_user)
        fio = (fio_hint or settings.erp_login).strip()
        return await asyncio.to_thread(
            _to_user_out,
            user_id=user_id,
            fio=fio,
            department="",
            position="",
        )

    try:
        erp_user = await asyncio.to_thread(find_user_by_id, user_id)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error loading profile")
        raise AuthError("Сервис аутентификации недоступен", status_code=503) from exc

    if erp_user is None:
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
