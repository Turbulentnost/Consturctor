from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DESKTOP_HOST_PORT = 7830


@dataclass(frozen=True)
class DesktopServiceSpec:
    tag: str
    port: int
    module: str
    extra_env: dict[str, str]


def repo_root() -> Path:
    raw = (os.environ.get("CONSTRUCTOR_ROOT") or "").strip()
    if raw:
        return Path(raw).resolve()
    return Path(__file__).resolve().parents[3]


def load_specs(root: Path) -> dict[int, DesktopServiceSpec]:
    fs_allow = os.environ.get("FS_ROOT_ALLOWLIST") or str(root / "data" / "filesystem")
    shell_roots = os.environ.get("SHELL_CWD_ROOTS") or str(root / "data" / "shell-native")
    return {
        DESKTOP_HOST_PORT: DesktopServiceSpec(
            "host",
            DESKTOP_HOST_PORT,
            "platform_desktop_host.main",
            {
                "FS_ROOT_ALLOWLIST": fs_allow,
                "SHELL_CWD_ROOTS": shell_roots,
            },
        ),
    }


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def resolve_port(*, port: int | None, tool_name: str | None, specs: dict[int, DesktopServiceSpec]) -> int:
    if port is not None:
        if port in specs:
            return port
        if port in {7826, 7827, 7828}:
            return DESKTOP_HOST_PORT
        raise ValueError(f"Unknown desktop port: {port}")
    name = (tool_name or "").strip()
    if name.startswith(("com.", "fs.", "desktop.")):
        return DESKTOP_HOST_PORT
    if name.startswith("shell."):
        return DESKTOP_HOST_PORT
    raise ValueError("Provide port or a desktop tool_name (com.*, fs.*, shell.*, desktop.*)")


def ensure_desktop_service(
    *,
    port: int,
    wait_seconds: float = 30.0,
    poll_seconds: float = 0.5,
) -> dict[str, object]:
    root = repo_root()
    specs = load_specs(root)
    target_port = DESKTOP_HOST_PORT if port in {7826, 7827, 7828, DESKTOP_HOST_PORT} else port
    spec = specs[DESKTOP_HOST_PORT]
    if port_open(spec.port):
        return {
            "ok": True,
            "port": spec.port,
            "service": spec.tag,
            "started": False,
            "message": f"desktop host already listening on {spec.port}",
        }

    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (root / "data" / "filesystem").mkdir(parents=True, exist_ok=True)
    (root / "data" / "shell-native").mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["API_PORT"] = str(spec.port)
    # Honor platform USE_STUBS (infra/.env) so sandbox/demo does not hang on real Outlook COM.
    env["USE_STUBS"] = (os.environ.get("USE_STUBS") or "false").strip().lower() or "false"
    env["CONSTRUCTOR_ROOT"] = str(root)
    env.update(spec.extra_env)

    out_path = logs / "desktop-host.out.log"
    err_path = logs / "desktop-host.err.log"
    out_fh = open(out_path, "a", encoding="utf-8")
    err_fh = open(err_path, "a", encoding="utf-8")
    try:
        subprocess.Popen(
            [sys.executable, "-m", spec.module],
            cwd=str(root),
            env=env,
            stdout=out_fh,
            stderr=err_fh,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception:
        out_fh.close()
        err_fh.close()
        raise
    out_fh.close()
    err_fh.close()

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if port_open(spec.port):
            return {
                "ok": True,
                "port": spec.port,
                "service": spec.tag,
                "started": True,
                "message": f"started unified desktop host on port {spec.port}",
            }
        time.sleep(poll_seconds)

    return {
        "ok": False,
        "port": spec.port,
        "service": spec.tag,
        "started": False,
        "message": f"timeout waiting for desktop host :{spec.port}; see logs/desktop-host.err.log",
    }
