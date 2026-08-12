"""Run shell commands for test/build/run only — never for writing source."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from agent.safety import (
    SafetyError,
    assert_command_allowed,
    resolve_cwd,
    safety_failure,
    truncate_text,
)
from agent.types import ToolResult


def run_terminal(
    workspace_root: str,
    command: str,
    cwd: str | None = None,
    timeout_ms: int | None = None,
    env: dict[str, str] | None = None,
    max_output_bytes: int = 256_000,
) -> ToolResult:
    tool = "run_terminal"
    try:
        assert_command_allowed(command)
        workdir = resolve_cwd(workspace_root, cwd)
    except SafetyError as exc:
        return safety_failure(tool, exc)

    if not workdir.is_dir():
        return ToolResult.failure(tool, "invalid_cwd", f"Working directory not found: {cwd or '.'}")

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    timeout_sec = None if timeout_ms is None else max(0.001, timeout_ms / 1000.0)
    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(workdir),
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_trunc = truncate_text(exc.stdout or "", max_output_bytes)
        stderr, stderr_trunc = truncate_text(exc.stderr or "", max_output_bytes)
        return ToolResult.failure(
            tool,
            "timeout",
            f"Command timed out after {timeout_ms} ms.",
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    stdout, stdout_trunc = truncate_text(completed.stdout or "", max_output_bytes)
    stderr, stderr_trunc = truncate_text(completed.stderr or "", max_output_bytes)

    root = Path(workspace_root).resolve()
    wd = workdir.resolve()
    cwd_display = "." if wd == root else wd.relative_to(root).as_posix()

    return ToolResult.success(
        tool,
        {
            "command": command,
            "cwd": cwd_display,
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_trunc,
            "stderr_truncated": stderr_trunc,
            "duration_ms": elapsed_ms,
        },
    )
