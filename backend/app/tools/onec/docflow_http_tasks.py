"""HTTP TasksII/User — задачи документа (ТД_ЗадачиДокумента), если опубликован hs/dterp."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.config import settings
from app.services.docflow_document_tasks import (
    filter_document_executor_rows,
    map_document_executor_row,
)


def dok_http_base_url() -> str:
    explicit = (os.environ.get("DOK_HTTP_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    doc = (settings.docflow_odata_base_url or "").strip().rstrip("/")
    if doc:
        if "/odata/" in doc:
            return doc.split("/odata/")[0] + "/hs/dterp"
        return doc + "/hs/dterp"
    erp = settings.odata_base_url.strip().rstrip("/")
    if "/erp_pm/" in erp:
        return erp.replace("/erp_pm/", "/doc/").split("/odata/")[0] + "/hs/dterp"
    return ""


def dok_http_auth(auth_args: dict[str, Any] | None = None) -> tuple[str, str] | None:
    payload = auth_args if isinstance(auth_args, dict) else {}
    user = str(
        payload.get("fio")
        or payload.get("username")
        or os.environ.get("DOK_HTTP_USER")
        or settings.docflow_odata_username
        or settings.erp_login
        or settings.odata_username
        or ""
    ).strip()
    password = str(
        payload.get("password")
        or payload.get("erp_password")
        or os.environ.get("DOK_HTTP_PASSWORD")
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
    for key in ("rows", "tasks", "value", "Items", "items", "data"):
        block = raw.get(key)
        if isinstance(block, list):
            return [row for row in block if isinstance(row, dict)]
    return []


def _request_tasksii(user_ref: str, *, auth: tuple[str, str]) -> list[dict[str, Any]]:
    base = dok_http_base_url()
    if not base:
        return []
    ref = user_ref.strip()
    headers = {"Accept": "application/json"}
    attempts: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", f"{base}/TasksII/User", {"UserRef": ref, "UserID": ref}),
        ("GET", f"{base}/TasksII/User/{ref}", None),
        ("POST", f"{base}/TasksII/User", None),
    ]
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        for method, url, params in attempts:
            try:
                if method == "GET":
                    response = client.get(url, params=params, headers=headers)
                else:
                    response = client.post(
                        url,
                        json={"UserRef": ref, "UserID": ref, "Ref_Key": ref},
                        headers={**headers, "Content-Type": "application/json"},
                    )
            except httpx.HTTPError:
                continue
            if response.status_code in {401, 403, 404}:
                continue
            if response.status_code >= 400:
                continue
            try:
                payload = response.json()
            except json.JSONDecodeError:
                continue
            rows = _parse_tasksii_payload(payload)
            if rows:
                return rows
    return []


def fetch_document_executor_tasks_http(
    *,
    user_ref: str,
    fio: str,
    only_open: bool,
    limit: int,
    auth_args: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """TasksII/User rows where Исполнитель matches session FIO (ТД_ЗадачиДокумента)."""
    auth = dok_http_auth(auth_args)
    if not dok_http_base_url() or not auth or not user_ref.strip():
        return [], ""
    from app.tools.onec import dok_http

    dok_http.set_request_auth(auth[0], auth[1])
    try:
        rows = dok_http.fetch_user_document_executions(user_ref.strip(), user_fio=fio)
        if not rows and fio.strip() and fio.strip() != user_ref.strip():
            rows = dok_http.fetch_user_document_executions(fio.strip(), user_fio=fio)
    except Exception as exc:  # noqa: BLE001
        return [], f"TasksII: {exc}".strip()
    finally:
        dok_http.clear_request_auth()

    if not rows:
        return [], ""
    filtered = filter_document_executor_rows(rows, fio=fio, only_open=only_open)
    mapped = [map_document_executor_row(row, fio=fio) for row in filtered[:limit]]
    return mapped, ""
