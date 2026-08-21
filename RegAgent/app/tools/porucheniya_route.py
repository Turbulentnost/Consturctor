"""Маршрутизация поручений на OData, а не на COM."""

from __future__ import annotations

from typing import Any

_COM_ONEC = frozenset(
    {
        "onec.search_documents",
        "onec.get_document_card",
        "onec.search_tasks",
        "onec.get_task_card",
    }
)

_MARKERS = ("поручен", "тд_поручен", "td_poruchen")


def looks_like_porucheniya(*texts: str) -> bool:
    blob = " ".join(texts).casefold()
    return any(marker in blob for marker in _MARKERS)


def reroute_if_porucheniya(name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """COM-поиск поручений → onec.docflow_tasks (OData Document.ТД_Поручения)."""
    tool = (name or "").strip()
    args = dict(arguments or {})
    if tool == "onec.docflow_tasks" or tool not in _COM_ONEC:
        return tool, args
    parts = [tool]
    for value in args.values():
        if isinstance(value, (str, int, float)):
            parts.append(str(value))
    if not looks_like_porucheniya(*parts):
        return tool, args
    mapped = dict(args)
    if "limit" not in mapped and mapped.get("max_results") is not None:
        mapped["limit"] = mapped.pop("max_results")
    return "onec.docflow_tasks", mapped
