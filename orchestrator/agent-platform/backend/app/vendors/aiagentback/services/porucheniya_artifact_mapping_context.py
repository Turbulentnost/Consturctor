from __future__ import annotations

import hashlib
import json
from typing import Any

from app.vendors.aiagentback.services.porucheniya_artifact_mapping_targets import task_mapping_target


_MAPPING_POLICY_VERSION = "author-scoped-shortlist-v6"


def document_mapping_context_fingerprint(document: dict[str, Any]) -> str:
    """Revision hash for fields that can change an attachment's task shortlist.

    A document lifecycle status is deliberately excluded: `Принято` or `ВРаботе`
    does not constitute a new executor response for a поручение.
    """

    document_ref = str(document.get("document_ref") or document.get("protocol_ref") or "").strip()
    tasks: list[dict[str, str]] = []
    for index, raw_task in enumerate(document.get("tasks") or [], start=1):
        if not isinstance(raw_task, dict):
            continue
        task_kind, task_key = task_mapping_target(raw_task, index=index)
        tasks.append(
            {
                "task_kind": task_kind,
                "task_key": task_key,
                "activity": str(raw_task.get("activity") or "").strip(),
                "responsible": str(raw_task.get("responsible") or "").strip(),
                "due_date": str(raw_task.get("due_date") or "").strip(),
                "comment": str(raw_task.get("comment") or "").strip(),
                "note": str(raw_task.get("note") or "").strip(),
            }
        )

    payload = {
        "mapping_policy_version": _MAPPING_POLICY_VERSION,
        "document_ref": document_ref,
        "tasks": sorted(tasks, key=lambda task: (task["task_kind"], task["task_key"])),
    }
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
