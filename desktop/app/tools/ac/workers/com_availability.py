"""Безопасная проверка доступности Windows COM и pywin32."""

import importlib
import importlib.util
import os
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
    if not is_windows():
        return "1C COMConnector доступен только на Windows"

    available, error_message = _check_pywin32_availability()
    if not available:
        return error_message or "pywin32 не установлен или недоступен"

    connection_string = os.environ.get("ONEC_COM_CONNECTION_STRING", "").strip()
    server = os.environ.get("ONEC_COM_SERVER", "").strip()
    ref = os.environ.get("ONEC_COM_REF", "").strip()
    if not connection_string and not (server and ref):
        return (
            "Не заданы ONEC_COM_CONNECTION_STRING или ONEC_COM_SERVER/ONEC_COM_REF "
            "для 1С COMConnector"
        )

    return "1C COMConnector доступен"


def is_onec_com_available() -> bool:
    """Проверить, достаточно ли окружения для 1C COMConnector."""
    return get_onec_com_unavailable_reason() == "1C COMConnector доступен"


def describe_com_capability() -> dict[str, object]:
    """Собрать краткое описание возможностей COM для передачи в local_run."""
    available, error_message = _check_pywin32_availability()
    outlook_available = is_windows() and available
    onec_available = is_onec_com_available()
    return {
        "platform": sys.platform,
        "is_windows": is_windows(),
        "pywin32_available": available,
        "outlook_com_available": outlook_available,
        "outlook_com_reason": "Outlook COM доступен"
        if outlook_available
        else (error_message or get_com_unavailable_reason()),
        "onec_com_available": onec_available,
        "onec_com_reason": get_onec_com_unavailable_reason(),
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
