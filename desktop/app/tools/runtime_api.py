"""Shared HTTP access to Constructor backend from desktop tools."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import backend_url

_token: str | None = None
_base_url: str = ""


def configure(*, token: str | None, base_url: str = "") -> None:
    global _token, _base_url
    _token = token
    _base_url = (base_url or backend_url()).rstrip("/")


def _authorized_request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    timeout: float = 30.0,
    accept: str = "application/json",
) -> httpx.Response:
    if not _token:
        raise RuntimeError("Нет сессии пользователя — войдите в Constructor.")
    url = f"{_base_url}{path}"
    headers = {"Authorization": f"Bearer {_token}", "Accept": accept}
    with httpx.Client(timeout=timeout) as client:
        response = client.request(method, url, headers=headers, json=json, params=params)
    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            detail = str(payload.get("detail") or payload.get("message") or detail)
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(detail or f"HTTP {response.status_code}")
    return response


def request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    timeout: float = 30.0,
) -> Any:
    response = _authorized_request(
        method, path, json=json, params=params, timeout=timeout
    )
    if not response.content:
        return {}
    return response.json()


def request_bytes(
    method: str,
    path: str,
    *,
    timeout: float = 30.0,
) -> bytes:
    response = _authorized_request(
        method,
        path,
        timeout=timeout,
        accept="application/octet-stream",
    )
    return response.content or b""
