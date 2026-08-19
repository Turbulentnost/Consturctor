from __future__ import annotations

import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.service_spawn import (
    build_host_command,
    build_launcher_command,
    constructor_root,
    extend_pythonpath,
    is_worker_argv,
)

logger = logging.getLogger(__name__)

DESKTOP_HOST_PORT = 7830
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_host_lock = threading.Lock()
_host_spawn_started = False
_launcher_spawn_started = False


def _spawn_mutex_name(kind: str) -> str:
    return f"Local\\NewConstructor.{kind}.Spawn"


def _try_acquire_spawn_mutex(kind: str) -> bool:
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, _spawn_mutex_name(kind))
        if not handle:
            return True
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        return True
    except Exception:
        return True


def _apply_infra_env(env: dict[str, str], root: Path) -> None:
    """Load IMAP / URL whitelist from .env for unified host :7830."""
    candidates = [
        root / ".env",
        root / "infra" / ".env",
        root.parent / "infra" / ".env",
    ]
    for env_file in candidates:
        if not env_file.is_file():
            continue
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"')
            if (
                key.startswith("IMAP_")
                or key.startswith("ERP_")
                or key.startswith("ONEC_COM_")
                or key.startswith("ODATA_")
                or key in ("USE_STUBS", "URL_WHITELIST", "DATABASE_URL")
            ):
                env.setdefault(key, value)
        return


_DEFAULT_URL_WHITELIST = (
    "localhost,127.0.0.1,example.com,www.example.com,turbo-don.ru,161.ru,ria.ru,don24.ru,donnews.ru,"
    "yandex.ru,ya.ru,google.com,duckduckgo.com,wikipedia.org,ru.wikipedia.org,"
    "en.wikipedia.org,calend.ru,www.calend.ru,vseinstrumenti.ru,rbc.ru,"
    "kommersant.ru,lenta.ru,gazeta.ru,mail.ru,vodokanalrnd.ru,rostov-zkh.ru"
)


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _prepare_host_env(root: Path) -> dict[str, str]:
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["API_PORT"] = str(DESKTOP_HOST_PORT)
    env["USE_STUBS"] = "false"
    env["CONSTRUCTOR_ROOT"] = str(root)
    _apply_infra_env(env, root)
    extend_pythonpath(env, root)
    env.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor",
    )
    env.setdefault("URL_WHITELIST", _DEFAULT_URL_WHITELIST)
    if "FS_ROOT_ALLOWLIST" not in env:
        try:
            from platform_tool_filesystem.desktop_paths import default_fs_allowlist

            env["FS_ROOT_ALLOWLIST"] = default_fs_allowlist(
                repo_data_filesystem=root / "data" / "filesystem"
            )
        except Exception:
            env["FS_ROOT_ALLOWLIST"] = str(root / "data" / "filesystem")
    if "SHELL_CWD_ROOTS" not in env:
        env["SHELL_CWD_ROOTS"] = str(root / "data" / "shell-native")
    return env


def _spawn_process(
    command: list[str],
    *,
    root: Path,
    env: dict[str, str],
    out_path: Path,
    err_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_fh = open(out_path, "a", encoding="utf-8")
    err_fh = open(err_path, "a", encoding="utf-8")
    try:
        subprocess.Popen(
            command,
            cwd=str(root),
            env=env,
            stdout=out_fh,
            stderr=err_fh,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    finally:
        out_fh.close()
        err_fh.close()


def _cleanup_stale_hosts() -> None:
    """Убрать зависший DesktopHost, если порт :7830 свободен."""
    if sys.platform != "win32" or _port_open(DESKTOP_HOST_PORT):
        return
    probe = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq DesktopHost.exe", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    if "DesktopHost.exe" not in probe.stdout:
        return
    subprocess.run(["taskkill", "/IM", "DesktopHost.exe", "/F"], capture_output=True, check=False)
    time.sleep(0.5)


def ensure_desktop_host(*, wait_seconds: float = 25.0) -> bool:
    """Start unified desktop host (:7830). Worker processes never spawn another host."""
    if is_worker_argv():
        return True
    if _port_open(DESKTOP_HOST_PORT):
        logger.info("Desktop host already running on :%s", DESKTOP_HOST_PORT)
        return True

    _cleanup_stale_hosts()

    global _host_spawn_started
    with _host_lock:
        if _host_spawn_started:
            return _wait_for_port(DESKTOP_HOST_PORT, wait_seconds)
        _host_spawn_started = True

    if not _try_acquire_spawn_mutex("DesktopHost"):
        return _wait_for_port(DESKTOP_HOST_PORT, wait_seconds)

    root = constructor_root()
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (root / "data" / "filesystem").mkdir(parents=True, exist_ok=True)
    (root / "data" / "shell-native").mkdir(parents=True, exist_ok=True)
    try:
        from platform_tool_filesystem.main import ensure_fs_workspace

        ensure_fs_workspace(root / "data" / "filesystem")
    except Exception:
        pass

    try:
        command = build_host_command(root=root)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return False

    env = _prepare_host_env(root)
    out_path = logs / "desktop-host.out.log"
    err_path = logs / "desktop-host.err.log"
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/IM", "DesktopHost.exe", "/F"], capture_output=True, check=False)
        time.sleep(0.5)
        if _port_open(DESKTOP_HOST_PORT):
            logger.info("Desktop host already running on :%s", DESKTOP_HOST_PORT)
            return True
    try:
        _spawn_process(command, root=root, env=env, out_path=out_path, err_path=err_path)
    except Exception as exc:
        logger.error("Failed to start desktop host: %s", exc)
        return False

    if _wait_for_port(DESKTOP_HOST_PORT, wait_seconds):
        logger.info("Desktop host started on :%s", DESKTOP_HOST_PORT)
        return True
    logger.error("Desktop host did not become ready; see %s", err_path)
    return False


def ensure_desktop_host_async(*, wait_seconds: float = 30.0) -> None:
    """Non-blocking host start for UI startup."""

    def _run() -> None:
        ensure_desktop_host(wait_seconds=wait_seconds)

    threading.Thread(target=_run, daemon=True, name="desktop-host-start").start()


def ensure_desktop_launcher(*, wait_seconds: float = 15.0) -> bool:
    if is_worker_argv():
        return True
    launcher_port = 7829
    if _port_open(launcher_port):
        return True

    global _launcher_spawn_started
    with _host_lock:
        if _launcher_spawn_started:
            return _wait_for_port(launcher_port, wait_seconds)
        _launcher_spawn_started = True

    if not _try_acquire_spawn_mutex("DesktopLauncher"):
        return _wait_for_port(launcher_port, wait_seconds)

    root = constructor_root()
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["API_PORT"] = str(launcher_port)
    env["CONSTRUCTOR_ROOT"] = str(root)
    extend_pythonpath(env, root)

    try:
        command = build_launcher_command(root=root)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return False

    try:
        _spawn_process(
            command,
            root=root,
            env=env,
            out_path=logs / "desktop-launcher.out.log",
            err_path=logs / "desktop-launcher.err.log",
        )
    except Exception as exc:
        logger.error("Failed to start desktop launcher: %s", exc)
        return False
    return _wait_for_port(launcher_port, wait_seconds)


def ensure_desktop_launcher_async(*, wait_seconds: float = 20.0) -> None:
    def _run() -> None:
        ensure_desktop_launcher(wait_seconds=wait_seconds)

    threading.Thread(target=_run, daemon=True, name="desktop-launcher-start").start()


def _wait_for_port(port: int, wait_seconds: float) -> bool:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.5)
    return False
