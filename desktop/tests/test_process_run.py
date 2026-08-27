from __future__ import annotations

import sys
from pathlib import Path

from app.tools.ac.process_run import run_captured, wrap_powershell_command


def test_wrap_powershell_command_forces_silent_exit() -> None:
    wrapped = wrap_powershell_command("Get-ChildItem")
    assert wrapped.startswith("$ProgressPreference='SilentlyContinue'; ")
    assert wrapped.endswith("; exit $LASTEXITCODE")
    assert "Get-ChildItem" in wrapped


def test_run_captured_returns_stdout() -> None:
    completed = run_captured(
        [sys.executable, "-c", "print('hello-agent')"],
        cwd=Path(__file__).resolve().parent,
        timeout=15,
    )
    assert completed.timed_out is False
    assert completed.exit_code == 0
    assert "hello-agent" in completed.stdout


def test_run_captured_times_out_and_kills() -> None:
    completed = run_captured(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=Path(__file__).resolve().parent,
        timeout=1,
    )
    assert completed.timed_out is True
    assert completed.exit_code is None


def test_run_captured_stdin_is_eof_not_parent_pipe() -> None:
    """Child must not inherit sidecar/Electron stdin or it waits until timeout."""
    completed = run_captured(
        [sys.executable, "-c", "import sys; print(sys.stdin.read() or 'eof')"],
        cwd=Path(__file__).resolve().parent,
        timeout=10,
    )
    assert completed.timed_out is False
    assert completed.exit_code == 0
    assert "eof" in completed.stdout
