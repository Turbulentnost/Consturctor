"""Настройки интерфейса пользователя. Секции сливаются по ключу, чтобы
сохранение меню не затирало раскладку «Сегодня» с другого устройства."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.user_ui_prefs import UserUiPrefs

SECTIONS = ("sidebar", "today")
MAX_BYTES = 200_000


class UserUiPrefsError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _section_patch(raw: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key in SECTIONS:
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, dict):
            raise UserUiPrefsError(f"Поле {key} должно быть объектом")
        patch[key] = value
    return patch


def merge_sections(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in patch.items():
        base = merged.get(key)
        merged[key] = {**(base if isinstance(base, dict) else {}), **value}
    return merged


def read_prefs(db: Session, *, user_id: str) -> dict[str, Any]:
    row = db.get(UserUiPrefs, user_id)
    body = row.body if row is not None and isinstance(row.body, dict) else {}
    return {key: body[key] for key in SECTIONS if isinstance(body.get(key), dict)}


def save_prefs(db: Session, *, user_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    patch = _section_patch(raw)
    if not patch:
        return read_prefs(db, user_id=user_id)
    row = db.get(UserUiPrefs, user_id)
    current = row.body if row is not None and isinstance(row.body, dict) else {}
    body = merge_sections(current, patch)
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise UserUiPrefsError("Настройки интерфейса слишком большие")
    if row is None:
        row = UserUiPrefs(user_id=user_id, body=body)
        db.add(row)
    else:
        row.body = body
        flag_modified(row, "body")
    db.commit()
    return {key: body[key] for key in SECTIONS if isinstance(body.get(key), dict)}
