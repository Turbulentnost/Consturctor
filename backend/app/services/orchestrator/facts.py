from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.agent_run import AgentRun
from app.models.orchestrator import UserOrchestrator
from app.models.workflow import Workflow
from app.services import agent_kpi

logger = logging.getLogger(__name__)

WINDOW_DAYS = 90
MAX_RUNS = 500
LAST_RESULT_PHASES = frozenset({"done", "tested", "executing"})

INFRA_MARKERS = (
    "invalid user api key",
    "cursor api http",
    "cursor sdk",
    "sdk не отвечает",
    "не отвечает",
    "не завершился за отвед",
    "cursor agent занят",
    "agent занят",
    "дождитесь завершения",
    "календарь не для записи",
    "запись в календарь недоступна",
    "неизвестное действие",
    "comconnector",
    "инструмент ещё не перевед",
)

MEETING_KEYS = (
    "совещани",
    "заседани",
    "пакет",
    "материал",
    "график",
    "слот",
    "календар",
    "outlook",
)
PROTOCOL_KEYS = ("протокол",)
INSTRUCTION_KEYS = ("поручен", "служебн", "сз ", "сз\n", "задач")
RETURN_KEYS = ("возврат", "на доработ", "по замечан", "returned")
LATE_KEYS = ("просроч", "после срока", "не в срок")

SZ_RE = re.compile(r"0000\d{5,6}")


@dataclass
class WorkItem:
    workflow_id: str
    title: str
    status: str
    answer: str
    events_text: str
    source: str
    started_at: datetime | None = None
    goal: str = ""
    tags: set[str] = field(default_factory=set)

    @property
    def blob(self) -> str:
        return " ".join(
            [
                self.title,
                self.goal,
                self.answer,
                self.events_text,
            ]
        ).casefold()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_infra_text(text: str) -> bool:
    blob = (text or "").casefold()
    if not blob.strip():
        return False
    if any(marker in blob for marker in INFRA_MARKERS):
        return True
    if "failed_validation" in blob and any(
        marker in blob for marker in ("outlook", "excel", "календар", "com ")
    ):
        return True
    return False


def _events_text(events: Any) -> str:
    if not isinstance(events, list):
        return ""
    parts: list[str] = []
    for event in events[:400]:
        if isinstance(event, dict):
            parts.append(str(event.get("type") or ""))
            parts.append(str(event.get("name") or ""))
            parts.append(str(event.get("text") or event.get("message") or event.get("content") or ""))
        elif event:
            parts.append(str(event))
    return " ".join(parts)


def _has_return(item: WorkItem) -> bool:
    blob = item.blob
    if "без возврат" in blob:
        return False
    return any(key in blob for key in RETURN_KEYS)


def _is_late(item: WorkItem) -> bool:
    return any(key in item.blob for key in LATE_KEYS)


def _classify(item: WorkItem) -> None:
    blob = item.blob
    if any(key in blob for key in MEETING_KEYS):
        item.tags.add("meeting")
        item.tags.add("package")
    if any(key in blob for key in PROTOCOL_KEYS):
        item.tags.add("protocol")
    if any(key in blob for key in INSTRUCTION_KEYS) or SZ_RE.search(item.answer or ""):
        item.tags.add("instructions")
    if _has_return(item):
        item.tags.add("returned")


def _window_days(tiles: list[dict[str, Any]]) -> int:
    for tile in tiles:
        measure = tile.get("measure") if isinstance(tile.get("measure"), dict) else {}
        params = measure.get("params") if isinstance(measure.get("params"), dict) else {}
        try:
            days = int(params.get("window_days") or 0)
        except (TypeError, ValueError):
            days = 0
        if days > 0:
            return days
    return WINDOW_DAYS


