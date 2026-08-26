from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.chat.test_user import ILCHENKO_USER_ID, is_ilchenko_user
from app.orchestrator.models import COMPLETED, ERROR, MEETING_ID, READY, REVISION_ID, WAITING_HUMAN, ProcessInstance

_GREEN = "#08745F"
_YELLOW = "#C9A227"
_RED = "#C0392B"


@dataclass(frozen=True)
class KpiDefinition:
    number: int
    name: str
    target: float
    weight: float
    kind: str


@dataclass(frozen=True)
class KpiRow:
    number: int
    name: str
    target: float
    weight: float
    fact: float | None
    color: str


ILCHENKO_KPI: tuple[KpiDefinition, ...] = (
    KpiDefinition(1, "Своевременность пакета к заседаниям (СД + РК)", 95, 25, "package_on_time"),
    KpiDefinition(2, "Своевременность протоколов (СД + РК)", 95, 25, "protocol_on_time"),
    KpiDefinition(3, "Реестр и контроль исполнения поручений (СД + РК)", 95, 25, "instructions"),
    KpiDefinition(4, "Качество протокола и материалов (без возвратов по замечаниям)", 98, 25, "quality"),
)


def has_position_kpi(user_id: str = "", fio: str = "") -> bool:
    return user_id == ILCHENKO_USER_ID or is_ilchenko_user(user_id, fio)


def _ratio(ok: int, total: int) -> float | None:
    if total <= 0:
        return None
    return 100.0 * ok / total


def _closed(instances: list[ProcessInstance]) -> list[ProcessInstance]:
    return [item for item in instances if item.status == COMPLETED]


def _has_return(instance: ProcessInstance) -> bool:
    return any(str(event.get("type") or "") == "returned" for event in instance.events)


def _fact(kind: str, instances: list[ProcessInstance]) -> float | None:
    if kind in {"package_on_time", "protocol_on_time"}:
        done = [item for item in instances if item.status in {COMPLETED, ERROR}]
        return _ratio(sum(1 for item in done if item.status == COMPLETED), len(done))
    if kind == "instructions":
        started = [item for item in instances if item.status != READY]
        return _ratio(len(_closed(instances)), len(started))
    if kind == "quality":
        closed = _closed(instances)
        return _ratio(sum(1 for item in closed if not _has_return(item)), len(closed))
    return None


def _color(fact: float | None, target: float) -> str:
    if fact is None:
        return "#6B7773"
    if fact + 1e-9 >= target:
        return _GREEN
    if fact + 1e-9 >= target - 10:
        return _YELLOW
    return _RED


def score_rows(instances: list[ProcessInstance], definitions: tuple[KpiDefinition, ...] = ILCHENKO_KPI) -> list[KpiRow]:
    rows: list[KpiRow] = []
    for item in definitions:
        fact = _fact(item.kind, instances)
        rows.append(
            KpiRow(
                number=item.number,
                name=item.name,
                target=item.target,
                weight=item.weight,
                fact=fact,
                color=_color(fact, item.target),
            )
        )
    return rows


def weighted_score(rows: list[KpiRow]) -> float | None:
    total_weight = 0.0
    acc = 0.0
    for row in rows:
        if row.fact is None:
            continue
        acc += row.fact * row.weight
        total_weight += row.weight
    if total_weight <= 0:
        return None
    return acc / total_weight


def format_percent(value: float | None) -> str:
    if value is None:
        return "нет данных"
    return f"{value:.1f}%".replace(".0%", "%")


def seed_ilchenko_instances() -> list[ProcessInstance]:
    now = datetime.now(timezone.utc).isoformat()
    rows: list[ProcessInstance] = []

    def add(definition_id: str, status: str, events: list[dict], waiting: int = 0) -> None:
        rows.append(
            ProcessInstance(
                id=str(uuid4()),
                definition_id=definition_id,
                status=status,
                waiting=waiting,
                updated_at=now,
                events=events,
            )
        )

    for _ in range(8):
        add(MEETING_ID, COMPLETED, [{"type": "approved", "status": COMPLETED, "at": now}])
    for _ in range(7):
        add(REVISION_ID, COMPLETED, [{"type": "approved", "status": COMPLETED, "at": now}])
    add(
        MEETING_ID,
        COMPLETED,
        [
            {"type": "returned", "status": "ACTIVE", "at": now},
            {"type": "approved", "status": COMPLETED, "at": now},
        ],
    )
    add(REVISION_ID, WAITING_HUMAN, [{"type": "seed", "status": WAITING_HUMAN, "at": now}], waiting=1)
    add(MEETING_ID, READY, [{"type": "seed", "status": READY, "at": now}])
    return rows
