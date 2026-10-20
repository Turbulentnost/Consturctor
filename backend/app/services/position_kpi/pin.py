"""Личный PIN-код сотрудника: без него зарплата на вкладке KPI не открывается.

PIN задаёт сам сотрудник при первом входе в KPI и меняет в настройках, зная старый.
В базе лежат соль и PBKDF2-хеш с секретом сервера: по одной выгрузке таблицы
четыре цифры не подобрать.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import UserKpiPin

PIN_LENGTH = 4
_ITERATIONS = 200_000
_MAX_ATTEMPTS = 5
_ATTEMPT_WINDOW_SEC = 300

_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}


class KpiPinError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _hash(pin: str, salt: str) -> str:
    material = f"{settings.jwt_secret}|kpi-pin|{pin}".encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", material, bytes.fromhex(salt), _ITERATIONS).hex()


def _check_format(pin: str) -> str:
    text = str(pin or "")
    if len(text) != PIN_LENGTH or not text.isdigit():
        raise KpiPinError(f"PIN-код — {PIN_LENGTH} цифры")
    return text


def _check_repeat(pin: str, repeat: str) -> str:
    text = _check_format(pin)
    if not hmac.compare_digest(text, str(repeat or "")):
        raise KpiPinError("PIN-коды не совпадают")
    return text


def _check_rate(user_id: str) -> None:
    now = time.monotonic()
    with _lock:
        recent = [stamp for stamp in _attempts.get(user_id, []) if now - stamp < _ATTEMPT_WINDOW_SEC]
        _attempts[user_id] = recent
        if len(recent) >= _MAX_ATTEMPTS:
            raise KpiPinError("Слишком много неверных попыток. Подождите 5 минут.", 429)


def _record_failure(user_id: str) -> None:
    with _lock:
        _attempts.setdefault(user_id, []).append(time.monotonic())


def _record(db: Session, user_id: str) -> UserKpiPin | None:
    if not user_id:
        raise KpiPinError("Нет пользователя", 401)
    return db.get(UserKpiPin, user_id)


def has_pin(db: Session, user_id: str) -> bool:
    return _record(db, user_id) is not None


def _store(db: Session, user_id: str, pin: str, record: UserKpiPin | None) -> None:
    salt = secrets.token_hex(16)
    if record is None:
        db.add(UserKpiPin(user_id=user_id, salt=salt, pin_hash=_hash(pin, salt)))
    else:
        record.salt = salt
        record.pin_hash = _hash(pin, salt)
    db.commit()


def set_pin(db: Session, user_id: str, pin: str, repeat: str) -> None:
    """Первый PIN. Если он уже есть — только смена со старым PIN."""
    record = _record(db, user_id)
    if record is not None:
        raise KpiPinError("PIN-код уже задан. Сменить его можно в настройках, в разделе «Безопасность».", 409)
    _store(db, user_id, _check_repeat(pin, repeat), None)


def verify_pin(db: Session, user_id: str, pin: str) -> None:
    record = _record(db, user_id)
    if record is None:
        raise KpiPinError("Сначала придумайте PIN-код", 409)
    _check_rate(user_id)
    if not hmac.compare_digest(_hash(str(pin or ""), record.salt), record.pin_hash):
        _record_failure(user_id)
        raise KpiPinError("Неверный PIN-код", 403)
    with _lock:
        _attempts.pop(user_id, None)


def change_pin(db: Session, user_id: str, current: str, pin: str, repeat: str) -> None:
    record = _record(db, user_id)
    if record is None:
        raise KpiPinError("PIN-код ещё не задан", 409)
    new_pin = _check_repeat(pin, repeat)
    try:
        verify_pin(db, user_id, current)
    except KpiPinError as exc:
        if exc.status_code == 403:
            raise KpiPinError("Старый PIN-код неверный", 403) from exc
        raise
    if hmac.compare_digest(new_pin, str(current or "")):
        raise KpiPinError("Новый PIN-код совпадает со старым")
    _store(db, user_id, new_pin, record)
