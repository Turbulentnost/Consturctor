"""Run a local subprocess without pipe deadlock.

Windows capture_output=True can block when the child fills the pipe buffer.
This helper drains stdout/stderr on background threads and kills the process
tree on timeout.

The child must not inherit the parent stdin pipe: Electron sidecar talks JSON
on stdin, and a script that reads stdin (or CPython waiting on the pipe) would
sit until the tool timeout.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class CapturedProcess:
    """Result of a captured subprocess run."""

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


def wrap_powershell_command(command: str) -> str:
    """Force PowerShell to skip progress UI and exit with the last code."""
    body = (command or "").strip()
    return (
        "$ProgressPreference='SilentlyContinue'; "
        + body
        + "; exit $LASTEXITCODE"
    )


def kill_process_tree(pid: int) -> None:
    """Kill a process and its children. Best-effort, ASCII-safe."""
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return
    try:
        subprocess.run(
            ["kill", "-TERM", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return


def _windows_run_kwargs() -> dict:
    """Hide the console and detach from the parent stdin job on Windows."""
    if sys.platform != "win32":
        return {}
    flags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {"creationflags": flags, "startupinfo": startupinfo}


def run_captured(
    command: Sequence[str],
    *,
    cwd: str | Path,
    timeout: int,
    env: Mapping[str, str] | None = None,
) -> CapturedProcess:
    """Run command, drain pipes on threads, kill the tree on timeout."""
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    kwargs: dict = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if env is not None:
        kwargs["env"] = dict(env)
    kwargs.update(_windows_run_kwargs())
    process = subprocess.Popen(list(command), **kwargs)

    def _drain(stream, bucket: list[str]) -> None:
        if stream is None:
            return
        try:
            while True:
                chunk = stream.readline()
                if chunk == "":
                    break
                bucket.append(chunk)
        except Exception:
            return

    stdout_thread = threading.Thread(
        target=_drain, args=(process.stdout, stdout_chunks), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_drain, args=(process.stderr, stderr_chunks), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()

    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_process_tree(process.pid)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=3)
            except Exception:
                pass

    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    return CapturedProcess(
        exit_code=None if timed_out else process.returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        timed_out=timed_out,
    )
