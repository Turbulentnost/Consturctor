from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.clients.erp_sql import (
    AmbiguousUserError,
    ErpSqlError,
    UserNotFoundError,
    find_user_by_fio,
    find_user_by_id,
    get_user_profile_by_fio,
    list_departments,
    ping,
    search_user_directory,
    search_user_fios,
)
from app.config import settings
from app.core.jwt import create_access_token
from app.schemas.auth import LoginResponse, UserDirectoryItem, UserOut
from app.services import app_users
from app.services.sessions import DEFAULT_CLIENT, new_session_id, normalize_client, replace_session
from tools.onec.password import verify_password

logger = logging.getLogger(__name__)


def _trace(message: str) -> None:
    print(message, flush=True)
    logger.info(message)

# Локальные оверрайды должности и отдела по подстроке ФИО (без учёта ь/ъ).
_POSITION_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("комарков", "менеджер тендерного офиса"),
    ("мангасарян", "Помощник Председателя совета директоров"),
)
_DEPARTMENT_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("мангасарян", "Управление делами"),
)


def _normalize_fio_key(value: str) -> str:
    text = (value or "").casefold()
    for ch in ("ь", "ъ", "\u0301"):
        text = text.replace(ch, "")
    return text


def _apply_overrides(fio: str, department: str, position: str) -> tuple[str, str]:
    key = _normalize_fio_key(fio)
    for needle, override in _DEPARTMENT_OVERRIDES:
        if _normalize_fio_key(needle) in key:
            department = override
            break
    for needle, override in _POSITION_OVERRIDES:
        if _normalize_fio_key(needle) in key:
            position = override
            break
    return department or "", position or ""


def _apply_position_override(fio: str, position: str) -> str:
    _, next_position = _apply_overrides(fio, "", position)
    return next_position


