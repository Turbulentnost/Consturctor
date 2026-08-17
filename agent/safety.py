"""Path sandbox, command policy, and size limits."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from agent.types import ToolResult

SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
}

SECRET_FILE_NAMES = {".env", ".env.local", "credentials.json", "secrets.json"}

# Destructive or file-writing shell patterns (case-insensitive).
COMMAND_DENY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\b", re.I),
    re.compile(r"\bdel\b", re.I),
    re.compile(r"\brmdir\b", re.I),
    re.compile(r"\bformat\b", re.I),
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r"\bdd\b", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\breboot\b", re.I),
    re.compile(r"\bpoweroff\b", re.I),
    re.compile(r"\bkill\b", re.I),
    re.compile(r"\bpkill\b", re.I),
    re.compile(r"\btaskkill\b", re.I),
    re.compile(r"\bgit\s+push\s+--force\b", re.I),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.I),
    re.compile(r"\bgit\s+clean\b", re.I),
    re.compile(r"[>|]\s*[^\s]", re.I),  # redirection / pipe-to-file
    re.compile(r"\btee\b", re.I),
    re.compile(r"\b(?:>|>>)\s", re.I),
    re.compile(r"\b(?:echo|printf|cat)\s+.+?\s*(?:>|>>)", re.I),
    re.compile(r"\b(?:curl|wget)\s+.+\s+(?:-o|--output)\b", re.I),
]

ALLOWED_COMMAND_PREFIXES = (
    "python",
    "py ",
    "pytest",
    "pip",
    "git ",
    "npm ",
    "node ",
    "ruff ",
    "mypy ",
    "uv ",
    "cargo ",
    "go ",
    "make ",
    "dir",
    "ls",
    "type ",
    "echo ",  # plain echo without redirection only
    "where ",
    "which ",
    "cd ",
)


class SafetyError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_workspace_path(workspace_root: str | Path, user_path: str) -> Path:
    """Resolve *user_path* inside the workspace; reject traversal."""
    root = Path(workspace_root).resolve()
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SafetyError(
            "path_outside_workspace",
            f"Path '{user_path}' resolves outside workspace root '{root}'.",
        ) from exc
    return resolved


def assert_writable_path(workspace_root: str | Path, user_path: str) -> Path:
    resolved = resolve_workspace_path(workspace_root, user_path)
    if resolved.name in SECRET_FILE_NAMES:
        raise SafetyError(
            "secret_file",
            f"Refusing to modify secret file '{resolved.name}'. Explicit user request required.",
        )
    return resolved


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES


def truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    note = f"\n\n[truncated: output exceeded {max_bytes} bytes]"
    return truncated + note, True


def assert_command_allowed(command: str) -> None:
    stripped = command.strip()
    if not stripped:
        raise SafetyError("empty_command", "Command must not be empty.")

    for pattern in COMMAND_DENY_PATTERNS:
        if pattern.search(stripped):
            raise SafetyError(
                "command_denied",
                f"Command blocked by safety policy: {pattern.pattern!r}. "
                "Use file tools (write_file/str_replace) for source edits; shell is for run/test/build only.",
            )

    lowered = stripped.lower()
    if not any(lowered.startswith(prefix.strip()) for prefix in ALLOWED_COMMAND_PREFIXES):
        raise SafetyError(
            "command_not_allowed",
            "Command not on allowlist. Allowed prefixes include: "
            + ", ".join(sorted({p.strip() for p in ALLOWED_COMMAND_PREFIXES})),
        )


def resolve_cwd(workspace_root: str | Path, cwd: str | None) -> Path:
    root = Path(workspace_root).resolve()
    if cwd is None:
        return root
    return resolve_workspace_path(root, cwd)


def safety_failure(tool: str, exc: SafetyError) -> ToolResult:
    return ToolResult.failure(tool, exc.code, exc.message)


def split_command(command: str) -> list[str]:
    """Best-effort command split for subprocess (Windows-friendly via shell=False when possible)."""
    try:
        return shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return [command]
