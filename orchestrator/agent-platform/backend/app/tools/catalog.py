"""Сборка каталога: реализации из провайдеров + паспорта из app/tools/passports.py.

В каталог попадают только инструменты с паспортом. Если паспорт есть, а реализация
не загрузилась (нет зависимости, ошибка импорта), инструмент остаётся в каталоге
с available=False и причиной — так видно, что сломалось, а не что пропало.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.config import settings
from app.tools.providers import ImplementedTool
from app.tools.registry import (
    ToolGroup,
    ToolSource,
    ToolSpec,
    clear,
    register_group,
    register_tool,
)

logger = logging.getLogger(__name__)

_loaded = False


def _providers() -> list[tuple[str, Callable[[], list[ImplementedTool]]]]:
    from app.tools.providers import aiagentback, constructor

    # Порядок важен: при совпадении имён побеждает реализация Constructor.
    return [("NewConstructor", constructor.discover), ("AIAgentBack", aiagentback.discover)]


def discover_implementations() -> tuple[dict[str, ImplementedTool], dict[str, str]]:
    found: dict[str, ImplementedTool] = {}
    failures: dict[str, str] = {}
    for project, discover in _providers():
        try:
            tools = discover()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tool provider %s failed", project)
            failures[project] = f"{type(exc).__name__}: {exc}"
            continue
        for tool in tools:
            found.setdefault(tool.name, tool)
    return found, failures


def load() -> None:
    global _loaded
    if _loaded:
        return
    from app.tools.passports import GROUPS

    implementations, failures = discover_implementations()
    described: set[str] = set()
    for index, group in enumerate(GROUPS):
        register_group(
            ToolGroup(
                id=group.id,
                title=group.title,
                summary=group.summary,
                order=(index + 1) * 10,
                requires=group.requires,
            )
        )
        for passport in group.tools:
            described.add(passport.name)
            tool = implementations.get(passport.name)
            spec = ToolSpec(
                name=passport.name,
                title=passport.title or (tool.title if tool else ""),
                group=group.id,
                summary=passport.summary,
                requires=[*group.requires, *passport.requires],
                replaces=passport.replaces,
            )
            if tool is None:
                reason = "; ".join(f"{name}: {error}" for name, error in failures.items())
                spec.available = False
                spec.unavailable_reason = reason or "реализация не найдена среди перенесённого кода"
                register_tool(spec)
                continue
            spec.description = tool.description
            spec.input_schema = tool.input_schema
            spec.execution = tool.execution
            spec.runtime = passport.runtime or tool.runtime
            spec.side_effect = passport.side_effect or tool.side_effect
            spec.requires_approval = (
                passport.requires_approval
                if passport.requires_approval is not None
                else tool.requires_approval
            )
            spec.timeout_seconds = (
                passport.timeout_seconds
                or tool.timeout_seconds
                or settings.tools_default_timeout_seconds
            )
            spec.source = ToolSource(project=tool.project, path=tool.source_path)
            register_tool(spec, tool.invoker)

    hidden = sorted(set(implementations) - described)
    if hidden:
        logger.info("Tools without passport are hidden: %s", ", ".join(hidden))
    _loaded = True


def unload() -> None:
    global _loaded
    clear()
    _loaded = False
