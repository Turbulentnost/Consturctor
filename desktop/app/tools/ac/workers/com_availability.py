"""Безопасная проверка доступности Windows COM и pywin32."""

from __future__ import annotations

import functools
import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ONEC_COM_RUNTIME_CSCRIPT32 = "cscript32"
ONEC_COM_RUNTIME_INPROC = "inproc"


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
    available, reason, _runtime = _check_onec_com_availability()
    if available:
        return "1C COMConnector доступен"
    return reason or "1C COMConnector недоступен"


def is_onec_com_available() -> bool:
    """Проверить, достаточно ли окружения для 1C COMConnector."""
    return get_onec_com_unavailable_reason() == "1C COMConnector доступен"


def onec_com_runtime() -> str:
    """Как ходить в 1С: cscript32 (основной) или inproc. Пусто — недоступно."""
    available, _reason, runtime = _check_onec_com_availability()
    return runtime if available else ""


def reset_onec_com_availability_cache() -> None:
    """Сбросить кэш проверки — для тестов и смены .env."""
    _check_onec_com_availability.cache_clear()


def prefers_com32() -> bool:
    """64-bit Python здесь не видит V83.COMConnector — нужен SysWOW64 cscript."""
    return onec_com_runtime() == ONEC_COM_RUNTIME_CSCRIPT32


def describe_com_capability() -> dict[str, object]:
    """Собрать краткое описание возможностей COM для передачи в local_run."""
    available, error_message = _check_pywin32_availability()
    outlook_available = is_windows() and available
    onec_available, onec_reason, onec_runtime = _check_onec_com_availability()
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
        "onec_com_runtime": onec_runtime if onec_available else "",
        "com_available": bool(outlook_available or onec_available),
        "com_reason": "COM доступен"
        if (outlook_available or onec_available)
        else (error_message or get_com_unavailable_reason()),
    }


def pywin32_dll_dirs() -> list[str]:
    """Каталоги с pythoncom/pywintypes DLL — после установщика они не в System32."""
    dirs: list[str] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        try:
            resolved = str(path.resolve())
        except OSError:
            return
        if not path.is_dir() or resolved in seen:
            return
        seen.add(resolved)
        dirs.append(resolved)

    prefixes = [Path(sys.prefix), Path(sys.exec_prefix)]
    try:
        import site

        prefixes.extend(Path(item) for item in site.getsitepackages())
        user = site.getusersitepackages()
        if user:
            prefixes.append(Path(user))
    except Exception:
        pass
    prefixes.append(Path(sys.prefix) / "Lib" / "site-packages")
    for base in prefixes:
        _add(base / "pywin32_system32")
        _add(base / "win32")
        _add(base / "Lib" / "site-packages" / "pywin32_system32")
        _add(base / "Lib" / "site-packages" / "win32")
    return dirs


def ensure_pywin32_dll_path() -> None:
    """Добавить pywin32 DLL в PATH — иначе embedded Python после установщика не грузит COM."""
    extras = pywin32_dll_dirs()
    if not extras:
        return
    if hasattr(os, "add_dll_directory"):
        for item in extras:
            try:
                os.add_dll_directory(item)
            except (OSError, FileNotFoundError):
                pass
    current = os.environ.get("PATH", "")
    prefix = os.pathsep.join(extras)
    if prefix and prefix not in current:
        os.environ["PATH"] = prefix if not current else f"{prefix}{os.pathsep}{current}"


def _check_pywin32_availability() -> tuple[bool, str | None]:
    """Проверить pywin32 без выбрасывания ошибок импорта наружу."""
    try:
        ensure_pywin32_dll_path()
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


def _has_onec_connection_env() -> bool:
    connection_string = os.environ.get("ONEC_COM_CONNECTION_STRING", "").strip()
    server = os.environ.get("ONEC_COM_SERVER", "").strip()
    ref = os.environ.get("ONEC_COM_REF", "").strip()
    return bool(connection_string or (server and ref))


@functools.lru_cache(maxsize=1)
def _check_onec_com_availability() -> tuple[bool, str | None, str]:
    """Доступность 1С COM: сначала 32-bit cscript, не py -3.12-32."""
    if not is_windows():
        return False, "1C COMConnector доступен только на Windows", ""

    if not _has_onec_connection_env():
        return (
            False,
            "Не заданы ONEC_COM_CONNECTION_STRING или ONEC_COM_SERVER/ONEC_COM_REF "
            "для 1С COMConnector",
            "",
        )

    from app.tools.ac.workers.onec_com32_helper import is_com32_available

    com32_ok, com32_reason = is_com32_available()
    if com32_ok:
        return True, None, ONEC_COM_RUNTIME_CSCRIPT32

    progid = os.environ.get("ONEC_COM_PROGID", "V83.COMConnector").strip() or "V83.COMConnector"
    pywin32_ok, pywin32_error = _check_pywin32_availability()
    if pywin32_ok:
        try:
            win32com_client = importlib.import_module("win32com.client")
            win32com_client.Dispatch(progid)
            return True, None, ONEC_COM_RUNTIME_INPROC
        except Exception as exc:  # noqa: BLE001
            dispatch_error = str(exc)
    else:
        dispatch_error = pywin32_error or "pywin32 недоступен"

    helper_available, helper_reason = _check_explicit_python32(progid)
    if helper_available:
        return True, None, "python32"

    helper_suffix = f". Helper: {helper_reason}" if helper_reason else ""
    com32_suffix = f". 32-bit: {com32_reason}" if com32_reason else ""
    return (
        False,
        f"Не удалось создать COMConnector {progid!r}: {dispatch_error}{helper_suffix}{com32_suffix}",
        "",
    )


def _check_explicit_python32(progid: str) -> tuple[bool, str | None]:
    """Только если явно задан ONEC_COM_PYTHON. py -3.12-32 больше не вызываем."""
    helper = os.environ.get("ONEC_COM_PYTHON", "").strip()
    if not helper:
        return False, None
    try:
        completed = subprocess.run(
            [helper, "-c", _helper_probe_code(progid)],
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
