"""Delete a file within the workspace."""

from __future__ import annotations

from agent.safety import SafetyError, assert_writable_path, safety_failure
from agent.types import ToolResult


def delete_file(workspace_root: str, path: str) -> ToolResult:
    tool = "delete_file"
    try:
        resolved = assert_writable_path(workspace_root, path)
    except SafetyError as exc:
        return safety_failure(tool, exc)

    if not resolved.exists():
        return ToolResult.failure(tool, "not_found", f"File not found: {path}")
    if not resolved.is_file():
        return ToolResult.failure(tool, "not_a_file", f"Path is not a file: {path}")

    resolved.unlink()
    return ToolResult.success(
        tool,
        {"path": str(resolved.relative_to(workspace_root)).replace("\\", "/"), "deleted": True},
    )
