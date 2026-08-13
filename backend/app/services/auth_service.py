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
    search_user_fios,
)
from app.core.jwt import create_access_token
from app.schemas.auth import LoginResponse, UserOut
from app.services import app_users
from tools.onec.password import verify_password

logger = logging.getLogger(__name__)

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


async def login(fio: str, password: str) -> LoginResponse:
    fio = fio.strip()
    if not fio or not password:
        raise AuthError("Неверный логин или пароль", status_code=401)

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
    try:
        return await asyncio.to_thread(search_user_fios, search)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error listing users")
        raise AuthError("Не удалось загрузить список пользователей", status_code=503) from exc


async def list_department_names() -> list[str]:
    try:
        return await asyncio.to_thread(list_departments)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error listing departments")
        raise AuthError("Не удалось загрузить список отделов", status_code=503) from exc


async def get_current_user_profile(user_id: str, fio_hint: str | None = None) -> UserOut:
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
