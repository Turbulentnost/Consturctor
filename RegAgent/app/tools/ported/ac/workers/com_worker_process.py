"""Entrypoint дочернего процесса для выполнения COM-задач."""

from __future__ import annotations

import json
import os
import sys
import time

from app.tools.ported.ac.workers.models import WorkerResult, WorkerTask
from app.tools.ported.ac.workers.onec_worker import OneCComWorker
from app.tools.ported.ac.workers.outlook_com_worker import OutlookComWorker

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    """Прочитать WorkerTask из stdin и записать WorkerResult JSON в stdout."""
    raw_input = sys.stdin.read()
    try:
        task = WorkerTask.model_validate_json(raw_input)
    except Exception as exc:
        _write_result(
            WorkerResult(
                task_id="invalid-task",
                ok=False,
                error_type="INVALID_WORKER_TASK",
                error_message=f"Некорректный WorkerTask JSON: {exc}",
            )
        )
        return 0

    result = _execute_task(task)
    _write_result(result)
    return 0


def _execute_task(task: WorkerTask) -> WorkerResult:
    """Маршрутизировать задачу внутри изолированного COM process."""
    if task.tool_name == "test.sleep":
        return _execute_test_sleep(task)

    if task.tool_name.startswith("onec."):
        worker = OneCComWorker()
        return worker.execute(task)

    worker = OutlookComWorker(safe_mode=True, allow_direct_com_calls=True)
    return worker.execute(task)


def _execute_test_sleep(task: WorkerTask) -> WorkerResult:
    """Тестовый route для проверки timeout, доступный только по env-флагу."""
    if os.environ.get("ENABLE_TEST_WORKER_TOOLS") != "1":
        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type="UNKNOWN_COM_TOOL",
            error_message="Неизвестный COM tool_name",
        )

    sleep_seconds = float(task.input_data.get("sleep_seconds", 0))
    print(
        f"[COM_DIAG] step=test_sleep seconds={sleep_seconds}",
        file=sys.stderr,
        flush=True,
    )
    time.sleep(sleep_seconds)
    return WorkerResult(
        task_id=task.task_id,
        ok=True,
        output_data={"slept": sleep_seconds},
    )


def _write_result(result: WorkerResult) -> None:
    """Записать WorkerResult в stdout как единственный JSON payload."""
    sys.stdout.write(result.model_dump_json())
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
