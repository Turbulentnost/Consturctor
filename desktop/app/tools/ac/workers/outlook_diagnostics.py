"""Пошаговая диагностика Outlook COM/MAPI."""

from __future__ import annotations

from typing import Any

from app.tools.ac.workers import com_availability
from app.tools.ac.workers.outlook_com_actions import (
    _load_pywin32_modules,
    _log_progress,
)


def run_outlook_diagnostics(input_data: dict) -> dict:
    """Проверить Outlook COM по шагам и вернуть структурированный отчёт."""
    steps: list[dict] = []
    recommendations: list[str] = []
    pythoncom = None
    com_initialized = False

    if not _run_step(
        steps,
        "check_windows",
        lambda: _check_windows_step(),
        "Windows доступен",
    ):
        recommendations.append("Запустите проверку на Windows-компьютере.")
        return _diagnostics_result(False, steps, recommendations)

    try:
        _log_progress("step=load_pywin32 start")
        pythoncom, win32com_client = _load_pywin32_modules()
        _add_ok_step(steps, "load_pywin32", "pywin32 загружен")
        _log_progress("step=load_pywin32 ok")
    except Exception as exc:
        _add_error_step(steps, "load_pywin32", exc)
        recommendations.append("Установите pywin32 в активное окружение проекта.")
        return _diagnostics_result(False, steps, recommendations)

    try:
        _log_progress("step=co_initialize start")
        pythoncom.CoInitialize()
        com_initialized = True
        _add_ok_step(steps, "co_initialize", "COM инициализирован")
        _log_progress("step=co_initialize ok")

        _log_progress("step=dispatch_outlook start")
        outlook = win32com_client.Dispatch("Outlook.Application")
        _add_ok_step(steps, "dispatch_outlook", "Outlook.Application получен")
        _log_progress("step=dispatch_outlook ok")

        _log_progress("step=get_namespace start")
        namespace = outlook.GetNamespace("MAPI")
        _add_ok_step(steps, "get_namespace", "MAPI namespace получен")
        _log_progress("step=get_namespace ok")

        _log_progress("step=get_inbox start")
        inbox = namespace.GetDefaultFolder(6)
        _add_ok_step(steps, "get_inbox", "Inbox получен")
        _log_progress("step=get_inbox ok")

        _log_progress("step=get_calendar start")
        calendar = namespace.GetDefaultFolder(9)
        _add_ok_step(steps, "get_calendar", "Calendar получен")
        _log_progress("step=get_calendar ok")

        _log_progress("step=get_inbox_items_count_safe start")
        inbox_count = inbox.Items.Count
        _add_ok_step(
            steps,
            "get_inbox_items_count_safe",
            f"Inbox items count: {inbox_count}",
        )
        _log_progress("step=get_inbox_items_count_safe ok")

        _log_progress("step=get_calendar_items_count_safe start")
        calendar_count = calendar.Items.Count
        _add_ok_step(
            steps,
            "get_calendar_items_count_safe",
            f"Calendar items count: {calendar_count}",
        )
        _log_progress("step=get_calendar_items_count_safe ok")

        recommendations.append("Outlook COM/MAPI отвечает на базовые read-only вызовы.")
        return _diagnostics_result(True, steps, recommendations)
    except Exception as exc:
        step_name = _last_started_step_from_stderr_context(steps)
        _add_error_step(steps, step_name, exc)
        recommendations.extend(
            [
                "Откройте Outlook вручную и закройте модальные окна.",
                "Проверьте, что профиль Outlook настроен и календарь виден.",
            ]
        )
        return _diagnostics_result(False, steps, recommendations)
    finally:
        if com_initialized and pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _check_windows_step() -> None:
    """Проверить Windows без импорта pywin32."""
    if not com_availability.is_windows():
        raise RuntimeError("COM доступен только на Windows")


def _run_step(
    steps: list[dict],
    step_name: str,
    action,
    ok_message: str,
) -> bool:
    """Выполнить простой диагностический шаг."""
    try:
        _log_progress(f"step={step_name} start")
        action()
        _add_ok_step(steps, step_name, ok_message)
        _log_progress(f"step={step_name} ok")
        return True
    except Exception as exc:
        _add_error_step(steps, step_name, exc)
        _log_progress(f"step={step_name} error")
        return False


def _add_ok_step(steps: list[dict], step_name: str, message: str) -> None:
    """Добавить успешный шаг диагностики."""
    steps.append({"step": step_name, "ok": True, "message": message})


def _add_error_step(steps: list[dict], step_name: str, exc: Exception) -> None:
    """Добавить ошибочный шаг диагностики."""
    steps.append(
        {
            "step": step_name,
            "ok": False,
            "message": str(exc),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    )


def _diagnostics_result(
    ok: bool,
    steps: list[dict],
    recommendations: list[str],
) -> dict:
    """Собрать payload диагностики."""
    return {
        "diagnostics": {
            "ok": ok,
            "steps": steps,
            "recommendations": recommendations,
        }
    }


def _last_started_step_from_stderr_context(steps: list[dict[str, Any]]) -> str:
    """Вернуть следующий ожидаемый шаг для ошибки внутри последовательного блока."""
    if not steps:
        return "unknown"
    last_step = steps[-1]["step"]
    order = [
        "co_initialize",
        "dispatch_outlook",
        "get_namespace",
        "get_inbox",
        "get_calendar",
        "get_inbox_items_count_safe",
        "get_calendar_items_count_safe",
    ]
    try:
        return order[order.index(last_step) + 1]
    except (ValueError, IndexError):
        return last_step
