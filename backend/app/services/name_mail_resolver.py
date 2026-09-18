"""Latin mail slug (*@turbo-don.ru) when v8users.Name is Cyrillic FIO."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TURBO_DOMAIN = "turbo-don.ru"
_DISCOVER_CACHE: dict[str, tuple[str, float]] = {}
_DISCOVER_CACHE_TTL_SEC = 3600.0
_discover_lock = threading.Lock()

_CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def latin_slug_from_login(raw: str) -> str:
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


def _transliterate_word(word: str) -> str:
    out: list[str] = []
    for ch in (word or "").strip().casefold().replace("ё", "е"):
        if "\u0400" <= ch <= "\u04ff":
            out.append(_CYRILLIC_TO_LATIN.get(ch, ""))
        elif ch.isascii() and (ch.isalnum() or ch in "._-"):
            out.append(ch)
    return "".join(out)


def guess_name_mail_slugs(fio: str) -> list[str]:
    """Typical turbo-don.ru patterns from ФИО (e.surname, ea.surname, …)."""
    parts = [p.strip() for p in (fio or "").split() if p.strip()]
    if len(parts) < 2:
        return []
    surname = _transliterate_word(parts[0]).lower()
    given = _transliterate_word(parts[1]).lower()
    if not surname or not given:
        return []
    initials = "".join(_transliterate_word(p)[:1] for p in parts[1:] if _transliterate_word(p))
    i1 = given[:1]
    i2 = given[:2] if len(given) >= 2 else given
    raw_candidates = [
        f"{i1}.{surname}",
        f"{i2}.{surname}",
        f"{initials}.{surname}" if initials else "",
        f"{given}.{surname}",
        f"{i1}{surname}",
        f"{initials}{surname}" if initials else "",
        surname,
    ]
    seen: set[str] = set()
    out: list[str] = []
    for item in raw_candidates:
        slug = latin_slug_from_login(item)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return out


def _fio_cache_key(fio: str) -> str:
    return " ".join((fio or "").split()).casefold()


def _turbo_api_base() -> str:
    return (settings.turboproject_api_base or "").strip().rstrip("/")


def _try_turbo_login(email: str, password: str, *, client: httpx.Client) -> bool:
    base = _turbo_api_base()
    if not base or not email or not password:
        return False
    url = f"{base}/api/auth/login"
    try:
        response = client.post(url, json={"email": email, "password": password}, timeout=15.0)
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return bool(str(payload.get("token") or "").strip())


def discover_name_mail_slug(
    fio: str,
    password: str,
    *,
    login_probe: Callable[[str, str], bool] | None = None,
) -> str:
    """Find latin slug by probing TurboProject login with guessed emails."""
    fio_key = _fio_cache_key(fio)
    if not fio_key or not (password or "").strip():
        return ""
    now = time.monotonic()
    with _discover_lock:
        cached = _DISCOVER_CACHE.get(fio_key)
        if cached and now - cached[1] < _DISCOVER_CACHE_TTL_SEC:
            return cached[0]

    slugs = guess_name_mail_slugs(fio)
    if not slugs:
        return ""

    probe = login_probe
    client: httpx.Client | None = None
    if probe is None and _turbo_api_base():
        client = httpx.Client(timeout=15.0)

    try:
        for slug in slugs[:10]:
            email = f"{slug}@{_TURBO_DOMAIN}"
            ok = probe(email, password) if probe else _try_turbo_login(email, password, client=client)  # type: ignore[arg-type]
            if ok:
                with _discover_lock:
                    _DISCOVER_CACHE[fio_key] = (slug, time.monotonic())
                logger.info("Resolved name_mail slug for %s via TurboProject probe", fio)
                return slug
    finally:
        if client is not None:
            client.close()
    return ""


def resolve_name_mail_for_user(
    *,
    fio: str,
    erp_name: str = "",
    erp_descr: str = "",
    password: str = "",
    login_probe: Callable[[str, str], bool] | None = None,
) -> str:
    for raw in (erp_name, erp_descr):
        slug = latin_slug_from_login(raw)
        if slug:
            return slug
    return discover_name_mail_slug(fio, password, login_probe=login_probe)
