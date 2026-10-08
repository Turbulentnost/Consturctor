"""JWT-сессия Constructor для инструментов, которые ходят в его backend."""

from __future__ import annotations

import logging
import threading
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_RETRY_SECONDS = 30.0

_lock = threading.Lock()
_configured = False
_last_error = ""
_last_attempt = 0.0


class ConstructorSessionError(RuntimeError):
    pass


def ensure_session() -> bool:
    """Настроить runtime_api один раз; при неудаче вернуть False и запомнить причину.

    Не бросает: локальные инструменты должны работать и без сервера Constructor,
    а серверные покажут причину через last_error().
    """
    global _configured, _last_error, _last_attempt
    if _configured:
        return True
    with _lock:
        if _configured:
            return True
        token = settings.constructor_api_token.strip()
        if not token:
            if not has_credentials():
                return False
            if _last_error and time.monotonic() - _last_attempt < _RETRY_SECONDS:
                return False
            _last_attempt = time.monotonic()
            try:
                token = access_token()
            except ConstructorSessionError as exc:
                _last_error = str(exc)
                logger.warning("Constructor: %s", exc)
                return False
        from app.vendors.constructor.tools import runtime_api

        runtime_api.configure(token=token, base_url=settings.constructor_api_url)
        _configured = True
        _last_error = ""
        return True


def last_error() -> str:
    return _last_error


def _pairs() -> list[tuple[str, str]]:
    """Пользователь агентов (вкладка «Настройки»), затем старая пара CONSTRUCTOR_LOGIN_*."""
    pairs: list[tuple[str, str]] = []
    for fio, password in (
        (settings.constructor_user_fio, settings.constructor_user_password),
        (settings.constructor_login_fio, settings.constructor_login_password),
    ):
        pair = (fio.strip(), password)
        if pair[0] and pair[1] and pair not in pairs:
            pairs.append(pair)
    return pairs


def has_credentials() -> bool:
    return bool(_pairs())


def access_token() -> str:
    """JWT Constructor: готовый токен, затем вход под пользователем агентов."""
    token = settings.constructor_api_token.strip()
    if token:
        return token
    pairs = _pairs()
    if not pairs:
        raise ConstructorSessionError(
            "Не задан пользователь агентов: Настройки → Инструменты → «Пользователь агентов»."
        )
    last_error: ConstructorSessionError | None = None
    for fio, password in pairs:
        try:
            return _login(fio, password)
        except ConstructorSessionError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def reset_session() -> None:
    global _configured, _last_error
    with _lock:
        _configured = False
        _last_error = ""


def _login(fio: str, password: str) -> str:
    return str(login(fio, password)["access_token"])


def login(fio: str, password: str) -> dict:
    """POST /api/v1/auth/login: ответ Constructor с access_token и user (fio, position, department)."""
    login_fio = fio.strip()
    login_password = password
    base = settings.constructor_api_url.rstrip("/")
    try:
        response = httpx.post(
            f"{base}/api/v1/auth/login",
            json={
                "fio": login_fio,
                "password": login_password,
                "client": "constructor",
            },
            timeout=settings.constructor_connect_timeout,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise ConstructorSessionError(
            f"Сервер Constructor {base} недоступен ({type(exc).__name__}). "
            "Проверьте CONSTRUCTOR_API_URL и что backend Constructor запущен."
        ) from exc
    if response.status_code in (400, 401, 403):
        raise ConstructorSessionError(
            f"Constructor отклонил вход как «{login_fio}»: {_detail(response) or 'неверное ФИО или пароль'}."
        )
    if response.status_code >= 400:
        raise ConstructorSessionError(f"Вход в Constructor: HTTP {response.status_code}")
    data = response.json()
    if not isinstance(data, dict) or not str(data.get("access_token") or ""):
        raise ConstructorSessionError("Constructor не вернул access_token при входе.")
    return data


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return ""
    return detail.strip() if isinstance(detail, str) else ""
