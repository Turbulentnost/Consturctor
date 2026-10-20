"""Источники исполняемых инструментов: каждый провайдер отдаёт реализации со своими метаданными."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import BACKEND_ROOT
from app.tools.registry import Execution, Invoker, SideEffect, SourceProject


def relative_source(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        return Path(path).name


@dataclass
class ImplementedTool:
    name: str
    project: SourceProject
    description: str
    input_schema: dict
    execution: Execution
    source_path: str
    invoker: Invoker
    title: str = ""
    side_effect: SideEffect = "read"
    requires_approval: bool = False
    timeout_seconds: int | None = None
    runtime: str = ""
