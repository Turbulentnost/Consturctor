"""Stub linter integration — reports honest unavailability."""

from __future__ import annotations

from agent.types import ToolResult


def read_lints(workspace_root: str, paths: list[str] | None = None) -> ToolResult:
    tool = "read_lints"
    return ToolResult.failure(
        tool,
        "unavailable",
        "Linter integration is not configured in this runtime. "
        "Use run_terminal with ruff/pytest/mypy after edits, or wire an LSP client here.",
    )
