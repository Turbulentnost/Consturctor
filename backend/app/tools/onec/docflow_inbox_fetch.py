"""Fetch docflow inbox via HTTP SOAP (dm.1cws), not OData."""

from __future__ import annotations

import re
from typing import Any

from app.tools.onec.docflow_inbox_map import map_inbox_payload
from app.tools.onec.dok_soap import fetch_user_inbox_tasks

_HTTP_AUTH = re.compile(r"\bHTTP\s*40[123]\b", re.I)

_SOAP_AUTH_REJECTED = (
    "Документооборот не принял логин/пароль с экрана входа. "
    "Проверьте ФИО и пароль 1С, которые вы вводили при входе."
)


def soap_modules_available() -> bool:
    return True


def _session_auth(auth_args: dict[str, Any] | None) -> tuple[str, str, str, str]:
    payload = auth_args if isinstance(auth_args, dict) else {}
    fio = str(payload.get("fio") or "").strip()
    typed = str(
        payload.get("session_login") or payload.get("erp_login") or fio
    ).strip()
    latin = str(
        payload.get("username")
        or payload.get("name_mail")
        or payload.get("nameMail")
        or ""
    ).strip()
    password = str(payload.get("password") or payload.get("erp_password") or "").strip()
    return typed, fio, latin, password


def _soap_login_attempts(auth_args: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Only credentials from the desktop session. Never OData / .env service accounts."""
    typed, fio, latin, password = _session_auth(auth_args)
    if not password:
        return []
    attempts: list[tuple[str, str]] = []
    seen: set[str] = set()
    for user in (typed, fio, latin):
        key = user.casefold()
        if not user or key in seen:
            continue
        seen.add(key)
        attempts.append((user, password))
    return attempts


def _is_soap_http_auth_error(text: str) -> bool:
    return bool(_HTTP_AUTH.search(text or ""))


def fetch_inbox_tasks_soap(
    fio: str,
    *,
    since_days: int = 90,
    only_open: bool = True,
    today_and_overdue: bool = False,
    force_refresh: bool = False,
    auth_args: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    attempts = _soap_login_attempts(auth_args)
    if not attempts:
        return [], "Нет пароля с экрана входа. Войдите с паролем 1С."
    last_warning = ""
    tried_users: list[str] = []
    for username, password in attempts:
        tried_users.append(username)
        try:
            payload = fetch_user_inbox_tasks(
                fio.strip(),
                since_days=since_days,
                only_open=only_open,
                retrieve=False,
                today_and_overdue=today_and_overdue,
                force_refresh=force_refresh,
                username=username,
                password=password,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            last_warning = str(exc)
            if _is_soap_http_auth_error(last_warning):
                continue
            return [], last_warning
        if not isinstance(payload, dict):
            last_warning = "Документооборот HTTP: неожиданный ответ"
            continue
        user_fio = str(payload.get("user_fio") or fio).strip() or fio
        return map_inbox_payload(payload, fio=user_fio), ""
    if _is_soap_http_auth_error(last_warning):
        names = ", ".join(tried_users)
        return [], f"{_SOAP_AUTH_REJECTED} Пробовали логин: {names}."
    return [], last_warning or _SOAP_AUTH_REJECTED
