"""Пароль модуля KPI: без него форма премирования выгружается только в процентах.

Каждый сотрудник сам включает требование пароля. Хранится соль и PBKDF2-хеш
в файле профиля Windows, сам пароль нигде не сохраняется. После ввода пароля
выдаётся подписанный токен разблокировки с ограниченным сроком жизни.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

_ITERATIONS = 240_000
_UNLOCK_TTL_SEC = 8 * 3600
_MIN_PASSWORD = 4
_MAX_ATTEMPTS = 5
_ATTEMPT_WINDOW_SEC = 60

_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}


class KpiProtectionError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ProtectionState:
    enabled: bool
    has_password: bool


def _store_path() -> Path:
    override = os.environ.get("KPI_PROTECTION_PATH", "").strip()
    if override:
        return Path(override)
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(root) / "orchestrator" / "kpi_protection.json"


def _read_all() -> dict[str, dict]:
    path = _store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_all(data: dict[str, dict]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _hash(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return digest.hex()


def _record(user_id: str) -> dict:
    record = _read_all().get(user_id)
    return record if isinstance(record, dict) else {}


def get_state(user_id: str) -> ProtectionState:
    record = _record(user_id)
    has_password = bool(record.get("hash") and record.get("salt"))
    return ProtectionState(enabled=bool(record.get("enabled")) and has_password, has_password=has_password)


def _check_rate(user_id: str) -> None:
    now = time.monotonic()
    with _lock:
        recent = [stamp for stamp in _attempts.get(user_id, []) if now - stamp < _ATTEMPT_WINDOW_SEC]
        _attempts[user_id] = recent
        if len(recent) >= _MAX_ATTEMPTS:
            raise KpiProtectionError("Слишком много попыток. Подождите минуту.", 429)


def _fail(user_id: str) -> None:
    with _lock:
        _attempts.setdefault(user_id, []).append(time.monotonic())


def _verify(user_id: str, record: dict, password: str) -> None:
    _check_rate(user_id)
    salt = str(record.get("salt") or "")
    expected = str(record.get("hash") or "")
    if not salt or not expected or not hmac.compare_digest(_hash(password, salt), expected):
        _fail(user_id)
        raise KpiProtectionError("Неверный пароль KPI", 403)
    with _lock:
        _attempts.pop(user_id, None)


def update_protection(
    user_id: str,
    *,
    enabled: bool,
    password: str | None,
    current_password: str | None,
) -> ProtectionState:
    """Включить или выключить пароль, задать или сменить его. Любое изменение — с текущим паролем."""
    if not user_id:
        raise KpiProtectionError("Нет пользователя", 401)
    new_password = password or ""
    if new_password and len(new_password) < _MIN_PASSWORD:
        raise KpiProtectionError(f"Пароль KPI должен быть не короче {_MIN_PASSWORD} символов")
    with _lock:
        data = _read_all()
    record = data.get(user_id) if isinstance(data.get(user_id), dict) else {}
    if record.get("hash"):
        _verify(user_id, record, current_password or "")
    elif enabled and not new_password:
        raise KpiProtectionError("Задайте пароль KPI, чтобы включить защиту")
    updated = dict(record)
    if new_password:
        salt = secrets.token_hex(16)
        updated.update(salt=salt, hash=_hash(new_password, salt))
    updated["enabled"] = bool(enabled)
    with _lock:
        data = _read_all()
        data[user_id] = updated
        _write_all(data)
    return get_state(user_id)


def _secret(record: dict) -> bytes:
    return f"{settings.jwt_secret}|kpi-unlock|{record.get('salt') or ''}".encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def unlock(user_id: str, password: str) -> tuple[str, int]:
    """Проверить пароль и выдать токен разблокировки. Смена пароля отзывает старые токены."""
    record = _record(user_id)
    if not (record.get("enabled") and record.get("hash")):
        raise KpiProtectionError("Защита KPI выключена. Включите её в настройках.", 409)
    _verify(user_id, record, password)
    expires = int(time.time()) + _UNLOCK_TTL_SEC
    body = f"{user_id}|{expires}"
    signature = hmac.new(_secret(record), body.encode("utf-8"), hashlib.sha256).digest()
    return f"{_b64(body.encode('utf-8'))}.{_b64(signature)}", expires


def token_unlocks(user_id: str, token: str) -> bool:
    text = str(token or "").strip()
    if not user_id or "." not in text:
        return False
    record = _record(user_id)
    if not (record.get("enabled") and record.get("hash")):
        return False
    body_part, _, sig_part = text.partition(".")
    try:
        body = base64.urlsafe_b64decode(body_part + "=" * (-len(body_part) % 4)).decode("utf-8")
        signature = base64.urlsafe_b64decode(sig_part + "=" * (-len(sig_part) % 4))
    except (ValueError, UnicodeDecodeError):
        return False
    expected = hmac.new(_secret(record), body.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return False
    owner, _, expires = body.rpartition("|")
    return owner == user_id and expires.isdigit() and int(expires) > time.time()
