"""Worker-обёртка, изолирующая COM-вызовы в отдельном Python-процессе."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from app.frozen_runtime import com_worker_command, desktop_root
from app.tools.ported.ac.workers.base import BaseWorker
from app.tools.ported.ac.workers.models import WorkerResult, WorkerTask


class SubprocessComWorker(BaseWorker):
    """Запускает COM-задачи в subprocess и защищает основной процесс timeout-ом."""

    def __init__(self, module_name: str | None = None) -> None:
        """Создать subprocess worker для указанного entrypoint-модуля."""
        self._module_name = (
            module_name or "app.tools.ported.ac.workers.com_worker_process"
        )

    def execute(self, task: WorkerTask) -> WorkerResult:
        """Выполнить WorkerTask в дочернем процессе и вернуть WorkerResult."""
        command = _build_worker_command(self._module_name)
        try:
            completed = subprocess.run(
                command,
                input=task.model_dump_json(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=task.timeout_seconds,
                check=False,
                cwd=_desktop_root(),
                env=_worker_env(),
                **_hidden_run_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            stderr = _safe_process_text(exc.stderr)
            details = f"COM worker не ответил за {task.timeout_seconds} секунд"
            if stderr:
                details += f". Последний stderr: {stderr.strip()}"
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="WORKER_TIMEOUT",
                error_message=details,
            )
        except Exception as exc:
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="WORKER_PROCESS_ERROR",
                error_message=str(exc),
            )

        parsed_result = _parse_worker_result(task.task_id, completed.stdout)
        if parsed_result is not None:
            return parsed_result

        if completed.returncode != 0:
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="WORKER_PROCESS_ERROR",
                error_message=_build_process_error_message(completed.stderr),
            )

        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type="INVALID_WORKER_RESPONSE",
            error_message="COM worker вернул невалидный JSON в stdout",
        )


def _parse_worker_result(task_id: str, stdout: str) -> WorkerResult | None:
    """Попытаться распарсить stdout дочернего процесса как WorkerResult."""
    try:
        return WorkerResult.model_validate_json(stdout)
    except (ValueError, ValidationError):
        return None


def _desktop_root() -> Path:
    return desktop_root()


def _worker_env() -> dict[str, str]:
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        return env
    desktop = str(_desktop_root())
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = desktop if not current else f"{desktop}{os.pathsep}{current}"
    return env


def _hidden_run_kwargs() -> dict:
    """Keep the COM worker from flashing a console window on Windows."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _build_worker_command(module_name: str) -> list[str]:
    """Собрать команду запуска COM-worker для обычного Python и frozen exe."""
    return com_worker_command(
        sys.executable,
        module_name,
        frozen=bool(getattr(sys, "frozen", False)),
    )


def _build_process_error_message(stderr: str) -> str:
    """Собрать понятное сообщение об ошибке дочернего процесса."""
    if stderr.strip():
        return stderr.strip()
    return "COM worker process завершился с ошибкой без stderr"


def _safe_process_text(value: str | bytes | None) -> str:
    """Безопасно привести stdout/stderr из subprocess exception к строке."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
