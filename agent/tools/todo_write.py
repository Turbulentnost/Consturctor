"""In-memory todo list for multi-step tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.types import ToolResult


@dataclass
class TodoStore:
    items: list[dict[str, str]] = field(default_factory=list)


def todo_write(
    store: TodoStore,
    todos: list[dict[str, Any]] | None = None,
    merge: bool = True,
) -> ToolResult:
    tool = "todo_write"
    if todos is None:
        todos = []

    validated: list[dict[str, str]] = []
    for item in todos:
        todo_id = str(item.get("id", "")).strip()
        content = str(item.get("content", "")).strip()
        status = str(item.get("status", "pending")).strip()
        if not todo_id or not content:
            return ToolResult.failure(
                tool,
                "invalid_todo",
                "Each todo requires non-empty 'id' and 'content'.",
            )
        if status not in {"pending", "in_progress", "completed", "cancelled"}:
            return ToolResult.failure(
                tool,
                "invalid_status",
                f"Invalid status '{status}' for todo '{todo_id}'.",
            )
        validated.append({"id": todo_id, "content": content, "status": status})

    if merge:
        by_id = {t["id"]: t for t in store.items}
        for item in validated:
            by_id[item["id"]] = item
        store.items = list(by_id.values())
    else:
        store.items = validated

    return ToolResult.success(tool, {"todos": list(store.items), "count": len(store.items)})
