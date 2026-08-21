"""Локальная история чата агента: {workspace}/session_log.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from app.config import WORKSPACES_DIR, ensure_data_dirs

HISTORY_LABELS: dict[str, str] = {
    "user": "Вы",
    "agent": "Агент",
    "thinking": "Размышление",
    "tool": "Инструмент",
    "system": "Система",
    "error": "Ошибка",
}

LogEntry = tuple[str, str]


def session_log_path(card_id: str, workspace_dir: str = "") -> Path:
    base = Path(workspace_dir) if (workspace_dir or "").strip() else (WORKSPACES_DIR / card_id)
    return base / "session_log.json"


def load_session_log(card_id: str, workspace_dir: str = "") -> list[LogEntry]:
    path = session_log_path(card_id, workspace_dir)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    items: list[LogEntry] = []
    for row in raw:
        kind, text = _parse_row(row)
        if kind and text:
            items.append((kind, text))
    return items


def save_session_log(
    card_id: str,
    entries: Sequence[LogEntry | dict[str, Any]],
    workspace_dir: str = "",
) -> Path:
    ensure_data_dirs()
    path = session_log_path(card_id, workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: list[dict[str, str]] = []
    for row in entries:
        kind, text = _parse_row(row)
        if not kind or not text:
            continue
        payload.append({"kind": kind, "text": text})
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def format_transcript(entries: Sequence[LogEntry | dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in entries:
        kind, text = _parse_row(row)
        body = (text or "").strip()
        if not kind or not body:
            continue
        label = HISTORY_LABELS.get(kind, kind)
        lines.append(f"**{label}**\n\n{body}\n")
    return "\n".join(lines).strip()


def _parse_row(row: object) -> tuple[str, str]:
    if isinstance(row, dict):
        kind = str(row.get("kind") or "").strip()
        text = str(row.get("text") or "").strip()
        return kind, text
    if isinstance(row, (list, tuple)) and len(row) >= 2:
        return str(row[0] or "").strip(), str(row[1] or "").strip()
    return "", ""
