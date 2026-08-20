"""Копирование файлов на компьютере пользователя (Desktop и локальные пути)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

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


class FilesCopyTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name="files.copy",
                title="Копирование файла",
                description=(
                    "Копирует локальный файл (в том числе с рабочего стола и file:///). "
                    "dest_name — новое имя без пути; если не указан dest, копия "
                    "кладётся рядом с исходником или на Desktop."
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
        if dest_raw:
            dest = resolve_local_path(dest_raw)
            if dest.is_dir() or dest_raw.endswith(("/", "\\")):
                dest = dest / (dest_name or source.name)
            elif dest_name and dest.suffix == "":
                dest = dest.with_name(dest_name + source.suffix)
        else:
            folder = source.parent if source.parent.is_dir() else _desktop_dir()
            name = dest_name or f"{source.stem}_копия"
            if dest_name and Path(dest_name).suffix:
                filename = dest_name
            else:
                filename = f"{name}{source.suffix}"
            dest = folder / filename

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


def register_files_tools(registry: ToolRegistry, *, skip_existing: bool = False) -> None:
    tool = FilesCopyTool()
    if skip_existing and registry.has_tool(tool.definition.name):
        return
    registry.register(tool)
