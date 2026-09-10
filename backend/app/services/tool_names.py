"""Canonical tool names: Cursor/MCP often strip dots from onec.download_artifact."""

from __future__ import annotations

from collections.abc import Iterable


def compact_tool_name(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def resolve_tool_name(name: str, allowed: Iterable[str]) -> str | None:
    raw = (name or "").strip()
    if not raw:
        return None
    pool = list(allowed)
    if raw in pool:
        return raw
    dotted = raw.replace("_", ".")
    if dotted in pool:
        return dotted
    compact = compact_tool_name(raw)
    matches = [item for item in pool if compact_tool_name(item) == compact]
    if len(matches) == 1:
        return matches[0]
    return None
