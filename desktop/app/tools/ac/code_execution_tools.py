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

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from app.frozen_runtime import agent_python_command
from app.tools.ac.process_run import run_captured
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
DEFAULT_TIMEOUT_SECONDS = 180
MAX_TIMEOUT_SECONDS = 600
MAX_OUTPUT_CHARS = 20_000
SUMMARY_CHARS = 2_000
FAILURE_TAIL_CHARS = 8_000
_KPI_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


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
        if found and "windowsapps" not in found.casefold():
            return [found]
    return None


def _agent_python_env() -> dict[str, str]:
    """Run agent scripts without the sidecar PYTHONPATH / console encoding."""
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.pop("PYTHONPATH", None)
    return env


def _script_failure_message(exit_code: int | None, stdout: str, stderr: str) -> str:
    blob = "\n".join(part for part in ((stdout or "").strip(), (stderr or "").strip()) if part)
    if len(blob) > FAILURE_TAIL_CHARS:
        blob = blob[-FAILURE_TAIL_CHARS:]
    detail = f"\n{blob}" if blob else ""
    if "No module named pytest" in blob:
        return (
            f"Python-скрипт завершился с кодом {exit_code}.{detail}\n"
            "В этом интерпретаторе нет pytest. Модуль не переписывай и пакеты не ставь."
        )
    return (
        f"Python-скрипт завершился с кодом {exit_code}.{detail}\n"
        "Перепиши код (code.write_python) и запусти снова."
    )


