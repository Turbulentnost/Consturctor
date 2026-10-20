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
    return f"docflow:tasks:v4:{norm}:{_cred_fingerprint(auth_args)}:{flags}"


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


_TASK_ID_KEYS = ("id", "task_id", "ref_key", "uid", "number")


def _row_is_task(row: dict[str, Any], wanted: set[str]) -> bool:
    return any(str(row.get(key) or "").strip().casefold() in wanted for key in _TASK_ID_KEYS)


def forget_cached_tasks(*task_ids: str) -> None:
    """Убрать закрытые задачи из списков в Redis, иначе перезагрузка вернёт их до конца TTL."""
    wanted = {str(item or "").strip().casefold() for item in task_ids if str(item or "").strip()}
    client = _redis_client()
    if not wanted or client is None:
        return
    try:
        keys = list(client.scan_iter(match="docflow:tasks:v4:*", count=100))
    except Exception as exc:
        logger.debug("docflow redis scan failed: %s", exc)
        return
    for key in keys:
        cached = get_cached_tasks(key if isinstance(key, str) else key.decode("utf-8"))
        if not cached:
            continue
        kept = [row for row in cached if not _row_is_task(row, wanted)]
        if len(kept) == len(cached):
            continue
        try:
            ttl = int(client.ttl(key) or 0)
        except Exception:
            ttl = 0
        set_cached_tasks(key if isinstance(key, str) else key.decode("utf-8"), kept, ttl_sec=ttl if ttl > 0 else None)


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
