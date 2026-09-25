"""Кэш списков задач документооборота в Redis (общий для gateway и локального backend)."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.config import settings
from app.tools.onec.dok_soap import parse_delegate_fios

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SEC = 1800


def _redis_client():
    try:
        from app.services.sessions import _redis

        return _redis()
    except Exception:
        return None


def _cred_fingerprint(auth_args: dict[str, Any] | None) -> str:
    payload = auth_args if isinstance(auth_args, dict) else {}
    password = str(payload.get("password") or payload.get("erp_password") or "").strip()
    if not password:
        return "nopw"
    return hashlib.sha256(password.encode("utf-8")).hexdigest()[:16]


def cache_key(
    fio: str,
    *,
    auth_args: dict[str, Any] | None,
    only_open: bool,
    today_and_overdue: bool,
) -> str:
    norm = " ".join((fio or "").split()).casefold()
    flags = f"o{int(only_open)}t{int(today_and_overdue)}"
    delegates = ",".join(
        sorted(" ".join(str(name).split()).casefold() for name in parse_delegate_fios((auth_args or {}).get("delegate_fios")))
    )
    if delegates:
        flags += ":d" + hashlib.sha256(delegates.encode("utf-8")).hexdigest()[:12]
    return f"docflow:tasks:v2:{norm}:{_cred_fingerprint(auth_args)}:{flags}"


def get_cached_tasks(key: str) -> list[dict[str, Any]] | None:
    client = _redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception as exc:
        logger.debug("docflow redis get failed: %s", exc)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return None


def set_cached_tasks(key: str, tasks: list[dict[str, Any]], *, ttl_sec: float | None = None) -> None:
    client = _redis_client()
    if client is None:
        return
    ttl = int(ttl_sec or settings.dok_http_cache_ttl_sec or _DEFAULT_TTL_SEC)
    ttl = max(60, ttl)
    try:
        client.setex(key, ttl, json.dumps(tasks, ensure_ascii=False, default=str))
    except Exception as exc:
        logger.debug("docflow redis set failed: %s", exc)
