"""Regex search — prefers ripgrep (rg) when available, else Python walk."""

from __future__ import annotations

import re
import shutil
import subprocess
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
    context_before: int | None = None,
    context_after: int | None = None,
) -> ToolResult:
    tool = "grep"
    root = Path(workspace_root).resolve()

    search_root = root
    if path is not None:
        try:
            search_root = resolve_workspace_path(root, path)
        except SafetyError as exc:
            return safety_failure(tool, exc)

    rg = shutil.which("rg")
    if rg:
        return _grep_rg(
            rg,
            root,
            search_root,
            pattern,
            glob,
            case_insensitive,
            head_limit,
            context_before,
            context_after,
        )

    return _grep_python(
        root,
        search_root,
        pattern,
        glob,
        case_insensitive,
        head_limit,
    )


def _grep_rg(
    rg: str,
    workspace_root: Path,
    search_root: Path,
    pattern: str,
    glob_pattern: str | None,
    case_insensitive: bool,
    head_limit: int | None,
    context_before: int | None,
    context_after: int | None,
) -> ToolResult:
    tool = "grep"
    cmd = [rg, "--line-number", "--no-heading", "--color=never", "--with-filename", pattern, str(search_root)]
    if case_insensitive:
        cmd.insert(1, "-i")
    if glob_pattern:
        cmd.insert(-1, "--glob")
        cmd.insert(-1, glob_pattern)
    if context_before:
        cmd.insert(-1, f"-B{int(context_before)}")
    if context_after:
        cmd.insert(-1, f"-A{int(context_after)}")
    if head_limit is not None:
        cmd.insert(-1, "--max-count")
        cmd.insert(-1, str(head_limit))

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(workspace_root),
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return ToolResult.failure(tool, "timeout", "rg timed out after 60s")

    lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
    if head_limit is not None:
        lines = lines[:head_limit]

    matches: list[dict[str, str | int]] = []
    for line in lines:
        parsed = _parse_rg_line(line, workspace_root)
        if parsed:
            matches.append(parsed)

    formatted = [f"{m['path']}:{m['line']}:{m['content']}" for m in matches if "content" in m]
    return ToolResult.success(
        tool,
        {
            "pattern": pattern,
            "engine": "rg",
            "matches": matches,
            "formatted": formatted,
            "count": len(matches),
            "truncated": head_limit is not None and len(matches) >= head_limit,
        },
    )


def _parse_rg_line(line: str, workspace_root: Path) -> dict[str, str | int] | None:
    if line.startswith("--"):
        return {"path": "", "line": 0, "content": line}
    match = re.match(r"^(?P<path>.*?):(?P<line>\d+):(?P<content>.*)$", line)
    if not match:
        return None
    file_part = match.group("path")
    line_no = int(match.group("line"))
    content = match.group("content")
    try:
        rel = Path(file_part).resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        rel = file_part.replace("\\", "/")
    return {"path": rel, "line": line_no, "content": content}


def _grep_python(
    workspace_root: Path,
    search_root: Path,
    pattern: str,
    glob_pattern: str | None,
    case_insensitive: bool,
    head_limit: int | None,
) -> ToolResult:
    tool = "grep"
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return ToolResult.failure(tool, "invalid_pattern", f"Invalid regex: {exc}")

    files = _collect_files(search_root, workspace_root, glob_pattern)
    matches: list[dict[str, str | int]] = []
    truncated = False

    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = file_path.relative_to(workspace_root).as_posix()
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
            "engine": "python",
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
