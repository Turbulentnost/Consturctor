"""Worker-обёртка, изолирующая COM-вызовы в отдельном Python-процессе."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from pydantic import ValidationError

from app.frozen_runtime import com_worker_command, desktop_root
from app.tools.ac.workers.base import BaseWorker
from app.tools.ac.workers.models import WorkerResult, WorkerTask


class SubprocessComWorker(BaseWorker):
    """Запускает COM-задачи в subprocess и защищает основной процесс timeout-ом."""

    _live: list[SubprocessComWorker] = []

    def __init__(self, module_name: str | None = None) -> None:
        """Создать subprocess worker для указанного entrypoint-модуля."""
        self._module_name = (
            module_name or "app.tools.ac.workers.com_worker_process"
        )
        self._proc_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False
        SubprocessComWorker._live.append(self)

    def cancel(self) -> bool:
        """Остановить текущий COM subprocess после Skip."""
        self._cancelled = True
        with self._proc_lock:
            proc = self._process
        if proc is None or proc.poll() is not None:
            return False
        try:
            proc.kill()
        except OSError:
            return False
        return True

    @classmethod
    def cancel_all(cls) -> None:
        """Остановить все живые COM subprocess после Skip."""
        for worker in list(cls._live):
            worker.cancel()

    def execute(self, task: WorkerTask) -> WorkerResult:
        """Выполнить WorkerTask в дочернем процессе и вернуть WorkerResult."""
        self._cancelled = False
        command = _build_worker_command(self._module_name)
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=_desktop_root(),
                env=_worker_env(),
                **_hidden_run_kwargs(),
            )
        except Exception as exc:
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="WORKER_PROCESS_ERROR",
                error_message=str(exc),
            )

        with self._proc_lock:
            self._process = proc
        if self._cancelled:
            try:
                proc.kill()
            except OSError:
                pass
            return self._cancelled_result(task.task_id)
        stdout = ""
        stderr = ""
        try:
            stdout, stderr = proc.communicate(
                input=task.model_dump_json(),
                timeout=task.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                leftover_out, leftover_err = proc.communicate(timeout=5)
            except Exception:
                leftover_out, leftover_err = "", ""
            details = f"COM worker не ответил за {task.timeout_seconds} секунд"
            extra = _safe_process_text(leftover_err)
            if extra:
                details += f". Последний stderr: {extra.strip()}"
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="WORKER_TIMEOUT",
                error_message=details,
            )
        except Exception as exc:
            try:
                proc.kill()
            except OSError:
                pass
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="WORKER_PROCESS_ERROR",
                error_message=str(exc),
            )
        finally:
            with self._proc_lock:
                if self._process is proc:
                    self._process = None

        if self._cancelled:
            return self._cancelled_result(task.task_id)

        parsed_result = _parse_worker_result(task.task_id, stdout)
        if parsed_result is not None:
            return parsed_result

        if proc.returncode != 0:
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="WORKER_PROCESS_ERROR",
                error_message=_build_process_error_message(stderr),
            )

        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type="INVALID_WORKER_RESPONSE",
            error_message="COM worker вернул невалидный JSON в stdout",
        )

    @staticmethod
    def _cancelled_result(task_id: str) -> WorkerResult:
        return WorkerResult(
            task_id=task_id,
            ok=False,
            error_type="WORKER_CANCELLED",
            error_message="COM worker stopped because the user skipped the tool",
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
