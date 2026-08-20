"""Копирование файлов на компьютере пользователя (Desktop и локальные пути)."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.tools.ac.agent_workspace import AgentWorkspaceResolver, WorkspaceError
from app.tools.ac.base import BaseTool
from app.tools.ac.registry import ToolRegistry
from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)


def _desktop_dir() -> Path:
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "OneDrive" / "Desktop",
        Path(os.environ.get("USERPROFILE", "")) / "Desktop",
        Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "Desktop",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return home / "Desktop"


def resolve_local_path(raw: str) -> Path:
    text = unquote((raw or "").strip().strip('"').strip("'"))
    if text.lower().startswith("file:"):
        parsed = urlparse(text)
        path = unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc not in {".", "localhost"}:
            path = f"//{parsed.netloc}{path}"
        if path.startswith("/") and len(path) >= 3 and path[2] == ":":
            path = path[1:]
        text = path.replace("/", "\\") if os.name == "nt" else path
    return Path(text).expanduser()


def _resolve_desktop_porucheniya_file() -> Path | None:
    """Найти Excel поручений на рабочем столе: Поручения.xlsx или act_porucheniya_*.xlsx."""
    desktop = _desktop_dir()
    for name in ("Поручения.xlsx", "porucheniya.xlsx"):
        candidate = desktop / name
        if candidate.is_file():
            return candidate.resolve()
    matches = sorted(
        desktop.glob("act_porucheniya_*.xlsx"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for path in matches:
        if path.is_file():
            return path.resolve()
    return None


def _resolve_rename_source(source_raw: str) -> Path | None:
    token = (source_raw or "").strip()
    low = token.casefold()
    if low in {
        "desktop:porucheniya",
        "porucheniya",
        "поручения",
        "поручений",
        "поручен",
        "поручения.xlsx",
        "поручений.xlsx",
    } or "поручен" in low:
        return _resolve_desktop_porucheniya_file()
    path = resolve_local_path(token)
    if path.is_file():
        return path.resolve()
    if not path.is_absolute() and len(path.parts) == 1:
        desktop_candidate = _desktop_dir() / path.name
        if desktop_candidate.is_file():
            return desktop_candidate.resolve()
    return None


def format_files_table(paths: list[str]) -> str:
    """Таблица как Get-Item | Format-Table FullName, Length, LastWriteTime."""
    rows: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for raw in paths:
        path = resolve_local_path(raw)
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M:%S")
        rows.append((str(path), int(stat.st_size), modified))
    if not rows:
        return ""
    name_w = max(len("FullName"), *(len(row[0]) for row in rows))
    lines = [
        "Созданные файлы:",
        f"{'FullName'.ljust(name_w)}  {'Length'.rjust(12)}  LastWriteTime",
        f"{'-' * name_w}  {'-' * 12}  -------------",
    ]
    for full_name, length, modified in rows:
        lines.append(f"{full_name.ljust(name_w)}  {length:>12}  {modified}")
    return "\n".join(lines)


_PATH_RE = re.compile(
    r"(?:file:///|file://)?[A-Za-z]:\\(?:[^\\/\n\r\"<>|]+\\)*[^\\/\n\r\"<>|]+",
    re.IGNORECASE,
)


def collect_paths_from_work(work: dict | None, text: str = "") -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        token = (raw or "").strip().strip("-•*").strip()
        if not token or token.casefold() in {"нет", "—", "-"}:
            return
        key = token.casefold()
        if key in seen:
            return
        seen.add(key)
        found.append(token)

    if isinstance(work, dict):
        for item in work.get("files") or []:
            add(str(item))
    blob = f"{text}\n" + "\n".join(str(x) for x in (work or {}).get("files") or [])
    for match in _PATH_RE.finditer(blob):
        add(match.group(0))
    return found


class FilesInspectTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name="files.inspect",
                title="Проверка файлов",
                description=(
                    "Проверяет локальные файлы: полный путь, размер (байты), дата изменения. "
                    "Вызови перед RESULT для каждого созданного/изменённого файла."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "path": {"type": "string"},
                    },
                },
                output_schema={"type": "object"},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        paths_raw = input_data.get("paths")
        collected: list[str] = []
        if isinstance(paths_raw, list):
            collected.extend(str(item) for item in paths_raw if str(item).strip())
        single = str(input_data.get("path") or "").strip()
        if single:
            collected.append(single)
        if not collected:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_PATHS",
                error_message="Передайте path или paths — список файлов для проверки.",
            )
        items: list[dict[str, str | int]] = []
        for raw in collect_paths_from_work({"files": collected}):
            path = resolve_local_path(raw)
            if not path.is_file():
                continue
            stat = path.stat()
            items.append(
                {
                    "FullName": str(path),
                    "Length": int(stat.st_size),
                    "LastWriteTime": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M:%S"),
                }
            )
        if not items:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="NOT_FOUND",
                error_message="Ни один из указанных файлов не найден.",
            )
        table = format_files_table([str(item["FullName"]) for item in items])
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={"files": items, "table": table, "count": len(items)},
        )


def _target_filename(dest_name: str, source: Path) -> str:
    name = dest_name.strip()
    if name.lower().endswith(".xlsx"):
        return name
    if source.suffix:
        return f"{name}{source.suffix}"
    return name


class FilesCopyTool(BaseTool):
    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        super().__init__(
            ToolDefinition(
                name="files.copy",
                title="Копирование файла",
                description=(
                    "Копирует локальный файл в рабочую папку агента (out/). "
                    "dest_name — новое имя без пути."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "dest": {"type": "string"},
                        "dest_name": {"type": "string"},
                    },
                    "required": ["source"],
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        source_raw = str(input_data.get("source") or "").strip()
        if not source_raw:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_SOURCE",
                error_message="Передайте source — путь или file:///",
            )
        source = resolve_local_path(source_raw)
        if not source.is_file():
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="NOT_FOUND",
                error_message=f"Файл не найден: {source}",
            )

        dest_raw = str(input_data.get("dest") or "").strip()
        dest_name = str(input_data.get("dest_name") or "").strip()
        workspace = self._resolver.for_agent(self._resolver.agent_id_from_input(input_data))
        if dest_raw:
            dest = resolve_local_path(dest_raw)
            if dest.is_dir() or dest_raw.endswith(("/", "\\")):
                dest = dest / (dest_name or source.name)
            elif dest_name and dest.suffix == "":
                dest = dest.with_name(dest_name + source.suffix)
            if not workspace.is_path_allowed(dest):
                return ToolCallResult(
                    ok=False,
                    tool_name=self.definition.name,
                    error_type="WORKSPACE_ERROR",
                    error_message="Копирование разрешено только в рабочую папку агента.",
                )
        else:
            name = dest_name or f"{source.stem}_копия"
            if dest_name and Path(dest_name).suffix:
                filename = dest_name
            else:
                filename = f"{name}{source.suffix}"
            dest = workspace.resolve_output(filename)

        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() == source.resolve():
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="SAME_PATH",
                error_message="Источник и копия совпадают.",
            )
        shutil.copy2(source, dest)
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "source": str(source),
                "path": str(dest),
                "name": dest.name,
            },
        )


class FilesRenameTool(BaseTool):
    def __init__(self, resolver: AgentWorkspaceResolver) -> None:
        super().__init__(
            ToolDefinition(
                name="files.rename",
                title="Переименование файла",
                description=(
                    "Переименовывает файл в рабочей папке агента. "
                    "dest_name — новое имя без пути."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "dest_name": {"type": "string"},
                    },
                    "required": ["source", "dest_name"],
                },
                output_schema={"type": "object"},
            )
        )
        self._resolver = resolver

    def execute(self, input_data: dict) -> ToolCallResult:
        source_raw = str(input_data.get("source") or "").strip()
        dest_name = str(input_data.get("dest_name") or "").strip()
        if not source_raw:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_SOURCE",
                error_message="Передайте source — путь или file:///",
            )
        if not dest_name:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_DEST",
                error_message="Передайте dest_name — новое имя файла.",
            )
        workspace = self._resolver.for_agent(self._resolver.agent_id_from_input(input_data))
        source = resolve_local_path(source_raw)
        if not source.is_file():
            try:
                source = workspace.resolve_output(Path(source_raw).name, must_exist=True)
            except WorkspaceError:
                source = Path()
        if not source.is_file():
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="NOT_FOUND",
                error_message=f"Файл не найден в рабочей папке агента: {source_raw}",
            )
        if not workspace.is_path_allowed(source):
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="WORKSPACE_ERROR",
                error_message="Переименование разрешено только в рабочей папке агента.",
            )
        filename = _target_filename(dest_name, source)
        dest = source.parent / filename
        if dest.resolve() == source.resolve():
            return ToolCallResult(
                ok=True,
                tool_name=self.definition.name,
                output_data={
                    "source": str(source),
                    "path": str(dest),
                    "name": dest.name,
                    "renamed": False,
                },
            )
        if dest.exists():
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="EXISTS",
                error_message=f"Файл уже существует: {dest}",
            )
        try:
            shutil.move(str(source), str(dest))
        except OSError as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="MOVE_FAILED",
                error_message=str(exc) or "Не удалось переименовать файл (возможно, он открыт).",
            )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "source": str(source),
                "path": str(dest),
                "name": dest.name,
                "renamed": True,
            },
        )


def register_files_tools(
    registry: ToolRegistry,
    resolver: AgentWorkspaceResolver,
    *,
    skip_existing: bool = False,
) -> None:
    for tool in (FilesCopyTool(resolver), FilesRenameTool(resolver), FilesInspectTool()):
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)
