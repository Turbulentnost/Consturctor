"""Локальная история чата агента: {workspace}/session_log.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

_PREVIEW_LIMIT = 180
_COLLAPSE_CHARS = 240
_COLLAPSE_LINES = 6
_ALWAYS_COLLAPSE = frozenset({"thinking", "tool"})

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


def user_turns(entries: Sequence[LogEntry | dict[str, Any]]) -> list[str]:
    turns: list[str] = []
    for row in entries:
        kind, text = _parse_row(row)
        if kind == "user" and text:
            turns.append(text)
    return turns


def preview_text(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    cut = compact[:limit].rsplit(" ", 1)[0].rstrip()
    return (cut or compact[:limit]) + "…"


def should_collapse_entry(kind: str, text: str) -> bool:
    if kind in _ALWAYS_COLLAPSE:
        return True
    body = (text or "").strip()
    if len(body) > _COLLAPSE_CHARS:
        return True
    return body.count("\n") >= _COLLAPSE_LINES


def format_history_body(text: str) -> str:
    raw = (text or "").replace("\r\n", "\n").strip()
    if not raw:
        return ""
    pretty = _try_pretty_json(raw)
    if pretty:
        return pretty
    newline = raw.find("\n")
    if newline == -1:
        return raw
    head, rest = raw[:newline], raw[newline + 1 :].strip()
    pretty = _try_pretty_json(rest)
    if pretty:
        return f"{head}\n{pretty}"
    return raw


def _try_pretty_json(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped or stripped[0] not in "{[":
        return ""
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return ""
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _parse_row(row: object) -> tuple[str, str]:
    if isinstance(row, dict):
        kind = str(row.get("kind") or "").strip()
        text = str(row.get("text") or "").strip()
        return kind, text
    if isinstance(row, (list, tuple)) and len(row) >= 2:
        return str(row[0] or "").strip(), str(row[1] or "").strip()
    return "", ""
