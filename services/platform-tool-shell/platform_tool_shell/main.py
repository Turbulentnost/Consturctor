from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app

ALLOWED_COMMANDS = {
    "python",
    "pip",
    "git",
    "dir",
    "type",
    "echo",
    "where",
    "ls",
    "cd",
    "pwd",
    "cat",
    "head",
    "tail",
    "find",
    "test",
    "true",
    "false",
}
SHELL_DENY_PATTERNS = (
    re.compile(r"(?i)\brm\b|\bdel\b|\brmdir\b|\bmkfs\b"),
    re.compile(r"(?i)\bcurl\b|\bwget\b|\bnc\b|\bssh\b|\bsudo\b|\bchmod\b|\bchown\b"),
    re.compile(r"(?i)invoke-webrequest"),
    re.compile(r"(?i)\bpowershell\b|\bpwsh\b|\.ps1\b"),
    re.compile(r"\$\("),
    re.compile(r"[<>]"),
)
_SINGLE_PIPE = re.compile(r"(?<!\|)\|(?!|\|)")
_SANDBOX_DIRS = ("incoming", "outgoing", "attachments")


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


def _ensure_sandbox_layout(cwd: Path) -> None:
    cwd.mkdir(parents=True, exist_ok=True)
    for name in _SANDBOX_DIRS:
        (cwd / name).mkdir(exist_ok=True)
    readme = cwd / "README.txt"
    if not readme.exists():
        readme.write_text("Constructor sandbox workspace\n", encoding="utf-8")


def _validate_shell_command(command: str) -> str:
    command = command.strip()
    if not command:
        raise ValueError("command required")
    for pattern in SHELL_DENY_PATTERNS:
        if pattern.search(command):
            raise ValueError("command contains forbidden tokens")
    if _SINGLE_PIPE.search(command):
        raise ValueError("pipe not allowed")
    for segment in re.split(r"\|\||&&", command):
        segment = segment.strip()
        if not segment:
            continue
        head = re.match(r"^([A-Za-z][\w.-]*)", segment)
        if not head:
            raise ValueError("invalid command segment")
        name = head.group(1).lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name not in ALLOWED_COMMANDS:
            raise ValueError(f"command not allowed: {head.group(1)}")
    return command


def _execute(command: str, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    _ensure_sandbox_layout(cwd)
    validated = _validate_shell_command(command)
    if os.name == "nt":
        return subprocess.run(
            ["cmd.exe", "/c", validated],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    return subprocess.run(
        ["/bin/sh", "-c", validated],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def _format_result(completed: subprocess.CompletedProcess[str], cwd: Path) -> dict[str, Any]:
    stdout = (completed.stdout or "")[: settings.max_output_bytes]
    stderr = (completed.stderr or "")[: settings.max_output_bytes]
    return {
        "summary": f"exit={completed.returncode}",
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": completed.returncode,
        "cwd": str(cwd),
    }


def _run(req: ToolInvokeRequest) -> dict[str, Any]:
    command = str(req.payload.get("command", ""))
    cwd = _run_dir(str(req.run_id) if req.run_id else None)
    timeout = min(int(req.payload.get("timeout", settings.max_timeout_sec)), settings.max_timeout_sec)
    completed = _execute(command, cwd, timeout)
    return _format_result(completed, cwd)


def _stub_run(req: ToolInvokeRequest) -> dict[str, Any]:
    try:
        return _run(req)
    except ValueError:
        raise
    except Exception as exc:
        command = str(req.payload.get("command", "echo stub"))
        return {
            "summary": f"stub failed: {exc}",
            "stdout": "",
            "stderr": str(exc),
            "exit_code": 1,
            "cwd": str(_run_dir(str(req.run_id) if req.run_id else None)),
        }


HANDLERS = {"shell.run": _run}
STUB_HANDLERS = {"shell.run": _stub_run}

app = create_tool_app(settings, HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()