def _fio_key(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def _erp_sql_bypass_enabled() -> bool:
    return bool(settings.auth_skip_erp_sql)


def _auth_gateway_base() -> str:
    return (settings.auth_erp_gateway_url or "").strip().rstrip("/")


def _erp_auth_unavailable_message(*, gateway_failed: bool = False) -> str:
    gw = _auth_gateway_base()
    local = (
        f"На этом backend нет доступа к erp_pm (ERP_SQL_SERVER={settings.erp_sql_server!r}). "
    )
    if gw and gateway_failed:
        return (
            f"{local}Прокси AUTH_ERP_GATEWAY_URL={gw} не принял вход — проверьте LAN до "
            "сервера gateway (192.168.1.157:7812) или укажите в desktop "
            "BACKEND_URL=http://192.168.1.157:7812."
        )
    if gw:
        return (
            f"{local}VPN на ПК не нужен, если gateway доступен ({gw}). "
            "Проверьте сеть или BACKEND_URL=http://192.168.1.157:7812."
        )
    return (
        f"{local}Без VPN: BACKEND_URL=http://192.168.1.157:7812 (аутентификация на gateway) "
        "или в backend/.env AUTH_ERP_GATEWAY_URL=http://192.168.1.157:7812 при локальном "
        "127.0.0.1:7812. Либо ERP_LOGIN/ERP_PASSWORD и AUTH_SKIP_ERP_SQL=1."
    )


async def _local_erp_reachable() -> bool:
    try:
        return await asyncio.wait_for(asyncio.to_thread(ping), timeout=3.0)
    except (TimeoutError, ErpSqlError):
        return False
    except Exception:
        logger.warning("Unexpected ERP ping error", exc_info=True)
        return False


def _user_out_from_gateway_payload(raw: dict[str, Any]) -> UserOut:
    user_id = str(raw.get("id") or raw.get("user_id") or "").strip()
    fio = str(raw.get("fio") or "").strip()
    if not user_id or not fio:
        raise AuthError("Некорректный ответ gateway при входе", status_code=503)
    department = str(raw.get("department") or "")
    position = str(raw.get("position") or "")
    name_mail = str(raw.get("name_mail") or raw.get("nameMail") or "")
    return _to_user_out(
        user_id=user_id,
        fio=fio,
        department=department,
        position=position,
        name_mail=name_mail,
    )


def _login_via_erp_gateway(fio: str, password: str, client: str = DEFAULT_CLIENT) -> LoginResponse:
    base = _auth_gateway_base()
    if not base:
        raise AuthError(_erp_auth_unavailable_message(), status_code=503)
    client = normalize_client(client)
    url = f"{base}/api/v1/auth/login"
    try:
        with httpx.Client(timeout=60.0) as http:
            response = http.post(
                url,
                json={"fio": fio, "password": password, "client": client},
            )
    except httpx.HTTPError as exc:
        logger.warning("ERP auth gateway unreachable at %s: %s", url, exc)
        raise AuthError(
            _erp_auth_unavailable_message(gateway_failed=True),
            status_code=503,
        ) from exc

    if response.status_code == 401:
        raise AuthError("Неверный логин или пароль", status_code=401)
    if response.status_code >= 400:
        logger.warning(
            "ERP auth gateway login HTTP %s: %s",
            response.status_code,
            response.text[:300],
        )
        raise AuthError(
            _erp_auth_unavailable_message(gateway_failed=True),
            status_code=503,
        )

    payload = response.json()
    user_raw = payload.get("user")
    if not isinstance(user_raw, dict):
        raise AuthError(
            _erp_auth_unavailable_message(gateway_failed=True),
            status_code=503,
        )

    user_out = _user_out_from_gateway_payload(user_raw)
    session_id = new_session_id()
    replace_session(user_out.id, session_id, client)
    token = create_access_token(
        user_id=user_out.id,
        fio=user_out.fio,
        department=user_out.department or "",
        position=user_out.position or "",
        session_id=session_id,
        client=client,
    )
    _trace(
        f"Auth login via gateway id={user_out.id} fio={user_out.fio} "
        f"gateway={base} client={client}"
    )
    return LoginResponse(access_token=token, user=user_out)


def _list_fios_via_erp_gateway(search: str | None) -> list[str]:
    base = _auth_gateway_base()
    if not base:
        return []
    url = f"{base}/api/v1/auth/users"
    params = {"search": search} if search else None
    try:
        with httpx.Client(timeout=30.0) as http:
            response = http.get(url, params=params)
    except httpx.HTTPError as exc:
        logger.warning("ERP auth gateway user list failed: %s", exc)
        return []
    if response.status_code >= 400:
        return []
    data = response.json()
    items = data.get("items")
    if not isinstance(items, list):
        return []
    return [str(x) for x in items if str(x).strip()]


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


def _login_via_bypass(fio: str, password: str, client: str = DEFAULT_CLIENT) -> LoginResponse:
    if not _bypass_credentials_ok(fio, password):
        raise AuthError("Неверный логин или пароль", status_code=401)
    user_id, canon_fio, department, position = _bypass_session_identity(fio)
    department, position = _apply_overrides(canon_fio, department, position)
    session_id = new_session_id()
    client = normalize_client(client)
    replace_session(user_id, session_id, client)
    token = create_access_token(
        user_id=user_id,
        fio=canon_fio,
        department=department,
        position=position,
        session_id=session_id,
        client=client,
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


def _name_mail_from_erp_login(raw: str) -> str:
    """v8users.Name — латинский логин для корпоративной почты."""
    text = (raw or "").strip().lower()
    if not text:
        return ""
    if "@" in text:
        text = text.split("@", 1)[0].strip()
    if any("\u0400" <= ch <= "\u04ff" for ch in text):
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    if not text or any(ch not in allowed for ch in text):
        return ""
    return text


def _to_user_out(
    *,
    user_id: str,
    fio: str,
    department: str,
    position: str = "",
    name_mail: str = "",
) -> UserOut:
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
    out = app_users.to_user_out(app_user)
    if name_mail:
        return out.model_copy(update={"name_mail": name_mail})
    return out


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def login(fio: str, password: str, client: str = DEFAULT_CLIENT) -> LoginResponse:
    fio = fio.strip()
    if not fio or not password:
        raise AuthError("Неверный логин или пароль", status_code=401)
    client = normalize_client(client)

    _trace(f"Auth login start fio={fio} client={client}")
    if _erp_sql_bypass_enabled():
        return await asyncio.to_thread(_login_via_bypass, fio, password, client)

    gateway = _auth_gateway_base()
    if gateway and not await _local_erp_reachable():
        _trace(f"Auth login local ERP down, using gateway {gateway}")
        return await asyncio.to_thread(_login_via_erp_gateway, fio, password, client)

    try:
        erp_user = await asyncio.to_thread(find_user_by_fio, fio)
    except UserNotFoundError as exc:
        raise AuthError("Неверный логин или пароль", status_code=401) from exc
    except AmbiguousUserError as exc:
        raise AuthError("Найдено несколько пользователей с таким ФИО", status_code=409) from exc
    except ErpSqlError as exc:
        logger.exception("ERP SQL error during login")
        if gateway:
            try:
                return await asyncio.to_thread(_login_via_erp_gateway, fio, password, client)
            except AuthError as proxy_exc:
                if proxy_exc.status_code == 401:
                    raise
                logger.warning("Gateway auth fallback failed: %s", proxy_exc.message)
        if settings.erp_login.strip() and settings.erp_password:
            try:
                return await asyncio.to_thread(_login_via_bypass, fio, password, client)
            except AuthError:
                pass
        raise AuthError(
            _erp_auth_unavailable_message(gateway_failed=bool(gateway)),
            status_code=503,
        ) from exc

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
    department, position = _apply_overrides(erp_user.fio, department or "", position or "")

    session_id = new_session_id()
    replace_session(erp_user.id, session_id, client)
    token = create_access_token(
        user_id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
        position=position or "",
        session_id=session_id,
        client=client,
    )
    user_out = await asyncio.to_thread(
        _to_user_out,
        user_id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
        position=position or "",
        name_mail=_name_mail_from_erp_login(erp_user.name),
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
    gateway = _auth_gateway_base()
    if gateway and not await _local_erp_reachable():
        items = await asyncio.to_thread(_list_fios_via_erp_gateway, search)
        if items or search:
            return items
    try:
        return await asyncio.to_thread(search_user_fios, search)
    except ErpSqlError as exc:
        logger.exception("ERP SQL error listing users")
        if gateway:
            items = await asyncio.to_thread(_list_fios_via_erp_gateway, search)
            if items:
                return items
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
        app_user = app_users.get_app_user(user_id)
        if app_user is None and fio_hint:
            app_user = app_users.find_app_user_by_fio(fio_hint)
        if app_user is not None:
            return app_users.to_user_out(app_user)
        raise AuthError(_erp_auth_unavailable_message(), status_code=503) from exc

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
    department, position = _apply_overrides(
        erp_user.fio or (fio_hint or ""),
        department or "",
        position or "",
    )

    return await asyncio.to_thread(
        _to_user_out,
        user_id=erp_user.id,
        fio=erp_user.fio,
        department=department or "",
        position=position or "",
        name_mail=_name_mail_from_erp_login(erp_user.name),
    )
