"""Защищенный слой для будущего 1C COMConnector.

Реальное подключение к 1С будет реализовано после уточнения строки подключения,
базы и прав. Модуль не импортирует pywin32 на верхнем уровне.
"""

from __future__ import annotations

import sys

from app.tools.ac.workers.models import WorkerResult, WorkerTask
from app.tools.ac.workers.onec_actions import (
    ensure_onec_readonly_input,
    ensure_onec_readonly_tool,
)

FORBIDDEN_COM_METHOD_PARTS = (
    "write",
    "записать",
    "post",
    "провести",
    "delete",
    "удалить",
    "set_status",
)


def execute_onec_com_readonly(task: WorkerTask) -> WorkerResult:
    """Подготовленный entrypoint будущего read-only COMConnector."""
    try:
        ensure_onec_readonly_tool(task.tool_name)
        ensure_onec_readonly_input(task.input_data)
    except Exception as exc:
        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type="ONEC_READONLY_POLICY_ERROR",
            error_message=str(exc),
        )

    if sys.platform != "win32":
        return _com_not_available(task, "1C COMConnector доступен только на Windows")

    try:
        # Импорт только внутри функции: unit-тесты и non-Windows окружения не
        # должны требовать pywin32.
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except ImportError as exc:
        return _com_not_available(task, f"pywin32 недоступен: {exc}")

    _ = pythoncom
    _ = win32com.client
    return WorkerResult(
        task_id=task.task_id,
        ok=False,
        error_type="ONEC_CONNECTION_ERROR",
        error_message=(
            "Реальное подключение к 1С COMConnector пока не настроено. "
            "Нужны строка подключения, база и read-only права."
        ),
    )


def ensure_no_write_like_method(method_name: str) -> None:
    """Запретить write-like методы COMConnector."""
    normalized = method_name.strip().casefold()
    if any(part in normalized for part in FORBIDDEN_COM_METHOD_PARTS):
        raise ValueError(f"Метод {method_name!r} запрещён read-only политикой 1С")


def _com_not_available(task: WorkerTask, message: str) -> WorkerResult:
    """Вернуть COM_NOT_AVAILABLE."""
    return WorkerResult(
        task_id=task.task_id,
        ok=False,
        error_type="COM_NOT_AVAILABLE",
        error_message=message,
    )

