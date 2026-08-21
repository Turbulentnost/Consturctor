"""Режимы запуска: GUI, COM-worker и встроенный Python-runner для frozen exe."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


COM_WORKER_FLAG = "--com-worker"
AGENT_PYTHON_FLAG = "--agent-python-runner"


def entry_mode(argv: list[str] | None = None) -> str:
    args = list(sys.argv if argv is None else argv)
    rest = args[1:]
    if rest and rest[0] == COM_WORKER_FLAG:
        return "com-worker"
    if rest and rest[0] == AGENT_PYTHON_FLAG:
        return "agent-python"
    return "gui"


def desktop_root(*, frozen: bool | None = None, executable: str | None = None) -> Path:
    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    exe = executable or sys.executable
    if is_frozen and exe:
        return Path(exe).resolve().parent
    return Path(__file__).resolve().parents[1]


def com_worker_command(executable: str, module_name: str, *, frozen: bool) -> list[str]:
    if not frozen:
        return [executable, "-m", module_name]
    return [executable, COM_WORKER_FLAG]


def agent_python_command(executable: str, *, frozen: bool) -> list[str]:
    if frozen:
        return [executable, AGENT_PYTHON_FLAG]
    return [executable]


def run_com_worker(argv: list[str] | None = None) -> int:
    from app.tools.ported.ac.workers import com_worker_process

    return com_worker_process.main()


def run_agent_python(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    rest = args[1:]
    if rest and rest[0] == AGENT_PYTHON_FLAG:
        rest = rest[1:]
    if not rest:
        print("usage: --agent-python-runner script.py [args...]", file=sys.stderr)
        return 2
    script, *script_args = rest
    sys.argv = [script, *script_args]
    runpy.run_path(script, run_name="__main__")
    return 0
