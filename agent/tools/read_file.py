"""Read file contents with optional windowing."""

from __future__ import annotations

from agent.safety import SafetyError, resolve_workspace_path, safety_failure
from agent.types import ToolResult


def read_file(
    workspace_root: str,
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> ToolResult:
    tool = "read_file"
    try:
        resolved = resolve_workspace_path(workspace_root, path)
    except SafetyError as exc:
        return safety_failure(tool, exc)

    if not resolved.exists():
        return ToolResult.failure(tool, "not_found", f"File not found: {path}")
    if not resolved.is_file():
        return ToolResult.failure(tool, "not_a_file", f"Path is not a file: {path}")

    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult.failure(
            tool,
            "binary_file",
            f"Cannot read binary file as UTF-8: {path}. Use run_terminal for binary inspection.",
        )

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    start = max(1, offset or 1)
    end = total_lines if limit is None else min(total_lines, start + limit - 1)
    if start > total_lines:
        window = ""
        truncated = False
    else:
        window = "".join(lines[start - 1 : end])
        truncated = limit is not None and end < total_lines

    return ToolResult.success(
        tool,
        {
            "path": str(resolved.relative_to(workspace_root)).replace("\\", "/"),
            "content": window,
            "start_line": start,
            "end_line": end if total_lines else 0,
            "total_lines": total_lines,
            "truncated": truncated,
        },
    )
