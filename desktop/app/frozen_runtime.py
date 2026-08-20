"""Режимы запуска frozen exe: GUI, COM-worker, runner Python-кода агента."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

COM_WORKER_FLAG = "--com-worker"
AGENT_PYTHON_FLAG = "--agent-python-runner"
COM_WORKER_EXE_NAME = "ConstructorComWorker.exe"


def entry_mode(
    argv: list[str] | None = None,
    *,
    frozen: bool | None = None,
    executable: str | None = None,
) -> str:
    """Определить режим: gui / com-worker / agent-python."""
    args = list(sys.argv if argv is None else argv)
    rest = args[1:]
    if rest and rest[0] == COM_WORKER_FLAG:
        return "com-worker"
    if rest and rest[0] == AGENT_PYTHON_FLAG:
        return "agent-python"
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = sys.executable if executable is None else executable
    if is_frozen and Path(exe).stem.casefold() == Path(COM_WORKER_EXE_NAME).stem.casefold():
        return "com-worker"
    return "gui"


def desktop_root(*, frozen: bool | None = None, executable: str | None = None) -> Path:
    """Корень desktop: рядом с exe в frozen, иначе папка desktop из исходников."""
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if is_frozen:
        exe = sys.executable if executable is None else executable
        return Path(exe).resolve().parent
    return Path(__file__).resolve().parents[1]


def com_worker_command(
    executable: str,
    module_name: str,
    *,
    frozen: bool,
) -> list[str]:
    """Команда COM-worker: консольный sibling-exe в frozen, иначе python -m."""
    if not frozen:
        return [executable, "-m", module_name]
    sibling = Path(executable).resolve().parent / COM_WORKER_EXE_NAME
    if sibling.is_file():
        return [str(sibling)]
    return [executable, COM_WORKER_FLAG]


def agent_python_command(executable: str, *, frozen: bool) -> list[str] | None:
    """Команда запуска .py агента: в frozen — консольный sibling с runner-флагом."""
    if not frozen:
        return [executable] if executable else None
    sibling = Path(executable).resolve().parent / COM_WORKER_EXE_NAME
    if sibling.is_file():
        return [str(sibling), AGENT_PYTHON_FLAG]
    if executable:
        return [executable, AGENT_PYTHON_FLAG]
    return None


def run_agent_python(argv: list[str] | None = None) -> int:
    """Выполнить скрипт агента через встроенный runtime PyInstaller."""
    args = list(sys.argv if argv is None else argv)
    rest = args[1:]
    if rest and rest[0] == AGENT_PYTHON_FLAG:
        rest = rest[1:]
    if not rest:
        sys.stderr.write("Нужен путь к скрипту для --agent-python-runner\n")
        return 2
    script, *script_args = rest
    sys.argv = [script, *script_args]
    runpy.run_path(script, run_name="__main__")
    return 0


def run_com_worker() -> int:
    """Запустить stdin/stdout COM-worker без Qt."""
    from app.tools.ac.workers.com_worker_process import main as com_main

    return int(com_main() or 0)
