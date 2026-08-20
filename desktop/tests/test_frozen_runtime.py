from __future__ import annotations

from pathlib import Path

from app.frozen_runtime import (
    COM_WORKER_EXE_NAME,
    agent_python_command,
    com_worker_command,
    desktop_root,
    entry_mode,
    run_agent_python,
)
from app.tools.ac.code_execution_tools import _python_command_prefix
from app.tools.ac.workers.subprocess_com_worker import _build_worker_command


def test_entry_mode_flags() -> None:
    assert entry_mode(["main.py"]) == "gui"
    assert entry_mode(["ConstructorDesktop.exe", "--com-worker"]) == "com-worker"
    assert entry_mode(["ConstructorDesktop.exe", "--agent-python-runner", "x.py"]) == (
        "agent-python"
    )


def test_entry_mode_sibling_exe_name() -> None:
    assert (
        entry_mode(
            [COM_WORKER_EXE_NAME],
            frozen=True,
            executable=rf"C:\app\{COM_WORKER_EXE_NAME}",
        )
        == "com-worker"
    )
    assert (
        entry_mode(
            ["ConstructorDesktop.exe"],
            frozen=True,
            executable=r"C:\app\ConstructorDesktop.exe",
        )
        == "gui"
    )


def test_com_worker_command_uses_sibling_when_present(tmp_path: Path) -> None:
    gui = tmp_path / "ConstructorDesktop.exe"
    sibling = tmp_path / COM_WORKER_EXE_NAME
    gui.write_bytes(b"x")
    sibling.write_bytes(b"x")
    assert com_worker_command(str(gui), "app.tools.ac.workers.com_worker_process", frozen=True) == [
        str(sibling)
    ]


def test_com_worker_command_falls_back_to_flag(tmp_path: Path) -> None:
    gui = tmp_path / "ConstructorDesktop.exe"
    gui.write_bytes(b"x")
    assert com_worker_command(str(gui), "mod", frozen=True) == [str(gui), "--com-worker"]
    assert com_worker_command("python", "mod", frozen=False) == ["python", "-m", "mod"]


def test_agent_python_command_uses_console_sibling(tmp_path: Path) -> None:
    gui = tmp_path / "ConstructorDesktop.exe"
    sibling = tmp_path / COM_WORKER_EXE_NAME
    gui.write_bytes(b"x")
    sibling.write_bytes(b"x")
    assert agent_python_command(str(gui), frozen=True) == [str(sibling), "--agent-python-runner"]
    assert agent_python_command("python", frozen=False) == ["python"]


def test_desktop_root_frozen_is_exe_dir(tmp_path: Path) -> None:
    exe = tmp_path / "ConstructorDesktop.exe"
    exe.write_bytes(b"x")
    assert desktop_root(frozen=True, executable=str(exe)) == tmp_path


def test_build_worker_command_unfrozen() -> None:
    command = _build_worker_command("app.tools.ac.workers.com_worker_process")
    assert command[-2:] == ["-m", "app.tools.ac.workers.com_worker_process"]


def test_python_prefix_unfrozen() -> None:
    prefix = _python_command_prefix()
    assert prefix
    assert "--agent-python-runner" not in prefix


def test_run_agent_python_executes_script(tmp_path: Path, capsys) -> None:
    script = tmp_path / "hello.py"
    script.write_text("print('ok-from-runner')\n", encoding="utf-8")
    code = run_agent_python(["worker.exe", "--agent-python-runner", str(script)])
    assert code == 0
    assert "ok-from-runner" in capsys.readouterr().out


def test_spec_is_onedir_with_com_worker() -> None:
    spec = Path(__file__).resolve().parents[1] / "NewConstructor.spec"
    text = spec.read_text(encoding="utf-8")
    assert "exclude_binaries=True" in text
    assert "COLLECT(" in text
    assert 'name="ConstructorDesktop"' in text
    assert 'name="ConstructorComWorker"' in text
    assert "console=True" in text
    assert "ERP_PASSWORD" not in text
    assert "console=False" in text
    assert '"torch"' in text or "'torch'" in text
    assert "collect_all" not in text
