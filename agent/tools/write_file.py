"""Write file contents (creates parent directories)."""

from __future__ import annotations

from agent.safety import SafetyError, assert_writable_path, safety_failure
from agent.types import ToolResult


def write_file(
    workspace_root: str,
    path: str,
    contents: str,
    max_bytes: int,
) -> ToolResult:
    tool = "write_file"
    encoded = contents.encode("utf-8")
    if len(encoded) > max_bytes:
        return ToolResult.failure(
            tool,
            "file_too_large",
            f"Refusing to write {len(encoded)} bytes (limit {max_bytes}). Split the file or use str_replace.",
        )

    try:
        resolved = assert_writable_path(workspace_root, path)
    except SafetyError as exc:
        return safety_failure(tool, exc)

    created = not resolved.exists()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(contents, encoding="utf-8")
    line_count = contents.count("\n") + (1 if contents and not contents.endswith("\n") else 0)
    if contents == "":
        line_count = 0

    return ToolResult.success(
        tool,
        {
            "path": str(resolved.relative_to(workspace_root)).replace("\\", "/"),
            "bytes_written": len(encoded),
            "lines_written": line_count,
            "created": created,
        },
    )
