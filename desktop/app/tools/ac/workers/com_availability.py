"""Безопасная проверка доступности Windows COM и pywin32."""

import importlib
import importlib.util
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
