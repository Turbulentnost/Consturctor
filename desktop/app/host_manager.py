from __future__ import annotations

import logging
import socket
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DESKTOP_HOST_PORT = 7830
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def constructor_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _apply_infra_env(env: dict[str, str]) -> None:
    """Load IMAP / URL whitelist from infra/.env for unified host :7830."""
    env_file = constructor_root() / "infra" / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key.startswith("IMAP_") or key in ("USE_STUBS", "URL_WHITELIST", "DATABASE_URL"):
            env.setdefault(key, value)


_DEFAULT_URL_WHITELIST = (
    "localhost,127.0.0.1,turbo-don.ru,161.ru,ria.ru,don24.ru,donnews.ru,"
    "yandex.ru,ya.ru,google.com,duckduckgo.com,wikipedia.org,ru.wikipedia.org,"
    "en.wikipedia.org,calend.ru,www.calend.ru,vseinstrumenti.ru,rbc.ru,"
    "kommersant.ru,lenta.ru,gazeta.ru,mail.ru,vodokanalrnd.ru,rostov-zkh.ru"
)


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def ensure_desktop_host(*, wait_seconds: float = 25.0) -> bool:
    """Start unified desktop host (:7830) in background when turbobot app launches."""
    if _port_open(DESKTOP_HOST_PORT):
        logger.info("Desktop host already running on :%s", DESKTOP_HOST_PORT)
        return True

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

    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["API_PORT"] = str(DESKTOP_HOST_PORT)
    env["USE_STUBS"] = "false"
    env["CONSTRUCTOR_ROOT"] = str(root)
    _apply_infra_env(env)
    env.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor",
    )
    env.setdefault("URL_WHITELIST", _DEFAULT_URL_WHITELIST)
    if "FS_ROOT_ALLOWLIST" not in env:
        env["FS_ROOT_ALLOWLIST"] = str(root / "data" / "filesystem")
    if "SHELL_CWD_ROOTS" not in env:
        env["SHELL_CWD_ROOTS"] = str(root / "data" / "shell-native")

    out_path = logs / "desktop-host.out.log"
    err_path = logs / "desktop-host.err.log"
    try:
        out_fh = open(out_path, "a", encoding="utf-8")
        err_fh = open(err_path, "a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, "-m", "platform_desktop_host.main"],
            cwd=str(root),
            env=env,
            stdout=out_fh,
            stderr=err_fh,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out_fh.close()
        err_fh.close()
    except Exception as exc:
        logger.error("Failed to start desktop host: %s", exc)
        return False

    import time

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _port_open(DESKTOP_HOST_PORT):
            logger.info("Desktop host started on :%s", DESKTOP_HOST_PORT)
            return True
        time.sleep(0.5)
    logger.error("Desktop host did not become ready; see %s", err_path)
    return False


def ensure_desktop_launcher(*, wait_seconds: float = 15.0) -> bool:
    """Start launcher (:7829) so Docker orchestrator can lazy-start host when app is open."""
    launcher_port = 7829
    if _port_open(launcher_port):
        return True
    root = constructor_root()
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["API_PORT"] = str(launcher_port)
    env["CONSTRUCTOR_ROOT"] = str(root)
    try:
        subprocess.Popen(
            [sys.executable, "-m", "platform_desktop_launcher.main"],
            cwd=str(root),
            env=env,
            stdout=open(logs / "desktop-launcher.out.log", "a", encoding="utf-8"),
            stderr=open(logs / "desktop-launcher.err.log", "a", encoding="utf-8"),
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception as exc:
        logger.error("Failed to start desktop launcher: %s", exc)
        return False
    import time

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _port_open(launcher_port):
            return True
        time.sleep(0.5)
    return False
