from __future__ import annotations

import json
import os
from pathlib import Path

from platform_orchestrator.tool_sandbox import SANDBOX_TESTS


class ToolNotAllowedError(PermissionError):
    pass


def _manifest_path(explicit: str = "") -> Path | None:
    raw = (explicit or os.environ.get("TOOL_MANIFEST_PATH") or "").strip()
    if not raw:
        default = Path(__file__).resolve().parents[3] / "backend" / "data" / "tool_manifest.json"
        if default.is_file():
            return default
        return None
    path = Path(raw)
    return path if path.is_file() else None


def allowed_tools_for_department(department: str, manifest_path: str = "") -> set[str] | None:
    path = _manifest_path(manifest_path)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    dept = department.strip()
    if not dept:
        return set(data.get("default", []))
    by_dept = data.get("by_department") or {}
    if dept in by_dept:
        return set(by_dept[dept])
    return set(data.get("default", []))


def ensure_tool_allowed(tool_name: str, department: str, manifest_path: str = "") -> None:
    allowed = allowed_tools_for_department(department, manifest_path)
    if allowed is not None and tool_name not in allowed:
        raise ToolNotAllowedError(f"Tool not allowed: {tool_name}")


def sandbox_allowed_tools() -> set[str]:
    names: set[str] = set()
    for scenario in SANDBOX_TESTS.values():
        for call in scenario["tool_calls"]:
            names.add(call["tool_name"])
    return names


def ensure_sandbox_tool_allowed(tool_name: str, department: str, manifest_path: str = "") -> None:
    if tool_name not in sandbox_allowed_tools():
        raise ToolNotAllowedError(f"Tool not in sandbox catalog: {tool_name}")
    ensure_tool_allowed(tool_name, department, manifest_path)
