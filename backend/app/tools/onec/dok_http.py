"""HTTP API 1С:Документооборот (hs/dterp, TasksII) — публикация коллеги.

Используется ``docflow_http_tasks`` и ``scripts/dump_user_docflow_tasks.py --executions``.
Учётные данные: ``set_request_auth`` (сеанс desktop) или DOK_HTTP_* / DOCFLOW_* / ODATA_* из settings.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextvars import ContextVar
from datetime import datetime
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_request_auth: ContextVar[tuple[str, str] | None] = ContextVar("_dok_http_request_auth", default=None)


def set_request_auth(user: str, password: str) -> None:
    u = (user or "").strip()
    p = password or ""
    if u and p:
        _request_auth.set((u, p))
    else:
        _request_auth.set(None)


def clear_request_auth() -> None:
    _request_auth.set(None)


def dok_http_base_url() -> str:
    explicit = (os.environ.get("DOK_HTTP_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    server = (settings.dok_http_server or "").strip()
    port = int(settings.dok_http_port or 81)
    base_path = (settings.dok_http_base_path or "/doc").strip().rstrip("/") or "/doc"
    if server:
        return f"http://{server}:{port}{base_path}/hs/dterp"
    doc = (settings.docflow_odata_base_url or "").strip().rstrip("/")
    if doc:
        if "/odata/" in doc:
            return doc.split("/odata/")[0] + "/hs/dterp"
        return doc + "/hs/dterp"
    erp = settings.odata_base_url.strip().rstrip("/")
    if "/erp_pm/" in erp:
        return erp.replace("/erp_pm/", "/doc/").split("/odata/")[0] + "/hs/dterp"
    return ""


def dok_endpoint_url(*, template: str = "TasksII", suffix: str = "User") -> str:
    base = dok_http_base_url()
    if not base:
        return ""
    return f"{base}/{template.strip('/')}/{suffix.strip('/')}"


def _resolve_auth() -> tuple[str, str] | None:
    ctx = _request_auth.get()
    if ctx:
        return ctx
    user = (
        os.environ.get("DOK_HTTP_USER")
        or settings.dok_http_user
        or settings.docflow_odata_username
        or settings.erp_login
        or settings.odata_username
        or ""
    ).strip()
    password = (
        os.environ.get("DOK_HTTP_PASSWORD")
        or settings.dok_http_password
        or settings.docflow_odata_password
        or settings.erp_password
        or settings.odata_password
        or ""
    ).strip()
    if user and password:
        return user, password
    return None


def _parse_tasksii_payload(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if not isinstance(raw, dict):
        return []
    for key in ("rows", "tasks", "value", "Items", "items", "data", "Tasks"):
        block = raw.get(key)
        if isinstance(block, list):
            return [row for row in block if isinstance(row, dict)]
    return []


def _http_get_json(url: str, *, auth: tuple[str, str], params: dict[str, Any] | None = None) -> Any:
    headers = {"Accept": "application/json"}
    timeout = max(15.0, float(settings.odata_timeout_sec or 60))
    with httpx.Client(timeout=timeout, auth=auth) as client:
        response = client.get(url, params=params, headers=headers)
    if response.status_code in {401, 403}:
        raise RuntimeError(f"HTTP {response.status_code}: документооборот отклонил учётку")
    if response.status_code >= 400:
        snippet = response.text[:200].strip()
        raise RuntimeError(f"HTTP {response.status_code}: {snippet or response.reason_phrase}")
    return response.json()


# Платформенный идентификатор типа «Структура» для ЗначениеВСтрокуВнутр / ЗначениеИзСтрокиВнутр.
_STRUCTURE_TYPE_ID = "4238019d-7e49-4fc9-91db-b6b951d5cf8e"


def internal_due_structure(due: datetime) -> str:
    """Тело TaskPatch: Новый Структура("СрокИсполнения", КонецДня(дата))."""
    stamp = due.strftime("%Y%m%d%H%M%S")
    return (
        '{"#",'
        + _STRUCTURE_TYPE_ID
        + ',{1,{{"S","СрокИсполнения"},{"D",'
        + stamp
        + "}}}}"
    )


def end_of_day(day: datetime) -> datetime:
    return day.replace(hour=23, minute=59, second=59, microsecond=0)


def result_description(response_text: str) -> str:
    """ОписаниеРезультата из ответа dterp (внутреннее представление структуры)."""
    match = re.search(r'"ОписаниеРезультата"\}\s*,\s*\{"S","([^"]*)"', response_text or "")
    return match.group(1).strip() if match else ""


def patch_task_deadline(process_uid: str, due: datetime, *, method: str = "PATCH") -> str:
    """TaskPatch?UID= — перенос срока исполнения задачи в базе ДО (только PATCH)."""
    auth = _resolve_auth()
    base = dok_http_base_url()
    uid = (process_uid or "").strip()
    if not base:
        raise RuntimeError("HTTP документооборота не настроен (DOK_HTTP_*)")
    if not auth:
        raise RuntimeError("Нужны учётные данные сеанса 1С для базы документооборота")
    if not uid:
        raise RuntimeError("Не указан UID процесса")
    url = f"{base}/TaskPatch"
    body = internal_due_structure(end_of_day(due))
    headers = {"Content-Type": "text/plain;charset=UTF-8", "Accept": "*/*"}
    timeout = max(15.0, float(settings.odata_timeout_sec or 60))
    with httpx.Client(timeout=timeout, auth=auth) as client:
        response = client.request(
            method.upper(),
            url,
            params={"UID": uid},
            content=body.encode("utf-8"),
            headers=headers,
        )
    text = (response.text or "").strip()
    logger.info(
        "TaskPatch %s UID=%s HTTP %s body=%s",
        method.upper(),
        uid,
        response.status_code,
        text[:500].replace("\n", " ") or "<empty>",
    )
    if response.status_code in {401, 403}:
        raise RuntimeError(f"HTTP {response.status_code}: документооборот отклонил учётку")
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {text[:200] or response.reason_phrase}")
    return text


def _http_post_json(url: str, *, auth: tuple[str, str], body: dict[str, Any]) -> Any:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    timeout = max(15.0, float(settings.odata_timeout_sec or 60))
    with httpx.Client(timeout=timeout, auth=auth) as client:
        response = client.post(url, json=body, headers=headers)
    if response.status_code in {401, 403}:
        raise RuntimeError(f"HTTP {response.status_code}: документооборот отклонил учётку")
    if response.status_code >= 400:
        snippet = response.text[:200].strip()
        raise RuntimeError(f"HTTP {response.status_code}: {snippet or response.reason_phrase}")
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("HTTP TasksII: ответ не JSON") from exc


def fetch_user_document_executions(user_ref: str, *, user_fio: str = "") -> list[dict[str, Any]]:
    """Строки TasksII/User для пользователя (GUID или ФИО в UserRef)."""
    auth = _resolve_auth()
    base = dok_http_base_url()
    ref = (user_ref or user_fio or "").strip()
    if not base or not auth or not ref:
        return []

    attempts: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = [
        ("GET", f"{base}/TasksII/User", {"UserRef": ref, "UserID": ref}, None),
        ("GET", f"{base}/TasksII/User", {"UserRef": ref}, None),
    ]
    if user_fio.strip() and user_fio.strip() != ref:
        attempts.append(
            ("GET", f"{base}/TasksII/User", {"UserRef": user_fio.strip(), "UserID": ref}, None)
        )
    attempts.extend(
        [
            ("GET", f"{base}/TasksII/User/{ref}", None, None),
            (
                "POST",
                f"{base}/TasksII/User",
                None,
                {"UserRef": ref, "UserID": ref, "Ref_Key": ref},
            ),
        ]
    )

    for method, url, params, body in attempts:
        try:
            if method == "GET":
                payload = _http_get_json(url, auth=auth, params=params)
            else:
                payload = _http_post_json(url, auth=auth, body=body or {})
        except (httpx.HTTPError, RuntimeError, json.JSONDecodeError):
            continue
        rows = _parse_tasksii_payload(payload)
        if rows:
            return rows
    return []
