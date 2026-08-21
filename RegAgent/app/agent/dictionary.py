"""Сопоставление system/entity/operation ↔ registry инструментов."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.tools.registry import list_tool_definitions

SYSTEM_ALIASES: dict[str, str] = {
    "outlook": "outlook",
    "почта": "outlook",
    "календарь": "outlook",
    "1c": "onec",
    "1с": "onec",
    "onec": "onec",
    "документооборот": "onec",
    "docflow": "onec",
}

ENTITY_TO_TOOLS: dict[str, list[str]] = {
    "mail": ["outlook.search_mail"],
    "calendar": ["outlook.read_calendar", "outlook.create_event"],
    "event": ["outlook.create_event"],
    "porucheniya": ["onec.docflow_tasks"],
    "docflow_tasks": ["onec.docflow_tasks"],
    "documents": ["onec.search_documents", "onec.get_document_card"],
    "tasks": ["onec.search_tasks", "onec.get_task_card"],
    "meeting_notes": ["onec.meeting_service_notes"],
}

OPERATION_TO_TOOL: dict[str, str] = {
    "search_mail": "outlook.search_mail",
    "read_calendar": "outlook.read_calendar",
    "create_event": "outlook.create_event",
    "docflow_tasks": "onec.docflow_tasks",
    "search_documents": "onec.search_documents",
    "get_document_card": "onec.get_document_card",
    "search_tasks": "onec.search_tasks",
    "get_task_card": "onec.get_task_card",
    "meeting_service_notes": "onec.meeting_service_notes",
}


@dataclass
class DictionaryValidation:
    ok: bool
    tools: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _registry_names() -> set[str]:
    return {d.name for d in list_tool_definitions()}


def normalize_system(value: str) -> str:
    key = (value or "").strip().casefold()
    return SYSTEM_ALIASES.get(key, key)


def resolve_tools(
    *,
    system: str = "",
    entity: str = "",
    operations: list[str] | None = None,
) -> list[str]:
    """Подобрать инструменты registry по system/entity/operations."""
    ops = [str(o).strip() for o in (operations or []) if str(o).strip()]
    sys_key = normalize_system(system)
    ent_key = (entity or "").strip().casefold().replace(" ", "_")
    out: list[str] = []

    for op in ops:
        if "." in op:
            out.append(op)
            continue
        mapped = OPERATION_TO_TOOL.get(op.casefold().replace(" ", "_"))
        if mapped:
            out.append(mapped)
        elif sys_key and op:
            candidate = f"{sys_key}.{op}"
            if candidate in _registry_names():
                out.append(candidate)

    if ent_key in ENTITY_TO_TOOLS:
        out.extend(ENTITY_TO_TOOLS[ent_key])

    if sys_key == "onec" and any("poruch" in o.casefold() or "docflow" in o for o in ops + [ent_key]):
        out.append("onec.docflow_tasks")

    deduped: list[str] = []
    seen: set[str] = set()
    for name in out:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def validate_dictionary(
    *,
    system: str = "",
    entity: str = "",
    operations: list[str] | None = None,
    tools: list[str] | None = None,
) -> DictionaryValidation:
    registry = _registry_names()
    resolved = list(tools or []) or resolve_tools(system=system, entity=entity, operations=operations)
    errors: list[str] = []
    warnings: list[str] = []

    for name in resolved:
        if name not in registry:
            errors.append(f"Неизвестный инструмент: {name}")

    blob = " ".join(resolved + list(operations or []) + [entity, system]).casefold()
    is_porucheniya = (
        any(m in blob for m in ("поручен", "docflow", "тд_поручен", "poruchen"))
        or ent_key in {"porucheniya", "docflow_tasks"}
    )
    if is_porucheniya:
        if "onec.docflow_tasks" not in resolved:
            warnings.append("Поручения должны идти через onec.docflow_tasks (OData)")
        com_hits = [t for t in resolved if t in {
            "onec.search_documents",
            "onec.search_tasks",
            "onec.get_document_card",
            "onec.get_task_card",
        }]
        if com_hits:
            errors.append(
                "Поручения документооборота: только onec.docflow_tasks, не COM search_*"
            )

    return DictionaryValidation(ok=not errors, tools=resolved, errors=errors, warnings=warnings)
