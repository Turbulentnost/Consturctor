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
    search_user_fios,
)
from app.core.jwt import create_access_token
from app.schemas.auth import LoginResponse, UserOut
from tools.onec.password import verify_password

logger = logging.getLogger(__name__)


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
    if not department:
        try:
            profile = await asyncio.to_thread(get_user_profile_by_fio, erp_user.fio)
            department = profile.department
        except ErpSqlError:
            logger.warning("Could not load department for user id=%s", erp_user.id)

    token = create_access_token(
        user_id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
    )
    logger.info("User logged in: id=%s", erp_user.id)
    return LoginResponse(
        access_token=token,
        user=UserOut(
            id=erp_user.id,
            fio=erp_user.fio,
            department=department or "",
        ),
    )


async def list_user_fios(search: str | None = None) -> list[str]:
    try:
        return await asyncio.to_thread(search_user_fios, search)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error listing users")
        raise AuthError("Не удалось загрузить список пользователей", status_code=503) from exc


async def get_current_user_profile(user_id: str, fio_hint: str | None = None) -> UserOut:
    try:
        erp_user = await asyncio.to_thread(find_user_by_id, user_id)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error loading profile")
        raise AuthError("Сервис аутентификации недоступен", status_code=503) from exc

    if erp_user is None:
        raise AuthError("Пользователь не найден", status_code=404)

    department = erp_user.department
    if not department:
        try:
            profile = await asyncio.to_thread(get_user_profile_by_fio, erp_user.fio or (fio_hint or ""))
            department = profile.department
        except ErpSqlError:
            logger.warning("Could not refresh department for user id=%s", user_id)

    return UserOut(
        id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
    )
