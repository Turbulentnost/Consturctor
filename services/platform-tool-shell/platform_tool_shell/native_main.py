from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app

NATIVE_ALLOWED_COMMANDS = {
    "cd",
    "dir",
    "type",
    "echo",
    "where",
    "copy",
    "move",
    "mkdir",
    "rd",
    "ls",
    "pwd",
    "cat",
    "find",
    "python",
    "pip",
    "git",
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


class NativeShellSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-shell-native"
    api_port: int = 7828
    shell_cwd_roots: str = ""
    max_timeout_sec: int = 120
    max_output_bytes: int = 131072


settings = NativeShellSettings()


def _cwd_roots() -> list[Path]:
    raw = (settings.shell_cwd_roots or os.environ.get("SHELL_CWD_ROOTS") or "").strip()
    if not raw:
        default = Path.cwd() / "data" / "shell-native"
        default.mkdir(parents=True, exist_ok=True)
        return [default.resolve()]
    roots: list[Path] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        path = Path(part).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        roots.append(path)
    return roots or [Path.cwd().resolve()]


def _resolve_cwd(cwd_str: str | None) -> Path:
    if not cwd_str or not str(cwd_str).strip():
        return _cwd_roots()[0]
    candidate = Path(str(cwd_str).strip()).expanduser()
    if not candidate.is_absolute():
        candidate = _cwd_roots()[0] / candidate
    resolved = candidate.resolve()
    for root in _cwd_roots():
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError(f"cwd not allowed: {cwd_str}")


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
        if name not in NATIVE_ALLOWED_COMMANDS:
            raise ValueError(f"command not allowed: {head.group(1)}")
    return command


def _execute(command: str, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    validated = _validate_shell_command(command)
    cwd.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["cmd.exe", "/c", validated],
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
        "runtime": "native",
        "source": "shell-native",
    }


def _run(req: ToolInvokeRequest) -> dict[str, Any]:
    command = str(req.payload.get("command", ""))
    cwd = _resolve_cwd(req.payload.get("cwd"))
    timeout = min(int(req.payload.get("timeout", settings.max_timeout_sec)), settings.max_timeout_sec)
    completed = _execute(command, cwd, timeout)
    return _format_result(completed, cwd)


def _stub_run(req: ToolInvokeRequest) -> dict[str, Any]:
    if os.name != "nt":
        command = str(req.payload.get("command", "echo stub"))
        return {
            "summary": "native shell requires Windows host",
            "stdout": "",
            "stderr": "native shell unavailable on non-Windows platform",
            "exit_code": 1,
            "cwd": str(_cwd_roots()[0]),
            "runtime": "native",
            "source": "stub",
        }
    try:
        return _run(req)
    except ValueError:
        raise
    except Exception as exc:
        return {
            "summary": f"native shell failed: {exc}",
            "stdout": "",
            "stderr": str(exc),
            "exit_code": 1,
            "cwd": str(_resolve_cwd(req.payload.get("cwd"))),
            "runtime": "native",
            "source": "stub",
        }


HANDLERS = {"shell.run": _run}
STUB_HANDLERS = {"shell.run": _stub_run}

app = create_tool_app(settings, HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()
