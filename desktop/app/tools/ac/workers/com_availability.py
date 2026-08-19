"""Безопасная проверка доступности Windows COM и pywin32."""

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys


def is_windows() -> bool:
    """Вернуть True, если приложение запущено на Windows."""
    return sys.platform == "win32"


def is_pywin32_available() -> bool:
    """Безопасно проверить доступность `pythoncom` и `win32com.client`."""
    available, _ = _check_pywin32_availability()
    return available


def get_com_unavailable_reason() -> str:
    """Вернуть понятную причину недоступности COM."""
    if not is_windows():
        return "COM доступен только на Windows с установленным pywin32"

    available, error_message = _check_pywin32_availability()
    if available:
        return "COM доступен"
    if error_message is not None:
        return error_message
    return "pywin32 не установлен или недоступен"


def get_onec_com_unavailable_reason() -> str:
    """Вернуть понятную причину недоступности 1С COMConnector."""
    available, reason = _check_onec_com_availability()
    if available:
        return "1C COMConnector доступен"
    return reason or "1C COMConnector недоступен"


def is_onec_com_available() -> bool:
    """Проверить, достаточно ли окружения для 1C COMConnector."""
    return get_onec_com_unavailable_reason() == "1C COMConnector доступен"


def describe_com_capability() -> dict[str, object]:
    """Собрать краткое описание возможностей COM для передачи в local_run."""
    available, error_message = _check_pywin32_availability()
    outlook_available = is_windows() and available
    onec_available, onec_reason = _check_onec_com_availability()
    return {
        "platform": sys.platform,
        "is_windows": is_windows(),
        "pywin32_available": available,
        "outlook_com_available": outlook_available,
        "outlook_com_reason": "Outlook COM доступен"
        if outlook_available
        else (error_message or get_com_unavailable_reason()),
        "onec_com_available": onec_available,
        "onec_com_reason": "1C COMConnector доступен" if onec_available else onec_reason,
        "com_available": bool(outlook_available or onec_available),
        "com_reason": "COM доступен"
        if (outlook_available or onec_available)
        else (error_message or get_com_unavailable_reason()),
    }


def _check_pywin32_availability() -> tuple[bool, str | None]:
    """Проверить pywin32 без выбрасывания ошибок импорта наружу."""
    try:
        if importlib.util.find_spec("pythoncom") is None:
            return False, "pywin32 не установлен: модуль pythoncom недоступен"
        if importlib.util.find_spec("win32com.client") is None:
            return False, "pywin32 не установлен: модуль win32com.client недоступен"

        importlib.import_module("pythoncom")
        importlib.import_module("win32com.client")
    except ImportError:
        return False, "pywin32 не установлен или недоступен"
    except Exception as exc:
        return False, f"Не удалось проверить доступность pywin32: {exc}"

    return True, None


def _check_onec_com_availability() -> tuple[bool, str | None]:
    """Проверить, что 1С COMConnector инициализируется без ошибки."""
    if not is_windows():
        return False, "1C COMConnector доступен только на Windows"

    available, error_message = _check_pywin32_availability()
    if not available:
        return False, error_message or "pywin32 не установлен или недоступен"

    connection_string = os.environ.get("ONEC_COM_CONNECTION_STRING", "").strip()
    server = os.environ.get("ONEC_COM_SERVER", "").strip()
    ref = os.environ.get("ONEC_COM_REF", "").strip()
    if not connection_string and not (server and ref):
        return (
            False,
            "Не заданы ONEC_COM_CONNECTION_STRING или ONEC_COM_SERVER/ONEC_COM_REF "
            "для 1С COMConnector",
        )

    progid = os.environ.get("ONEC_COM_PROGID", "V83.COMConnector").strip() or "V83.COMConnector"
    try:
        win32com_client = importlib.import_module("win32com.client")
        win32com_client.Dispatch(progid)
    except Exception as exc:  # noqa: BLE001
        helper_available, helper_reason = _check_onec_com_availability_via_helper(progid)
        if helper_available:
            return True, None
        helper_suffix = f". Helper: {helper_reason}" if helper_reason else ""
        return False, f"Не удалось создать COMConnector {progid!r}: {exc}{helper_suffix}"

    return True, None


def _check_onec_com_availability_via_helper(progid: str) -> tuple[bool, str | None]:
    """Проверить COMConnector через 32-bit helper Python, если он доступен."""
    helper = os.environ.get("ONEC_COM_PYTHON", "").strip()
    command: list[str] | None = None
    if helper:
        command = [helper, "-c", _helper_probe_code(progid)]
    elif sys.platform == "win32" and shutil.which("py"):
        command = ["py", "-3.12-32", "-c", _helper_probe_code(progid)]
    if command is None:
        return False, "32-bit helper Python не настроен"
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Helper probe failed: {exc}"
    if completed.returncode == 0:
        return True, None
    stderr = (completed.stderr or completed.stdout or "").strip()
    return False, stderr or f"Helper exit code {completed.returncode}"


def _helper_probe_code(progid: str) -> str:
    return (
        "import importlib\n"
        "client = importlib.import_module('win32com.client')\n"
        f"client.Dispatch({progid!r})\n"
        "print('ok')\n"
    )
