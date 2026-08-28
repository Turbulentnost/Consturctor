from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from app.orchestrator.models import MEETING_ID, READY, REVISION_ID, WAITING_HUMAN, ProcessInstance


def _root() -> Path:
    path = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "turbobot" / "orchestrator"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_path(user_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() else "_" for ch in (user_id or "local")) or "local"
    return _root() / f"{safe}.json"


def _parse(item: dict) -> ProcessInstance | None:
    instance_id = str(item.get("id") or "")
    definition_id = str(item.get("definition_id") or "")
    status = str(item.get("status") or "")
    if not instance_id or not definition_id or not status:
        return None
    events = item.get("events")
    return ProcessInstance(
        id=instance_id,
        definition_id=definition_id,
        status=status,
        waiting=int(item.get("waiting") or 0),
        updated_at=str(item.get("updated_at") or ""),
        events=list(events) if isinstance(events, list) else [],
    )


def _dump(instance: ProcessInstance) -> dict:
    return {
        "id": instance.id,
        "definition_id": instance.definition_id,
        "status": instance.status,
        "waiting": instance.waiting,
        "updated_at": instance.updated_at,
        "events": instance.events,
    }


def load_instances(user_id: str) -> list[ProcessInstance]:
    path = store_path(user_id)
    if not path.is_file():
        seeded = _seed_for(user_id)
        save_instances(user_id, seeded)
        return seeded
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _seed_for(user_id)
    rows = payload.get("instances") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return _seed_for(user_id)
    instances = [parsed for item in rows if isinstance(item, dict) and (parsed := _parse(item))]
    return instances or _seed_for(user_id)


def save_instances(user_id: str, instances: list[ProcessInstance]) -> None:
    path = store_path(user_id)
    try:
        path.write_text(
            json.dumps({"instances": [_dump(item) for item in instances]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        # Disk full: keep working from memory, do not crash login.
        return


def latest_by_definition(instances: list[ProcessInstance]) -> dict[str, ProcessInstance]:
    latest: dict[str, ProcessInstance] = {}
    for item in instances:
        current = latest.get(item.definition_id)
        if current is None or item.updated_at >= current.updated_at:
            latest[item.definition_id] = item
    return latest


def _seed_for(user_id: str) -> list[ProcessInstance]:
    from app.chat.test_user import is_local_test_user
    from app.orchestrator.kpi import has_position_kpi, seed_ilchenko_instances

    if has_position_kpi(user_id) or is_local_test_user(user_id):
        return seed_ilchenko_instances()
    return _seed()


def _seed() -> list[ProcessInstance]:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return [
        ProcessInstance(
            id=str(uuid4()),
            definition_id=REVISION_ID,
            status=WAITING_HUMAN,
            waiting=1,
            updated_at=now,
            events=[{"type": "seed", "status": WAITING_HUMAN, "at": now}],
        ),
        ProcessInstance(
            id=str(uuid4()),
            definition_id=MEETING_ID,
            status=READY,
            waiting=0,
            updated_at=now,
            events=[{"type": "seed", "status": READY, "at": now}],
        ),
    ]