def collect_work_items(
    db: Session,
    *,
    user_id: str,
    now: datetime | None = None,
    window_days: int = WINDOW_DAYS,
) -> list[WorkItem]:
    now = now or _now()
    start = now - timedelta(days=max(1, window_days))
    workflows = list(db.query(Workflow).filter(Workflow.user_id == user_id).all())
    by_id = {row.id: row for row in workflows}
    runs = list(
        db.execute(
            select(AgentRun)
            .where(AgentRun.user_id == user_id)
            .order_by(AgentRun.started_at.desc())
            .limit(MAX_RUNS)
        )
        .scalars()
        .all()
    )
    items: list[WorkItem] = []
    used_workflows: set[str] = set()
    for run in runs:
        started = _as_aware(getattr(run, "started_at", None))
        if started is not None and started < start:
            continue
        status = str(getattr(run, "status", "") or "").strip().casefold()
        if status not in {"ok", "error"}:
            continue
        if getattr(run, "finished_at", None) is None:
            continue
        answer = str(getattr(run, "answer", "") or "")
        if is_infra_text(answer):
            continue
        workflow = by_id.get(str(getattr(run, "workflow_id", "") or ""))
        title = str(getattr(workflow, "title", "") or "") if workflow is not None else ""
        plan = workflow.plan_json if workflow is not None and isinstance(workflow.plan_json, dict) else {}
        goal = str(plan.get("goal") or "") if isinstance(plan, dict) else ""
        item = WorkItem(
            workflow_id=str(getattr(run, "workflow_id", "") or ""),
            title=title,
            goal=goal,
            status=status,
            answer=answer,
            events_text=_events_text(getattr(run, "events_json", None)),
            source="run",
            started_at=started,
        )
        _classify(item)
        items.append(item)
        if item.workflow_id:
            used_workflows.add(item.workflow_id)
    for workflow in workflows:
        if workflow.id in used_workflows:
            continue
        phase = str(workflow.phase or "").strip().casefold()
        if phase not in LAST_RESULT_PHASES:
            continue
        answer = str(workflow.last_result or "").strip()
        if not answer or is_infra_text(answer):
            continue
        plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
        item = WorkItem(
            workflow_id=workflow.id,
            title=str(workflow.title or ""),
            goal=str(plan.get("goal") or ""),
            status="ok",
            answer=answer,
            events_text="",
            source="last_result",
            started_at=_as_aware(getattr(workflow, "updated_at", None)),
        )
        if item.started_at is not None and item.started_at < start:
            continue
        _classify(item)
        items.append(item)
    return items


def _pick(items: list[WorkItem], *tags: str, fallback: tuple[str, ...] = ()) -> list[WorkItem]:
    matched = [item for item in items if item.tags.intersection(tags)]
    if matched:
        return matched
    if fallback:
        return [item for item in items if item.tags.intersection(fallback)]
    return list(items)


