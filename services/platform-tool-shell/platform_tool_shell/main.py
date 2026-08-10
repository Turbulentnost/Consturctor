from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app

ALLOWED_COMMANDS = {"python", "pip", "git", "dir", "type", "echo", "where"}
DENY_PATTERNS = (
    re.compile(r"(?i)\brm\b|\bdel\b|\brmdir\b"),
    re.compile(r"(?i)invoke-webrequest|curl\s|wget\s"),
    re.compile(r"[|&;<>]"),
)


class ShellSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-shell"
    api_port: int = 7823
    workspace_root: str = ""
    max_timeout_sec: int = 60
    max_output_bytes: int = 65536


settings = ShellSettings()


def _workspace_root() -> Path:
    root = (settings.workspace_root or os.environ.get("CONSTRUCTOR_WORKSPACE") or "").strip()
    if not root:
        root = str(Path.cwd() / "data" / "workspace")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_dir(run_id: str | None) -> Path:
    base = _workspace_root()
    if run_id:
        path = base / str(run_id)
    else:
        path = base / "default"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_command(command: str) -> list[str]:
    command = command.strip()
    if not command:
        raise ValueError("command required")
    for pattern in DENY_PATTERNS:
        if pattern.search(command):
            raise ValueError("command contains forbidden tokens")
    parts = shlex.split(command, posix=os.name != "nt")
    if not parts:
        raise ValueError("empty command")
    exe = Path(parts[0]).name.lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    if exe not in ALLOWED_COMMANDS:
        raise ValueError(f"command not allowed: {exe}")
    return parts


def _stub_run(req: ToolInvokeRequest) -> dict[str, Any]:
    command = str(req.payload.get("command", "echo stub"))
    return {
        "summary": f"stub: {command}",
        "stdout": f"[stub stdout] {command}\n",
        "stderr": "",
        "exit_code": 0,
    }


def _run(req: ToolInvokeRequest) -> dict[str, Any]:
    command = str(req.payload.get("command", ""))
    parts = _validate_command(command)
    cwd = _run_dir(str(req.run_id) if req.run_id else None)
    timeout = min(int(req.payload.get("timeout", settings.max_timeout_sec)), settings.max_timeout_sec)
    completed = subprocess.run(
        parts,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    stdout = (completed.stdout or "")[: settings.max_output_bytes]
    stderr = (completed.stderr or "")[: settings.max_output_bytes]
    return {
        "summary": f"exit={completed.returncode}",
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": completed.returncode,
        "cwd": str(cwd),
    }


HANDLERS = {"shell.run": _run}
STUB_HANDLERS = {"shell.run": _stub_run}

app = create_tool_app(settings, HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()
