from __future__ import annotations

import json

from app.config import constructor_instance
from PySide6.QtCore import QSettings

NAV_MIME = "application/x-turbobot-nav"
SIDES = ("left", "right", "top", "bottom")
FLOAT = "float"
DEFAULT_KEYS = ("create", "agents", "files", "kpi", "dashboard", "orchestrator", "chat")


def _settings() -> QSettings:
    return QSettings("turbobot", constructor_instance() or "desktop")


def default_layout() -> dict[str, list[str]]:
    return {
        "left": list(DEFAULT_KEYS),
        "right": [],
        "top": [],
        "bottom": [],
        FLOAT: [],
    }


def _normalize(raw: object) -> dict[str, list[str]]:
    layout = default_layout()
    if not isinstance(raw, dict):
        return layout
    seen: set[str] = set()
    allowed = set(DEFAULT_KEYS)
    for side in (*SIDES, FLOAT):
        rows = raw.get(side)
        keys: list[str] = []
        if isinstance(rows, list):
            for item in rows:
                key = str(item or "")
                if key in allowed and key not in seen:
                    keys.append(key)
                    seen.add(key)
        layout[side] = keys
    missing = [key for key in DEFAULT_KEYS if key not in seen]
    layout["left"] = missing + layout["left"]
    return layout


def load_layout() -> dict[str, list[str]]:
    raw = _settings().value("nav/dock_layout", "")
    if not raw:
        return default_layout()
    try:
        payload = json.loads(str(raw))
    except Exception:
        return default_layout()
    return _normalize(payload)


def save_layout(layout: dict[str, list[str]]) -> None:
    settings = _settings()
    settings.setValue("nav/dock_layout", json.dumps(_normalize(layout), ensure_ascii=False))
    settings.sync()


def _strip_key(layout: dict[str, list[str]], key: str) -> None:
    for name in (*SIDES, FLOAT):
        if key in layout[name]:
            layout[name].remove(key)


def move_key(layout: dict[str, list[str]], key: str, side: str) -> dict[str, list[str]]:
    next_layout = {name: list(keys) for name, keys in _normalize(layout).items()}
    if side not in SIDES or key not in DEFAULT_KEYS:
        return next_layout
    _strip_key(next_layout, key)
    next_layout[side].append(key)
    return next_layout


def detach_key(layout: dict[str, list[str]], key: str) -> dict[str, list[str]]:
    next_layout = {name: list(keys) for name, keys in _normalize(layout).items()}
    if key not in DEFAULT_KEYS:
        return next_layout
    _strip_key(next_layout, key)
    next_layout[FLOAT].append(key)
    return next_layout


def first_docked_key(layout: dict[str, list[str]]) -> str:
    normalized = _normalize(layout)
    for side in SIDES:
        if normalized[side]:
            return normalized[side][0]
    return ""


def save_float_geom(key: str, x: int, y: int, width: int, height: int) -> None:
    settings = _settings()
    settings.setValue(f"nav/float_geom/{key}", f"{x},{y},{width},{height}")
    settings.sync()


def load_float_geom(key: str) -> tuple[int, int, int, int] | None:
    raw = str(_settings().value(f"nav/float_geom/{key}", "") or "")
    parts = raw.split(",")
    if len(parts) != 4:
        return None
    try:
        x, y, width, height = (int(part) for part in parts)
    except ValueError:
        return None
    if width < 400 or height < 300:
        return None
    return x, y, width, height
