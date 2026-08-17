"""Apply a targeted string replacement (preferred edit method)."""

from __future__ import annotations

from agent.safety import SafetyError, assert_writable_path, safety_failure
from agent.types import ToolResult


def str_replace(
    workspace_root: str,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> ToolResult:
    tool = "str_replace"
    try:
        resolved = assert_writable_path(workspace_root, path)
    except SafetyError as exc:
        return safety_failure(tool, exc)

    if not resolved.exists():
        return ToolResult.failure(
            tool,
            "not_found",
            f"File not found: {path}. Use write_file to create new files.",
        )
    if not resolved.is_file():
        return ToolResult.failure(tool, "not_a_file", f"Path is not a file: {path}")

    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult.failure(tool, "binary_file", f"Cannot edit binary file: {path}")

    count = text.count(old_string)
    if count == 0:
        return ToolResult.failure(
            tool,
            "not_found",
            f"old_string not found in {path}. Read the file first and copy an exact unique snippet.",
        )
    if count > 1 and not replace_all:
        return ToolResult.failure(
            tool,
            "ambiguous",
            f"old_string matches {count} times in {path}. Provide more context or set replace_all=true.",
        )

    if replace_all:
        updated = text.replace(old_string, new_string)
        replacements = count
    else:
        updated = text.replace(old_string, new_string, 1)
        replacements = 1

    resolved.write_text(updated, encoding="utf-8")
    return ToolResult.success(
        tool,
        {
            "path": str(resolved.relative_to(workspace_root)).replace("\\", "/"),
            "replacements": replacements,
            "bytes_written": len(updated.encode("utf-8")),
        },
    )