def _ratio(ok: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(100.0 * ok / total, 1)


def _sz_codes(items: list[WorkItem]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for item in items:
        for code in SZ_RE.findall(item.answer or ""):
            if code not in seen:
                seen.add(code)
                found.append(code)
    return found


def _success_counts(items: list[WorkItem]) -> tuple[int, int]:
    ok = sum(1 for item in items if item.status == "ok")
    return ok, len(items)


def bucket_for_tile(tile: dict[str, Any]) -> str:
    tid = str(tile.get("id") or "").strip()
    known = {
        "package_on_time": "package",
        "protocol_on_time": "protocol",
        "instructions": "instructions",
        "quality": "quality",
    }
    if tid in known:
        return known[tid]
    name = str(tile.get("name") or "").casefold()
    if "протокол" in name:
        return "protocol"
    if "поручен" in name or "реестр" in name:
        return "instructions"
    if "качеств" in name or "возврат" in name:
        return "quality"
    if "пакет" in name or "заседан" in name or "совеща" in name:
        return "package"
    return "success"


def _evidence(items: list[WorkItem], *, ok: int, total: int, extra: str = "") -> str:
    if total <= 0:
        return "Нет рабочих прогонов агентов за 90 дней (инфраструктурные ошибки не считаем)."
    codes = _sz_codes(items)
    parts = [
        f"По запускам и выводам ИИ-агентов: {ok} успешных из {total} рабочих прогонов."
    ]
    if codes:
        parts.append("В выводах служебные записки: " + ", ".join(codes[:8]) + ".")
    if extra:
        parts.append(extra)
    return " ".join(parts)


def compute_tile_updates(tiles: list[dict[str, Any]], items: list[WorkItem]) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        tid = str(tile.get("id") or "").strip()
        if not tid:
            continue
        bucket = bucket_for_tile(tile)
        extra = ""
        if bucket == "package":
            chosen = _pick(items, "package", "meeting")
            ok, total = _success_counts(chosen)
            extra = "Пакет/совещания: успех рабочего прогона агента."
        elif bucket == "protocol":
            chosen = _pick(items, "protocol", fallback=("meeting", "package"))
            ok, total = _success_counts(chosen)
            if not any("protocol" in item.tags for item in chosen):
                extra = "Отдельных протоколов в выводах нет, считаем по прогонам агентов совещаний."
            else:
                extra = "Протокол: успех рабочего прогона, где есть вывод про протокол."
        elif bucket == "instructions":
            chosen = _pick(items, "instructions", fallback=("meeting", "package"))
            late = [item for item in chosen if _is_late(item)]
            ok = sum(1 for item in chosen if item.status == "ok" and item not in late)
            total = len(chosen)
            extra = "Поручения/СЗ: успешный прогон и нет признака просрочки в выводе."
        elif bucket == "quality":
            chosen = _pick(items, "package", "protocol", "meeting") or list(items)
            returned = [item for item in chosen if _has_return(item)]
            ok = sum(1 for item in chosen if item.status == "ok" and item not in returned)
            total = len(chosen)
            extra = "Качество: рабочий прогон без возврата и без ошибки."
        else:
            chosen = list(items)
            ok, total = _success_counts(chosen)
            extra = "Факт по успешности рабочих прогонов агентов сотрудника."
        value = _ratio(ok, total)
        updates.append(
            {
                "id": tid,
                "fact": {"value": value, "unit": "%"},
                "score_percent": value,
                "evidence": _evidence(chosen, ok=ok, total=total, extra=extra),
            }
        )
    return updates


def apply_run_facts(
    db: Session,
    row: UserOrchestrator,
    *,
    user_id: str,
    now: datetime | None = None,
    force: bool = False,
    persist: bool = True,
) -> bool:
    now = now or _now()
    tiles = [dict(item) for item in (row.tiles or []) if isinstance(item, dict)]
    if not tiles:
        return False
    items = collect_work_items(db, user_id=user_id, now=now, window_days=_window_days(tiles))
    due = set(agent_kpi.due_tile_ids({"tiles": tiles}, now))
    missing = any(agent_kpi._as_float((item.get("fact") or {}).get("value")) is None for item in tiles)
    latest = max((item.started_at for item in items if item.started_at is not None), default=None)
    stale = False
    if latest is not None:
        for tile in tiles:
            stamp = agent_kpi._as_datetime(tile.get("updated_at"))
            if stamp is None or latest > stamp:
                stale = True
                break
    if not force and not due and not missing and not stale:
        return False
    updates = compute_tile_updates(tiles, items)
    due_ids = {str(item.get("id") or "") for item in tiles if item.get("id")}
    updated = agent_kpi.apply_calc_updates({"tiles": tiles}, updates, due_ids=due_ids, now=now)
    row.tiles = updated.get("tiles") or tiles
    if row.status == "calculating":
        row.status = "ready"
    row.calculating_at = None
    if persist:
        flag_modified(row, "tiles")
        db.commit()
        db.refresh(row)
    logger.info(
        "Orchestrator facts from agent runs user=%s items=%s tiles=%s",
        user_id,
        len(items),
        [item.get("id") for item in updates],
    )
    return True
