"""Каталог исполняемых инструментов стенда.

Реализации перенесены из Constructor (app/vendors/constructor) и AIAgentBack
(app/vendors/aiagentback). Карточка инструмента собирается из двух частей:
- реализация даёт LLM-описание, схему параметров, таймаут и исполнитель;
- паспорт (app/tools/passports.py) даёт группу и описание для человека.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

SideEffect = Literal["read", "create_draft", "write", "dangerous"]
SourceProject = Literal["NewConstructor", "AIAgentBack"]
# local — выполняется в процессе стенда; server — проксируется на backend Constructor.
Execution = Literal["local", "server"]
Invoker = Callable[[dict[str, Any]], Awaitable[Any]]


class Passport(BaseModel):
    """Человеческое описание инструмента и переопределения метаданных реализации."""

    model_config = ConfigDict(extra="forbid")

    name: str
    summary: str
    title: str = ""
    side_effect: SideEffect | None = None
    requires_approval: bool | None = None
    timeout_seconds: int | None = None
    runtime: str = ""
    requires: list[str] = Field(default_factory=list)
    replaces: list[str] = Field(default_factory=list)

    def __init__(self, name: str, /, **data: Any) -> None:
        super().__init__(name=name, **data)


class PassportGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    summary: str = ""
    requires: list[str] = Field(default_factory=list)
    tools: list[Passport] = Field(default_factory=list)


class ToolSource(BaseModel):
    project: SourceProject
    path: str


class ToolSpec(BaseModel):
    name: str
    title: str = ""
    group: str = ""
    summary: str = ""
    description: str = ""
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    execution: Execution = "local"
    runtime: str = ""
    side_effect: SideEffect = "read"
    requires_approval: bool = False
    timeout_seconds: int = 90
    requires: list[str] = Field(default_factory=list)
    source: ToolSource | None = None
    replaces: list[str] = Field(default_factory=list)
    available: bool = True
    unavailable_reason: str = ""


class ToolGroup(BaseModel):
    id: str
    title: str
    summary: str = ""
    order: int = 0
    requires: list[str] = Field(default_factory=list)


_TOOLS: dict[str, ToolSpec] = {}
_INVOKERS: dict[str, Invoker] = {}
_GROUPS: list[ToolGroup] = []


def register_tool(spec: ToolSpec, invoker: Invoker | None = None) -> None:
    if spec.name in _TOOLS:
        raise ValueError(f"tool already registered: {spec.name}")
    _TOOLS[spec.name] = spec
    if invoker is not None:
        _INVOKERS[spec.name] = invoker


def register_group(group: ToolGroup) -> None:
    if any(item.id == group.id for item in _GROUPS):
        raise ValueError(f"tool group already registered: {group.id}")
    _GROUPS.append(group)


def get_tool(name: str) -> ToolSpec | None:
    return _TOOLS.get(name)


def get_invoker(name: str) -> Invoker | None:
    return _INVOKERS.get(name)


def list_tools() -> list[ToolSpec]:
    return list(_TOOLS.values())


def list_groups() -> list[ToolGroup]:
    return sorted(_GROUPS, key=lambda item: (item.order, item.id))


def clear() -> None:
    _TOOLS.clear()
    _INVOKERS.clear()
    _GROUPS.clear()


def load_catalog() -> None:
    from app.tools.catalog import load

    load()
