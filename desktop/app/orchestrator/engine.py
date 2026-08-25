from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.orchestrator.models import (
    ACTIVE,
    COMPLETED,
    READY,
    WAITING_HUMAN,
    ProcessInstance,
)
from app.orchestrator.store import latest_by_definition, load_instances, save_instances


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(instance: ProcessInstance, event_type: str, status: str) -> None:
    instance.status = status
    instance.updated_at = _now()
    instance.events.append({"type": event_type, "status": status, "at": instance.updated_at})


def counts(instances: list[ProcessInstance]) -> tuple[int, int, int]:
    waiting = sum(1 for item in instances if item.status == WAITING_HUMAN)
    active = sum(1 for item in instances if item.status == ACTIVE)
    errors = sum(1 for item in instances if item.status == "ERROR")
    return waiting, active, errors


def start_process(user_id: str, definition_id: str) -> tuple[list[ProcessInstance], str | None]:
    instances = load_instances(user_id)
    latest = latest_by_definition(instances).get(definition_id)
    if latest is not None and latest.status in {ACTIVE, WAITING_HUMAN}:
        return instances, "Сначала закройте текущее решение по этому процессу."
    instance = ProcessInstance(
        id=str(uuid4()),
        definition_id=definition_id,
        status=READY,
        waiting=0,
        updated_at=_now(),
    )
    _append(instance, "start", ACTIVE)
    _append(instance, "agent_step", WAITING_HUMAN)
    instance.waiting = 1
    instances.append(instance)
    save_instances(user_id, instances)
    return instances, None


def decide(user_id: str, instance_id: str, approved: bool) -> tuple[list[ProcessInstance], str | None]:
    instances = load_instances(user_id)
    found = next((item for item in instances if item.id == instance_id), None)
    if found is None or found.status != WAITING_HUMAN:
        return instances, "Нет решения, которое можно закрыть."
    if approved:
        found.waiting = 0
        _append(found, "approved", COMPLETED)
    else:
        _append(found, "returned", ACTIVE)
        _append(found, "agent_step", WAITING_HUMAN)
        found.waiting = 1
    save_instances(user_id, instances)
    return instances, None
