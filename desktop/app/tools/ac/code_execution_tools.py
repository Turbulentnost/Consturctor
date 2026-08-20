"""Инструменты написания и запуска Python-кода в рабочей папке агента.

Архитектурная идея: LLM сама решает, нужно ли писать код, какой код писать,
запускать ли его и как чинить после ошибки. Модель НЕ получает прямой доступ к
терминалу — она лишь выбирает разрешённое действие ``code.write_python`` /
``code.run_python``. Runtime и эти инструменты гарантируют, что весь код лежит и
исполняется только внутри подпапки ``code`` рабочей директории агента.

Такой подход позволяет делегировать тяжёлую обработку данных (например, разбор
большой таблицы с выгруженной страницы) написанной моделью программе, а не самой
языковой модели — без хардкода под конкретную задачу.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from app.frozen_runtime import agent_python_command
from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.ac.agent_workspace import (
    AgentWorkspace,
    AgentWorkspaceResolver,
    WorkspaceError,
)
from app.tools.ac.base import BaseTool
from app.tools.ac.registry import ToolRegistry

CODE_SUBDIR = "code"
DEFAULT_SCRIPT_NAME = "main.py"
DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 600
MAX_OUTPUT_CHARS = 20_000
SUMMARY_CHARS = 2_000


def _summarize(text: str, max_chars: int = SUMMARY_CHARS) -> str:
    """Вернуть компактное представление stdout/stderr для контекста LLM."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _trim(text: str) -> str:
    """Ограничить объём вывода, который сохраняется в результате."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "..."


def _python_command_prefix() -> list[str] | None:
    """Вернуть команду запуска Python-кода агента.

    В исходниках используем текущий Python. В frozen exe отдельного python.exe
    может не быть, поэтому вызываем консольный ConstructorComWorker.exe
    в режиме --agent-python-runner (встроенный runtime PyInstaller).
    """
    if getattr(sys, "frozen", False) and sys.executable:
        return agent_python_command(sys.executable, frozen=True)
    if sys.executable:
        return [sys.executable]
    for name in ("python", "python3", "py"):
        found = shutil.which(name)
        if found:
            return [found]
    return None


def _code_dir(workspace: AgentWorkspace) -> Path:
    """Вернуть (создав при необходимости) подпапку code рабочей папки агента."""
    code_dir = (workspace.directory / CODE_SUBDIR).resolve()
    code_dir.mkdir(parents=True, exist_ok=True)
    return code_dir


def _resolve_code_file(workspace: AgentWorkspace, filename: object) -> Path:
    """Вернуть безопасный путь .py внутри подпапки code (защита от traversal)."""
    name = str(filename or DEFAULT_SCRIPT_NAME).strip() or DEFAULT_SCRIPT_NAME
    code_dir = _code_dir(workspace)
    candidate = (code_dir / name).resolve()
    if code_dir != candidate and code_dir not in candidate.parents:
        raise WorkspaceError("Путь скрипта выходит за пределы папки code агента")
    if candidate.suffix.lower() != ".py":
        raise WorkspaceError("Разрешены только .py файлы в папке code агента")
    return candidate


class CodeWritePythonTool(BaseTool):
    """Записывает Python-код в подпапку ``code`` рабочей папки агента."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        """Создать инструмент записи кода."""
        super().__init__(
            ToolDefinition(
                name="code.write_python",
                title="Написать Python-код в папку агента",
                description=(
                    "Сохраняет Python-код в подпапку code рабочей папки агента "
                    "(только .py). Не запускает код — для запуска используй "
                    "code.run_python."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                timeout_seconds=15,
                max_retries=0,
                input_schema={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "filename": {"type": "string"},
                    },
                    "required": ["code"],
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        """Записать переданный код в файл внутри папки code агента."""
        code = input_data.get("code")
        if not isinstance(code, str) or not code.strip():
            return _fail(self.definition.name, "INVALID_CODE", "Передайте непустой code.")
        try:
            workspace = self._resolver.for_agent(
                self._resolver.agent_id_from_input(input_data)
            )
            target = _resolve_code_file(workspace, input_data.get("filename"))
        except WorkspaceError as exc:
            return _fail(self.definition.name, "WORKSPACE_ERROR", str(exc))

        try:
            target.write_text(code, encoding="utf-8")
        except OSError as exc:
            return _fail(self.definition.name, "WRITE_ERROR", str(exc))

        relative = target.relative_to(workspace.directory).as_posix()
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "path": relative,
                "absolute_path": str(target),
                "filename": target.name,
                "bytes_written": len(code.encode("utf-8")),
                "lines": code.count("\n") + 1,
            },
        )


class CodeRunPythonTool(BaseTool):
    """Запускает Python-скрипт из подпапки ``code`` рабочей папки агента."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        """Создать инструмент запуска кода (требует подтверждения человека)."""
        super().__init__(
            ToolDefinition(
                name="code.run_python",
                title="Запустить Python-код агента",
                description=(
                    "Запускает .py файл из подпапки code рабочей папки агента и "
                    "возвращает stdout/stderr/exit_code. Можно передать inline code "
                    "— он будет сначала сохранён, затем запущен. Рабочая директория "
                    "процесса — папка агента, поэтому скрипт может читать выгруженные "
                    "файлы и писать результаты. По умолчанию требует подтверждения "
                    "человека; в LLM-цикле Runtime может автоподтвердить несколько "
                    "запусков подряд в sandbox (бюджет rewrite→rerun)."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=True,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_retries=0,
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "code": {"type": "string"},
                        "args": {"type": "array", "items": {"type": "string"}},
                        "timeout_seconds": {"type": "integer"},
                    },
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        """Запустить .py файл из папки code в рабочей директории агента."""
        try:
            workspace = self._resolver.for_agent(
                self._resolver.agent_id_from_input(input_data)
            )
            target = _resolve_code_file(workspace, input_data.get("filename"))
        except WorkspaceError as exc:
            return _fail(self.definition.name, "WORKSPACE_ERROR", str(exc))

        code = input_data.get("code")
        if isinstance(code, str) and code.strip():
            try:
                target.write_text(code, encoding="utf-8")
            except OSError as exc:
                return _fail(self.definition.name, "WRITE_ERROR", str(exc))

        if not target.exists():
            return _fail(
                self.definition.name,
                "SCRIPT_NOT_FOUND",
                f"Файл {target.name} не найден в папке code. Сначала запиши код "
                "(code.write_python) или передай inline code.",
            )

        command_prefix = _python_command_prefix()
        if command_prefix is None:
            return _fail(
                self.definition.name,
                "PYTHON_NOT_FOUND",
                "Не найден интерпретатор Python и недоступен встроенный runner exe.",
            )

        args = [str(item) for item in (input_data.get("args") or []) if str(item)]
        timeout = _timeout(input_data.get("timeout_seconds"))
        try:
            completed = subprocess.run(
                [*command_prefix, str(target), *args],
                cwd=str(workspace.directory),
                capture_output=True,
                text=True,
                timeout=timeout,
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            return self._result(
                workspace=workspace,
                target=target,
                exit_code=None,
                stdout=_coerce(exc.stdout),
                stderr=_coerce(exc.stderr),
                timed_out=True,
            )
        except Exception as exc:  # noqa: BLE001 - subprocess может вернуть OSError
            return _fail(self.definition.name, "PYTHON_EXECUTION_ERROR", str(exc))

        return self._result(
            workspace=workspace,
            target=target,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )

    def _result(
        self,
        *,
        workspace: AgentWorkspace,
        target: Path,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        timed_out: bool,
    ) -> ToolCallResult:
        stdout = _trim(_coerce(stdout))
        stderr = _trim(_coerce(stderr))
        ok = not timed_out and exit_code == 0
        error_type = None
        error_message = None
        if timed_out:
            error_type = "SCRIPT_TIMED_OUT"
            error_message = "Python-скрипт превысил timeout."
        elif not ok:
            error_type = "SCRIPT_FAILED"
            error_message = (
                f"Python-скрипт завершился с кодом {exit_code}. Проанализируй "
                "stderr, при необходимости перепиши код (code.write_python) и запусти снова."
            )
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
                "script": target.relative_to(workspace.directory).as_posix(),
                "cwd": str(workspace.directory),
                "timed_out": timed_out,
            },
            error_type=error_type,
            error_message=error_message,
        )


def _fail(tool_name: str, error_type: str, message: str) -> ToolCallResult:
    """Собрать неуспешный результат инструмента."""
    return ToolCallResult(
        ok=False,
        tool_name=tool_name,
        error_type=error_type,
        error_message=message,
    )


def _timeout(value: object) -> int:
    """Ограничить timeout запуска скрипта разумными пределами."""
    try:
        timeout = int(value or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    return max(1, min(timeout, MAX_TIMEOUT_SECONDS))


def _coerce(value: object) -> str:
    """Привести stdout/stderr к строке."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def register_code_execution_tools(
    registry: ToolRegistry,
    resolver: AgentWorkspaceResolver,
    *,
    skip_existing: bool = False,
) -> None:
    """Зарегистрировать инструменты написания и запуска Python-кода."""
    tools = [CodeWritePythonTool(resolver), CodeRunPythonTool(resolver)]
    for tool in tools:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)