def _imports_pytest(command: list[str]) -> bool:
    try:
        completed = subprocess.run(
            [*command, "-c", "import pytest"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


_PYTEST_PREFIX: list[str] | None = None


def pytest_command_prefix() -> list[str]:
    """Python that can run pytest. The sidecar interpreter often cannot."""
    global _PYTEST_PREFIX
    if _PYTEST_PREFIX:
        return list(_PYTEST_PREFIX)
    candidates: list[list[str]] = []
    own = _python_command_prefix()
    if own:
        candidates.append(own)
    if sys.executable:
        exe = Path(sys.executable)
        sibling = exe.parent.parent / "Python313" / "python.exe"
        if sibling.is_file() and sibling.resolve() != exe.resolve():
            candidates.append([str(sibling)])
    launcher = shutil.which("py")
    if launcher and "windowsapps" not in launcher.casefold():
        candidates.append([launcher, "-3.13"])
        candidates.append([launcher, "-3"])
    chosen = list(own or [sys.executable])
    for command in candidates:
        if _imports_pytest(command):
            chosen = list(command)
            break
    _PYTEST_PREFIX = chosen
    return list(chosen)


def _pytest_command(prefix: list[str], target: Path) -> list[str]:
    command = pytest_command_prefix() or list(prefix)
    if not getattr(sys, "frozen", False):
        if "-u" not in command:
            command.append("-u")
        if "-X" not in command:
            command.extend(["-X", "utf8"])
    command.extend(["-m", "pytest", str(target), "-q", "--tb=short"])
    return command


def _python_run_command(prefix: list[str], target: Path, args: list[str]) -> list[str]:
    """Build argv: unbuffered UTF-8 CPython, or the frozen runner as-is.

    Do not pass -I / -E: those ignore PYTHONUTF8 and can hide user site
    packages the agent script needs (openpyxl, pandas). PYTHONPATH is
    stripped in the child env instead, so the sidecar desktop/ tree is
    not imported.
    """
    command = list(prefix)
    if not getattr(sys, "frozen", False):
        if "-u" not in command:
            command.append("-u")
        if "-X" not in command:
            command.extend(["-X", "utf8"])
    command.append(str(target))
    command.extend(args)
    return command


def _code_dir(workspace: AgentWorkspace) -> Path:
    """Вернуть (создав при необходимости) подпапку code рабочей папки агента."""
    code_dir = (workspace.directory / CODE_SUBDIR).resolve()
    code_dir.mkdir(parents=True, exist_ok=True)
    return code_dir


def _normalize_code_name(filename: object) -> str:
    name = str(filename or DEFAULT_SCRIPT_NAME).strip().replace("\\", "/") or DEFAULT_SCRIPT_NAME
    while name.startswith("./"):
        name = name[2:]
    return name.lstrip("/")


def _kpi_slug_ok(stem: str) -> bool:
    return bool(_KPI_SLUG.match(stem))


def _resolve_kpi_module_file(workspace: AgentWorkspace, name: str) -> Path | None:
    """generated/<slug>.py и tests/test_<slug>.py — в корне workspace, не в code/."""
    relative = name[len(CODE_SUBDIR) + 1 :] if name.startswith(f"{CODE_SUBDIR}/") else name
    parts = tuple(part for part in relative.split("/") if part)
    if any(part in {".", ".."} for part in parts):
        raise WorkspaceError("Путь скрипта выходит за пределы рабочей папки агента")
    if len(parts) != 2:
        return None
    folder, filename = parts
    if not filename.endswith(".py"):
        raise WorkspaceError("Разрешены только .py файлы")
    stem = filename[: -len(".py")]
    if folder == "generated":
        if stem in {"__init__"} or stem.startswith("test_") or not _kpi_slug_ok(stem):
            raise WorkspaceError("Модуль KPI: generated/<slug>.py, slug из латиницы в нижнем регистре")
    elif folder == "tests":
        if not stem.startswith("test_") or not _kpi_slug_ok(stem[len("test_") :]):
            raise WorkspaceError("Тест KPI: tests/test_<slug>.py")
    else:
        return None
    root = workspace.directory.resolve()
    candidate = (root / folder / filename).resolve()
    if root != candidate and root not in candidate.parents:
        raise WorkspaceError("Путь скрипта выходит за пределы рабочей папки агента")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    init = root / "generated" / "__init__.py"
    if not init.exists():
        init.parent.mkdir(parents=True, exist_ok=True)
        init.write_text('"""KPI modules for this build."""\n', encoding="utf-8")
    return candidate


def _resolve_code_file(workspace: AgentWorkspace, filename: object) -> Path:
    """Путь .py: KPI-модули в generated/ и tests/, остальное только в code/."""
    name = _normalize_code_name(filename)
    if ".." in name.split("/"):
        raise WorkspaceError("Путь скрипта выходит за пределы рабочей папки агента")
    kpi_file = _resolve_kpi_module_file(workspace, name)
    if kpi_file is not None:
        return kpi_file
    code_dir = _code_dir(workspace)
    candidate = (code_dir / name).resolve()
    if code_dir != candidate and code_dir not in candidate.parents:
        raise WorkspaceError("Путь скрипта выходит за пределы папки code агента")
    if candidate.suffix.lower() != ".py":
        raise WorkspaceError("Разрешены только .py файлы в папке code агента")
    return candidate


def _is_kpi_test_file(workspace: AgentWorkspace, target: Path) -> bool:
    try:
        relative = target.resolve().relative_to(workspace.directory.resolve()).as_posix()
    except ValueError:
        return False
    if not relative.startswith("tests/test_") or not relative.endswith(".py"):
        return False
    return "/" not in relative[len("tests/") :]


def promote_kpi_artifacts(workspace: Path) -> None:
    """Перенести модули, записанные в code/generated и code/tests, в корень workspace."""
    root = Path(workspace)
    generated = root / "generated"
    tests = root / "tests"
    generated.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    init = generated / "__init__.py"
    if not init.exists():
        init.write_text('"""KPI modules for this build."""\n', encoding="utf-8")

    def relocate(path: Path, dest_dir: Path, *, test: bool) -> None:
        stem = path.stem[len("test_") :] if test else path.stem
        if path.name == "__init__.py" or not _kpi_slug_ok(stem):
            return
        if test and not path.name.startswith("test_"):
            return
        dest = dest_dir / path.name
        if path.resolve() == dest.resolve():
            return
        dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.unlink()

    code_generated = root / CODE_SUBDIR / "generated"
    code_tests = root / CODE_SUBDIR / "tests"
    if code_generated.is_dir():
        for path in list(code_generated.glob("*.py")):
            if path.name.startswith("test_"):
                relocate(path, tests, test=True)
            else:
                relocate(path, generated, test=False)
    if code_tests.is_dir():
        for path in list(code_tests.glob("test_*.py")):
            relocate(path, tests, test=True)
    for path in list(generated.glob("test_*.py")):
        relocate(path, tests, test=True)


class CodeWritePythonTool(BaseTool):
    """Записывает Python-код в подпапку ``code`` рабочей папки агента."""

    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        """Создать инструмент записи кода."""
        super().__init__(
            ToolDefinition(
                name="code.write_python",
                title="Написать Python-код в папку агента",
                description=(
                    "Сохраняет Python-код. Обычный скрипт — в подпапку code. "
                    "Модуль KPI — filename ровно generated/<slug>.py, тест — "
                    "tests/test_<slug>.py: они пишутся в корень рабочей папки, не в code/. "
                    "Не запускает код — для запуска используй code.run_python."
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
        """Создать инструмент запуска кода в sandbox без HITL."""
        super().__init__(
            ToolDefinition(
                name="code.run_python",
                title="Запустить Python-код агента",
                description=(
                    "Запускает .py из подпапки code и возвращает stdout/stderr/exit_code. "
                    "filename tests/test_<slug>.py запускает pytest этого файла. "
                    "Можно передать inline code — он будет сначала сохранён, затем запущен. "
                    "Рабочая директория процесса — папка агента. "
                    "Если pytest или скрипт упал, в ответе есть traceback: поправь файл "
                    "через code.write_python и запусти снова."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
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
        if _is_kpi_test_file(workspace, target):
            command = _pytest_command(command_prefix, target)
        else:
            command = _python_run_command(command_prefix, target, args)
        try:
            completed = run_captured(
                command,
                cwd=workspace.directory,
                timeout=timeout,
                env=_agent_python_env(),
            )
        except Exception as exc:  # noqa: BLE001 - subprocess может вернуть OSError
            return _fail(self.definition.name, "PYTHON_EXECUTION_ERROR", str(exc))

        return self._result(
            workspace=workspace,
            target=target,
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=completed.timed_out,
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
            error_message = _script_failure_message(exit_code, stdout, stderr)
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
