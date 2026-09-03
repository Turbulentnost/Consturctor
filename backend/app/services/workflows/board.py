"""Aggregate agents, run history and upcoming schedule for the My Agents board."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.models.regulation import AgentDraft
from app.models.trigger import AgentTrigger
from app.models.workflow import Workflow
from app.schemas.workflow import BoardAgent, BoardStats, CalendarEvent, WorkflowBoard
from app.services.agent_runs import effective_run_status, fail_stale_started_runs
from app.services.triggers.service import (
    has_window,
    is_workflow_paused,
    parse_active_days,
    parse_skipped_slots,
    slot_key,
    windowed_slots_between,
    workflow_is_deleted,
)


def _stamp_iso(value: datetime | None) -> str:
    stamp = _as_utc(value)
    return stamp.isoformat() if stamp else ""

_MAX_SLOTS_PER_TRIGGER = 800
_EVENT_HORIZON = timedelta(days=40)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_dt(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _one_line(value: str, limit: int = 90) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _agent_description(row: Workflow) -> str:
    plan = row.plan_json if isinstance(row.plan_json, dict) else {}
    goal = str(plan.get("goal") or "").strip()
    if goal:
        return _one_line(goal)
    local = row.local_run if isinstance(row.local_run, dict) else {}
    draft = local.get("schedule_draft") if isinstance(local.get("schedule_draft"), dict) else {}
    draft_goal = str(draft.get("goal") or "").strip()
    if draft_goal:
        return _one_line(draft_goal)
    if (row.document_name or "").strip():
        return _one_line(row.document_name)
    return _one_line(row.notes or "")


def _run_event_status(status: str) -> str:
    raw = (status or "").strip().lower()
    if raw == "ok":
        return "ok"
    if raw == "error":
        return "error"
    if raw in {"canceled", "cancelled"}:
        return "canceled"
    return "running"


def _run_source(row: AgentRun) -> str:
    if (row.source or "") == "chat":
        return "manual"
    kind = (row.trigger_kind or "").strip()
    if kind == "event":
        return "event"
    return "schedule"


def _trigger_kind(row: AgentTrigger) -> str:
    if (row.condition_text or "").strip():
        return "event"
    if int(row.interval_seconds or 0) > 0:
        return "interval"
    return "datetime"


def _expand_slot_times(
    *,
    fire_at: datetime | None,
    interval_seconds: int,
    window_start: datetime,
    window_end: datetime,
    active_days: object = "",
    window_start_min: int | None = None,
    window_end_min: int | None = None,
) -> list[datetime]:
    origin = _as_utc(fire_at)
    if origin is None:
        return []
    interval = max(0, int(interval_seconds or 0))
    if interval > 0 and has_window(window_start_min, window_end_min):
        return windowed_slots_between(
            start=window_start,
            end=window_end,
            interval_seconds=interval,
            window_start_min=int(window_start_min),
            window_end_min=int(window_end_min),
            active_days=parse_active_days(active_days),
            max_slots=_MAX_SLOTS_PER_TRIGGER,
        )
    if interval <= 0:
        if window_start <= origin <= window_end:
            return [origin]
        return []
    cursor = origin
    guard = 0
    step = timedelta(seconds=interval)
    while cursor - step >= window_start and guard < _MAX_SLOTS_PER_TRIGGER:
        cursor = cursor - step
        guard += 1
    if cursor < window_start:
        steps = math.ceil((window_start - cursor).total_seconds() / interval)
        cursor = cursor + timedelta(seconds=steps * interval)
    times: list[datetime] = []
    days = parse_active_days(active_days)
    msk = timezone(timedelta(hours=3))
    while cursor <= window_end and len(times) < _MAX_SLOTS_PER_TRIGGER:
        if cursor >= window_start and (not days or cursor.astimezone(msk).weekday() in days):
            times.append(cursor)
        cursor = cursor + step
    return times


def _near_seconds(interval_seconds: int) -> int:
    interval = max(0, int(interval_seconds or 0))
    if interval <= 0:
        return 15 * 60
    return max(60, min(interval // 2, 10 * 60))


def _pick_slot_run(candidates: list[AgentRun]) -> AgentRun:
    def rank(row: AgentRun) -> tuple[int, datetime]:
        raw = (row.status or "").strip().lower()
        if raw in {"started", "running"}:
            tier = 4
        elif raw == "error":
            tier = 3
        elif raw == "ok":
            tier = 2
        elif raw in {"canceled", "cancelled"}:
            tier = 1
        else:
            tier = 0
        stamp = _as_utc(row.started_at) or datetime.min.replace(tzinfo=timezone.utc)
        return (tier, stamp)

    return max(candidates, key=rank)


def _cluster_runs(
    rows: list[AgentRun],
    *,
    interval_seconds: int,
) -> list[tuple[datetime, list[AgentRun]]]:
    span = timedelta(seconds=_near_seconds(interval_seconds))
    ordered = sorted(
        rows,
        key=lambda row: _as_utc(row.started_at) or datetime.min.replace(tzinfo=timezone.utc),
    )
    clusters: list[tuple[datetime, list[AgentRun]]] = []
    for row in ordered:
        stamp = _as_utc(row.started_at)
        if stamp is None:
            continue
        if clusters and stamp < clusters[-1][0] + span:
            clusters[-1][1].append(row)
            continue
        clusters.append((stamp, [row]))
    return clusters


def _slot_occupied(stamp: datetime, clusters: list[tuple[datetime, list[AgentRun]]], interval_seconds: int) -> bool:
    span = timedelta(seconds=_near_seconds(interval_seconds))
    for start, _rows in clusters:
        if start <= stamp < start + span:
            return True
        if stamp <= start < stamp + span:
            return True
    return False


def _is_manual_run(row: AgentRun) -> bool:
    return (row.source or "") == "chat"


def _event_from_run(
    *,
    workflow: Workflow,
    run: AgentRun,
    start_at: datetime,
    event_id: str = "",
    trigger_id: str = "",
    is_future: bool = False,
) -> CalendarEvent:
    subtitle = _one_line(run.answer or run.trigger_reason or run.message or "", 70)
    return CalendarEvent(
        id=event_id or f"run:{run.id}",
        workflow_id=workflow.id,
        title=workflow.title or "ИИ-агент",
        subtitle=subtitle,
        start_at=_stamp_iso(start_at),
        status=_run_event_status(
            effective_run_status(
                run.status or "",
                run.answer or "",
                in_flight=(run.status or "") in {"started", "running"} and run.finished_at is None,
            )
        ),
        source=_run_source(run),
        is_future=is_future,
        run_id=run.id,
        trigger_id=trigger_id or run.trigger_id or "",
    )


def _next_run_label(*, kind: str, next_at: datetime | None, paused: bool, condition: str) -> str:
    if kind == "event":
        text = (condition or "").strip() or "при наступлении события"
        return f"Триггер: {text}. Следующий запуск зависит от события"
    if paused:
        return "Приостановлен"
    if next_at is None:
        return "Следующий запуск не запланирован"
    return ""


def get_workflow_board(
    db: Session,
    *,
    user_id: str,
    window_from: str = "",
    window_to: str = "",
    workflow_id: str = "",
) -> WorkflowBoard:
    now = datetime.now(timezone.utc)
    fail_stale_started_runs(db, user_id=user_id)
    from app.services.workflows.service import repair_deleted_workflows

    repair_deleted_workflows(db, user_id=user_id)
    start = _parse_dt(window_from) or (now - timedelta(days=7))
    end = _parse_dt(window_to) or (now + _EVENT_HORIZON)
    if end < start:
        start, end = end, start
    wanted = (workflow_id or "").strip()

    workflows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id)
        .order_by(Workflow.updated_at.desc())
        .all()
    )
    published = [
        row
        for row in workflows
        if (row.phase or "") == "done" and not workflow_is_deleted(row)
    ]
    published_ids = [row.id for row in published]
    history_ids = published_ids
    wf_by_id = {row.id: row for row in published}

    triggers = list(
        db.execute(
            select(AgentTrigger).where(
                AgentTrigger.owner_user_id == user_id,
                AgentTrigger.workflow_id.in_(published_ids or ["__none__"]),
            )
        ).scalars().all()
    )
    triggers_by_wf: dict[str, list[AgentTrigger]] = {}
    for item in triggers:
        triggers_by_wf.setdefault(item.workflow_id, []).append(item)

    runs = list(
        db.execute(
            select(AgentRun)
            .where(
                AgentRun.user_id == user_id,
                AgentRun.workflow_id.in_(history_ids or ["__none__"]),
            )
            .order_by(AgentRun.started_at.desc())
        ).scalars().all()
    )
    last_run: dict[str, AgentRun] = {}
    for item in runs:
        if item.workflow_id not in last_run:
            last_run[item.workflow_id] = item

    agents: list[BoardAgent] = []
    events: list[CalendarEvent] = []
    next_candidates: list[datetime] = []

    for row in published:
        paused = is_workflow_paused(row.local_run)
        wf_triggers = triggers_by_wf.get(row.id) or []
        enabled = [item for item in wf_triggers if item.enabled]
        event_trigger = next((item for item in enabled if _trigger_kind(item) == "event"), None)
        timed = [item for item in enabled if _trigger_kind(item) != "event"]
        kind = "event" if event_trigger is not None and not timed else (
            _trigger_kind(timed[0]) if timed else ("event" if event_trigger is not None else "")
        )
        next_at: datetime | None = None
        for item in timed:
            stamp = _as_utc(item.fire_at)
            if stamp is None:
                continue
            if next_at is None or stamp < next_at:
                next_at = stamp
        if not paused and next_at is not None:
            next_candidates.append(next_at)
        last = last_run.get(row.id)
        last_status = (
            effective_run_status(
                last.status or "",
                last.answer or "",
                in_flight=(last.status or "") in {"started", "running"} and last.finished_at is None,
            )
            if last is not None
            else ""
        )
        status = "paused" if paused else ("needs_attention" if last_status == "error" else "active")
        condition = (event_trigger.condition_text if event_trigger is not None else "") or ""
        label = _next_run_label(kind=kind, next_at=next_at, paused=paused, condition=condition)
        summary = ""
        if kind == "event":
            summary = f"Триггер: {(condition or 'при наступлении события').strip()}"
        elif timed:
            if kind == "interval":
                seconds = int(timed[0].interval_seconds or 0)
                summary = f"По расписанию каждые {max(1, seconds // 60)} мин"
            else:
                summary = "По расписанию"
        agents.append(
            BoardAgent(
                id=row.id,
                kind="workflow",
                title=row.title or "ИИ-агент",
                description=_agent_description(row),
                status=status,
                last_run_at=_stamp_iso(last.started_at) if last is not None else "",
                last_run_status=last_status,
                next_run_at=_stamp_iso(next_at) if next_at is not None else "",
                next_run_label=label,
                trigger_summary=summary,
                trigger_kind=kind,
                paused=paused,
                phase=row.phase or "",
            )
        )

        if wanted and wanted != row.id:
            continue

        wf_runs: list[AgentRun] = []
        for run in runs:
            if run.workflow_id != row.id:
                continue
            stamp = _as_utc(run.started_at)
            if stamp is None or stamp < start or stamp > end:
                continue
            wf_runs.append(run)
        used_run_ids: set[str] = set()
        for item in timed:
            interval = int(item.interval_seconds or 0)
            scheduled_runs = [
                run
                for run in wf_runs
                if run.id not in used_run_ids
                and not _is_manual_run(run)
                and (not run.trigger_id or run.trigger_id == item.id)
            ]
            clusters = _cluster_runs(scheduled_runs, interval_seconds=interval)
            matched_clusters: set[int] = set()
            if not paused:
                earliest = start
                created = _as_utc(item.created_at)
                if created is not None and created > earliest:
                    earliest = created
                times = _expand_slot_times(
                    fire_at=item.fire_at,
                    interval_seconds=interval,
                    window_start=earliest,
                    window_end=end,
                    active_days=getattr(item, "active_days", ""),
                    window_start_min=getattr(item, "window_start_min", None),
                    window_end_min=getattr(item, "window_end_min", None),
                )
                skipped = parse_skipped_slots(getattr(item, "skipped_slots", None))
                if skipped:
                    times = [stamp for stamp in times if slot_key(stamp) not in skipped]
                grace = timedelta(seconds=min(120, interval if interval > 0 else 120))
                for stamp in times:
                    hit = next(
                        (
                            index
                            for index, cluster in enumerate(clusters)
                            if index not in matched_clusters
                            and _slot_occupied(stamp, [cluster], interval)
                        ),
                        None,
                    )
                    if hit is not None:
                        _slot_start, group = clusters[hit]
                        matched_clusters.add(hit)
                        pick = _pick_slot_run(group)
                        for run in group:
                            used_run_ids.add(run.id)
                        events.append(
                            _event_from_run(
                                workflow=row,
                                run=pick,
                                start_at=stamp,
                                event_id=f"slot:{item.id}:{int(stamp.timestamp())}",
                                trigger_id=item.id,
                            )
                        )
                        continue
                    current_fire = _as_utc(item.fire_at)
                    pending = bool(
                        current_fire is not None
                        and _slot_occupied(stamp, [(current_fire, [])], interval)
                    )
                    if pending:
                        events.append(
                            CalendarEvent(
                                id=f"trig:{item.id}:{int(stamp.timestamp())}",
                                workflow_id=row.id,
                                title=row.title or "ИИ-агент",
                                subtitle=_one_line(item.message or "Запланировано", 70),
                                start_at=_stamp_iso(stamp),
                                status="scheduled",
                                source="schedule",
                                is_future=True,
                                trigger_id=item.id,
                            )
                        )
                        continue
                    if current_fire is not None and stamp < current_fire:
                        events.append(
                            CalendarEvent(
                                id=f"trig:{item.id}:{int(stamp.timestamp())}",
                                workflow_id=row.id,
                                title=row.title or "ИИ-агент",
                                subtitle=_one_line(item.message or "Не запущен", 70),
                                start_at=_stamp_iso(stamp),
                                status="missed",
                                source="schedule",
                                is_future=False,
                                trigger_id=item.id,
                            )
                        )
                        continue
                    if stamp + grace >= now:
                        events.append(
                            CalendarEvent(
                                id=f"trig:{item.id}:{int(stamp.timestamp())}",
                                workflow_id=row.id,
                                title=row.title or "ИИ-агент",
                                subtitle=_one_line(item.message or "Запланировано", 70),
                                start_at=_stamp_iso(stamp),
                                status="scheduled",
                                source="schedule",
                                is_future=True,
                                trigger_id=item.id,
                            )
                        )
                        continue
                    events.append(
                        CalendarEvent(
                            id=f"trig:{item.id}:{int(stamp.timestamp())}",
                            workflow_id=row.id,
                            title=row.title or "ИИ-агент",
                            subtitle=_one_line(item.message or "Не запущен", 70),
                            start_at=_stamp_iso(stamp),
                            status="missed",
                            source="schedule",
                            is_future=False,
                            trigger_id=item.id,
                        )
                    )
            for index, (slot_start, group) in enumerate(clusters):
                if index in matched_clusters:
                    continue
                pick = _pick_slot_run(group)
                for run in group:
                    used_run_ids.add(run.id)
                events.append(
                    _event_from_run(
                        workflow=row,
                        run=pick,
                        start_at=slot_start,
                        event_id=f"slot:{item.id}:{int(slot_start.timestamp())}",
                        trigger_id=item.id,
                    )
                )

        for run in wf_runs:
            if run.id in used_run_ids:
                continue
            stamp = _as_utc(run.started_at)
            if stamp is None:
                continue
            events.append(_event_from_run(workflow=row, run=run, start_at=stamp))

    drafts = (
        db.query(AgentDraft)
        .filter(AgentDraft.user_id == user_id)
        .order_by(AgentDraft.updated_at.desc())
        .all()
    )
    for draft in drafts:
        suggestions = (draft.result_json or {}).get("agentSuggestions") or []
        first = next((item for item in suggestions if isinstance(item, dict)), {})
        description = str(first.get("description") or "").strip()
        if not description:
            parts = [part for part in (draft.position, draft.department) if (part or "").strip()]
            description = " · ".join(parts)
        title = (draft.title or "").strip()
        if not title and draft.position:
            title = f"ИИ-агент: {draft.position}"
        agents.append(
            BoardAgent(
                id=draft.id,
                kind="draft",
                title=title or "Черновик агента",
                description=_one_line(description),
                status="draft",
                next_run_label="Черновик",
                draft_id=draft.id,
            )
        )

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    runs_today = 0
    errors_today = 0
    for run in runs:
        stamp = _as_utc(run.started_at)
        if stamp is None or stamp < day_start or stamp >= day_end:
            continue
        runs_today += 1
        if (run.status or "") == "error":
            errors_today += 1

    upcoming = [stamp for stamp in next_candidates if stamp is not None]
    if not upcoming:
        for item in events:
            if str(item.status or "") != "scheduled":
                continue
            stamp = _parse_dt(item.start_at)
            if stamp is not None:
                upcoming.append(stamp)
    # Meetings from calendar.show_meetings are NOT mixed into the run calendar.
    # They belong to the agent's own answer as a mini calendar form (rendered in
    # the run feed from the tool result), so the shared "Календарь запусков"
    # stays a board of agent runs only.

    upcoming.sort()
    stats = BoardStats(
        active_agents=sum(
            1 for item in agents if item.kind == "workflow" and not item.paused
        ),
        runs_today=runs_today,
        errors_today=errors_today,
        needs_attention=sum(1 for item in agents if item.status == "needs_attention"),
        next_run_at=_stamp_iso(upcoming[0]) if upcoming else "",
    )
    events.sort(key=lambda item: item.start_at)
    return WorkflowBoard(stats=stats, agents=agents, events=events)
