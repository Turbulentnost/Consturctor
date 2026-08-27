"""PowerShell-инструмент для рабочей папки агента.

Команды всегда выполняются внутри изолированной директории агента. Инструмент
блокирует явно разрушительные команды до подтверждения человеком.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.ac.agent_workspace import (
    AgentWorkspaceResolver,
    WorkspaceError,
)
from app.tools.ac.base import BaseTool
from app.tools.ac.process_run import run_captured, wrap_powershell_command
from app.tools.ac.registry import ToolRegistry

DEFAULT_TIMEOUT_SECONDS = 90
MAX_TIMEOUT_SECONDS = 300
MAX_OUTPUT_CHARS = 20_000
SUMMARY_CHARS = 2_000

_DESTRUCTIVE_COMMAND_RE = re.compile(
    r"(?i)(^|[\s;&|({])"
    r"(remove-item|rm|ri|del|erase|rmdir|rd|clear-content|clc|set-content|sc)"
    r"\b"
)


def _summarize(text: str, max_chars: int = SUMMARY_CHARS) -> str:
    """Вернуть компактное представление stdout/stderr для контекста LLM."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def is_destructive_powershell_command(command: str) -> bool:
    """Определить, похожа ли команда на удаление/перезапись содержимого."""
    return bool(_DESTRUCTIVE_COMMAND_RE.search(command or ""))


class WorkspacePowerShellRunTool(BaseTool):
    """Запускает PowerShell-команду в рабочей папке агента."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        """Создать инструмент запуска PowerShell."""
        super().__init__(
            ToolDefinition(
                name="workspace.powershell_run",
                title="PowerShell в папке агента",
                description=(
                    "Запускает PowerShell-команду только в рабочей папке агента "
                    "и возвращает stdout/stderr."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_retries=0,
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout_seconds": {"type": "integer"},
                        "working_subdir": {"type": "string"},
                    },
                    "required": ["command"],
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        """Выполнить команду PowerShell в sandbox директории агента."""
        command = str(input_data.get("command") or "").strip()
        if not command:
            return self._fail("INVALID_COMMAND", "Передайте непустую command.")

        try:
            workspace = self._resolver.for_agent(
                self._resolver.agent_id_from_input(input_data)
            )
            cwd = self._resolve_cwd(workspace.directory, input_data.get("working_subdir"))
        except WorkspaceError as exc:
            return self._fail("WORKSPACE_ERROR", str(exc))

        if is_destructive_powershell_command(command) and not self._is_human_approved(
            input_data
        ):
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="HUMAN_APPROVAL_REQUIRED",
                error_message=(
                    "Команда PowerShell похожа на удаление или разрушительную "
                    "перезапись файлов и требует подтверждения человека."
                ),
                requires_human_approval=True,
            )

        executable = self._find_powershell()
        if executable is None:
            return self._fail(
                "POWERSHELL_NOT_FOUND",
                "Не найден исполняемый файл PowerShell (pwsh или powershell).",
            )

        timeout = self._timeout(input_data.get("timeout_seconds"))
        wrapped = wrap_powershell_command(command)
        argv = [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
        ]
        if executable.lower().endswith("powershell.exe"):
            argv.extend(["-WindowStyle", "Hidden"])
        argv.extend(["-Command", wrapped])
        try:
            completed = run_captured(
                argv,
                cwd=cwd,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - subprocess может вернуть OSError
            return self._fail("POWERSHELL_EXECUTION_ERROR", str(exc))

        return self._result(
            command=command,
            cwd=cwd,
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=completed.timed_out,
        )

    def _resolve_cwd(self, workspace_dir: Path, working_subdir: object) -> Path:
        """Вернуть cwd внутри workspace и запретить path traversal."""
        base = workspace_dir.resolve()
        if working_subdir is None or not str(working_subdir).strip():
            return base
        candidate = (base / str(working_subdir).strip()).resolve()
        if base != candidate and base not in candidate.parents:
            raise WorkspaceError("working_subdir выходит за пределы рабочей папки агента")
        if not candidate.exists() or not candidate.is_dir():
            raise WorkspaceError(f"working_subdir не является папкой: {working_subdir}")
        return candidate

    @staticmethod
    def _is_human_approved(input_data: dict) -> bool:
        runtime_context = input_data.get("runtime_context") or {}
        return bool(
            input_data.get("human_approved")
            or (
                isinstance(runtime_context, dict)
                and runtime_context.get("human_approved")
            )
        )

    @staticmethod
    def _find_powershell() -> str | None:
        return shutil.which("pwsh") or shutil.which("powershell")

    @staticmethod
    def _timeout(value: object) -> int:
        try:
            timeout = int(value or DEFAULT_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_SECONDS
        return max(1, min(timeout, MAX_TIMEOUT_SECONDS))

    def _result(
        self,
        *,
        command: str,
        cwd: Path,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        timed_out: bool,
    ) -> ToolCallResult:
        stdout = self._trim(self._coerce_output(stdout))
        stderr = self._trim(self._coerce_output(stderr))
        ok = not timed_out and exit_code == 0
        error_type = None
        error_message = None
        if timed_out:
            error_type = "COMMAND_TIMED_OUT"
            error_message = "Команда PowerShell превысила timeout."
        elif not ok:
            error_type = "COMMAND_FAILED"
            error_message = f"Команда PowerShell завершилась с кодом {exit_code}."
        return ToolCallResult(
            ok=ok,
            tool_name=self.definition.name,
            output_data={
                "ok": ok,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_summary": _summarize(stdout),
                "stderr_summary": _summarize(stderr),
                "cwd": str(cwd),
                "command": command,
                "timed_out": timed_out,
            },
            error_type=error_type,
            error_message=error_message,
        )

    def _fail(self, error_type: str, message: str) -> ToolCallResult:
        return ToolCallResult(
            ok=False,
            tool_name=self.definition.name,
            error_type=error_type,
            error_message=message,
        )

    @staticmethod
    def _trim(text: str) -> str:
        if len(text) <= MAX_OUTPUT_CHARS:
            return text
        return text[:MAX_OUTPUT_CHARS] + "..."

    @staticmethod
    def _coerce_output(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)


def register_powershell_tools(
    registry: ToolRegistry,
    resolver: AgentWorkspaceResolver,
    *,
    skip_existing: bool = False,
) -> None:
    """Зарегистрировать PowerShell-инструменты workspace."""
    tool = WorkspacePowerShellRunTool(resolver)
    if skip_existing and registry.has_tool(tool.definition.name):
        return
    registry.register(tool)
