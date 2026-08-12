"""Regex search across files (rg-like path:line:content output)."""

from __future__ import annotations

import re
from pathlib import Path

from agent.safety import SafetyError, resolve_workspace_path, safety_failure, should_skip_dir
from agent.types import ToolResult


def grep_search(
    workspace_root: str,
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    case_insensitive: bool = False,
    head_limit: int | None = None,
) -> ToolResult:
    tool = "grep"
    root = Path(workspace_root).resolve()
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return ToolResult.failure(tool, "invalid_pattern", f"Invalid regex: {exc}")

    search_root = root
    if path is not None:
        try:
            search_root = resolve_workspace_path(root, path)
        except SafetyError as exc:
            return safety_failure(tool, exc)

    files = _collect_files(search_root, root, glob)
    matches: list[dict[str, str | int]] = []
    truncated = False

    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = file_path.relative_to(root).as_posix()
        for line_no, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append({"path": rel, "line": line_no, "content": line})
                if head_limit is not None and len(matches) >= head_limit:
                    truncated = True
                    break
        if truncated:
            break

    formatted = [f"{m['path']}:{m['line']}:{m['content']}" for m in matches]
    return ToolResult.success(
        tool,
        {
            "pattern": pattern,
            "matches": matches,
            "formatted": formatted,
            "count": len(matches),
            "truncated": truncated,
        },
    )


def _collect_files(search_root: Path, workspace_root: Path, glob_pattern: str | None) -> list[Path]:
    import fnmatch

    if search_root.is_file():
        return [search_root]

    results: list[Path] = []
    stack = [search_root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if should_skip_dir(entry.name):
                    continue
                stack.append(entry)
            elif entry.is_file():
                rel = entry.relative_to(workspace_root).as_posix()
                if glob_pattern is None or fnmatch.fnmatch(rel, glob_pattern.replace("\\", "/")):
                    results.append(entry)
    results.sort()
    return results
