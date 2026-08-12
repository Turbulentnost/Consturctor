from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.workflow.models import WorkflowRecord


def workflows_dir() -> Path:
    path = config.DESKTOP_ROOT / "data" / "workflows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def outputs_dir(workflow_id: str) -> Path:
    path = config.DESKTOP_ROOT / "data" / "outputs" / (workflow_id or "misc")
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_workflow(record: WorkflowRecord) -> Path:
    record.touch()
    path = workflows_dir() / f"{record.id}.json"
    path.write_text(
        json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_workflow(workflow_id: str) -> WorkflowRecord | None:
    path = workflows_dir() / f"{workflow_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return WorkflowRecord.from_dict(data)


def list_workflows() -> list[WorkflowRecord]:
    items: list[WorkflowRecord] = []
    for path in workflows_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                items.append(WorkflowRecord.from_dict(data))
        except (OSError, json.JSONDecodeError):
            continue
    items.sort(key=lambda w: w.updated_at, reverse=True)
    return items


def delete_workflow(workflow_id: str) -> bool:
    path = workflows_dir() / f"{workflow_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True
