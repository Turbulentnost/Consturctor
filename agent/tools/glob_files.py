"""Glob file search with skip rules for common vendor/build dirs."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from agent.safety import SafetyError, resolve_workspace_path, safety_failure, should_skip_dir
from agent.types import ToolResult


def glob_files(
    workspace_root: str,
    pattern: str,
    target_directory: str | None = None,
) -> ToolResult:
    tool = "glob"
    try:
        base = resolve_workspace_path(workspace_root, target_directory or ".")
    except SafetyError as exc:
        return safety_failure(tool, exc)

    if not base.is_dir():
        return ToolResult.failure(tool, "not_a_directory", f"Not a directory: {target_directory or '.'}")

    normalized_pattern = pattern.replace("\\", "/")
    if not normalized_pattern.startswith("**/"):
        normalized_pattern = f"**/{normalized_pattern.lstrip('/')}"

    matches: list[str] = []
    root = Path(workspace_root).resolve()

    for dirpath, dirnames, filenames in _walk(base):
        rel_dir = dirpath.relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""

        for name in filenames:
            rel_path = f"{rel_dir}/{name}" if rel_dir else name
            rel_norm = rel_path.replace("\\", "/")
            if fnmatch.fnmatch(rel_norm, normalized_pattern) or fnmatch.fnmatch(name, pattern.replace("\\", "/")):
                matches.append(rel_norm)

    matches.sort(key=lambda p: _mtime_key(root / p), reverse=True)
    return ToolResult.success(
        tool,
        {
            "pattern": pattern,
            "target_directory": str(base.relative_to(root)).replace("\\", "/") if base != root else ".",
            "matches": matches,
            "count": len(matches),
        },
    )


def _walk(base: Path):
    """Depth-first walk that prunes skipped directories."""
    stack = [base]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        dirs: list[Path] = []
        files: list[str] = []
        for entry in entries:
            if entry.is_dir():
                if should_skip_dir(entry.name):
                    continue
                dirs.append(entry)
            elif entry.is_file():
                files.append(entry.name)
        yield current, [d.name for d in dirs], files
        stack.extend(reversed(dirs))


def _mtime_key(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
