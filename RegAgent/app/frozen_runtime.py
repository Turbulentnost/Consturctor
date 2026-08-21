"""Minimal frozen_runtime for COM subprocess workers (dev mode only)."""

from __future__ import annotations

import sys
from pathlib import Path


COM_WORKER_FLAG = "--com-worker"


def entry_mode(argv: list[str] | None = None) -> str:
    args = list(sys.argv if argv is None else argv)
    rest = args[1:]
    if rest and rest[0] == COM_WORKER_FLAG:
        return "com-worker"
    return "gui"


def desktop_root(*, frozen: bool | None = None, executable: str | None = None) -> Path:
    _ = frozen, executable
    return Path(__file__).resolve().parents[1]


def com_worker_command(executable: str, module_name: str, *, frozen: bool) -> list[str]:
    if not frozen:
        return [executable, "-m", module_name]
    return [executable, COM_WORKER_FLAG]


def run_com_worker(argv: list[str] | None = None) -> int:
    from app.tools.ported.ac.workers import com_worker_process

    return com_worker_process.main()
