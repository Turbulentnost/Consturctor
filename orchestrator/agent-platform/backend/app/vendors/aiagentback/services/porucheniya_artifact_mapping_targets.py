from __future__ import annotations

import hashlib
from typing import Any


def task_mapping_target(task: dict[str, Any], *, index: int = 0) -> tuple[str, str]:
    """Build a stable public mapping target for a 1C activity/task."""
    task_kind = str(task.get("item_type") or "").strip()
    if task_kind not in {"poruchenie_task", "protocol_task"}:
        task_kind = "protocol_task" if task.get("task_id") else "poruchenie_task"

    if task_kind == "protocol_task":
        key = str(task.get("task_id") or task.get("protocol_item_number") or "").strip()
    else:
        key = str(task.get("line_number") or "").strip()
    if key:
        return task_kind, key

    stable = "|".join(
        [
            task_kind,
            str(task.get("activity") or "").strip(),
            str(task.get("responsible") or "").strip(),
            str(task.get("due_date") or "").strip(),
            str(index),
        ]
    )
    return task_kind, f"derived:{hashlib.sha1(stable.encode('utf-8')).hexdigest()[:16]}"
