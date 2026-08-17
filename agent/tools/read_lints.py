"""Linter diagnostics via ruff when available."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from agent.safety import SafetyError, resolve_workspace_path, safety_failure
from agent.types import ToolResult


def read_lints(workspace_root: str, paths: list[str] | None = None) -> ToolResult:
    tool = "read_lints"
    root = Path(workspace_root).resolve()
    targets: list[Path] = []
    if paths:
        for item in paths:
            try:
                targets.append(resolve_workspace_path(root, item))
            except SafetyError as exc:
                return safety_failure(tool, exc)
    else:
        targets = [root]

    ruff = shutil.which("ruff")
    if not ruff:
        return ToolResult.failure(
            tool,
            "unavailable",
            "ruff is not installed. Run: pip install ruff — or use run_terminal with ruff/pytest.",
        )

    cmd = [ruff, "check", "--output-format", "json"]
    cmd.extend(str(t) for t in targets)
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root), timeout=60)
    except subprocess.TimeoutExpired:
        return ToolResult.failure(tool, "timeout", "ruff timed out after 60s")
    except OSError as exc:
        return ToolResult.failure(tool, "unavailable", str(exc))

    diagnostics: list[dict[str, str | int]] = []
    if completed.stdout.strip():
        try:
            raw = json.loads(completed.stdout)
            if isinstance(raw, list):
                for item in raw:
                    diagnostics.append(
                        {
                            "path": str(item.get("filename") or ""),
                            "line": int(item.get("location", {}).get("row") or 0),
                            "column": int(item.get("location", {}).get("column") or 0),
                            "code": str(item.get("code") or ""),
                            "message": str(item.get("message") or ""),
                        }
                    )
        except json.JSONDecodeError:
            diagnostics = [{"path": "", "line": 0, "column": 0, "code": "", "message": completed.stdout[:2000]}]

    return ToolResult.success(
        tool,
        {
            "linter": "ruff",
            "count": len(diagnostics),
            "diagnostics": diagnostics,
            "exit_code": completed.returncode,
        },
    )
