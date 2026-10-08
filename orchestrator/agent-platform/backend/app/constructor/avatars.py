"""Аватары сотрудников с бэкенда Constructor (GET /api/v1/auth/users/{id}/avatar)."""

from __future__ import annotations

import re
import threading
import time
from urllib.parse import quote

import httpx

from app.config import settings

USER_ID_PATTERN = re.compile(r"[A-Za-z0-9_.:\-]{1,128}")
_HIT_TTL_SECONDS = 600
_MISS_TTL_SECONDS = 120

_cache: dict[str, tuple[float, tuple[bytes, str] | None]] = {}
_lock = threading.Lock()


class AvatarUnavailable(RuntimeError):
    pass


def fetch_avatar(user_id: str) -> tuple[bytes, str] | None:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(user_id)
        if cached and cached[0] > now:
            return cached[1]

    url = (
        f"{settings.constructor_api_url.rstrip('/')}"
        f"/api/v1/auth/users/{quote(user_id, safe='')}/avatar"
    )
    try:
        response = httpx.get(url, timeout=10.0)
    except httpx.HTTPError as exc:
        raise AvatarUnavailable(f"Constructor недоступен: {exc}") from exc

    if response.status_code == 404:
        result: tuple[bytes, str] | None = None
        ttl = _MISS_TTL_SECONDS
    elif response.is_success:
        media_type = response.headers.get("content-type", "").split(";")[0].strip()
        if not media_type.startswith("image/"):
            raise AvatarUnavailable(f"Constructor вернул не изображение: {media_type or '—'}")
        result = (response.content, media_type)
        ttl = _HIT_TTL_SECONDS
    else:
        raise AvatarUnavailable(f"Constructor ответил HTTP {response.status_code}")

    with _lock:
        _cache[user_id] = (now + ttl, result)
    return result
