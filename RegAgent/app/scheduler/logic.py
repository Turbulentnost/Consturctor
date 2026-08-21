"""Расчёт next_run_at для запланированных задач (без UI)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.models import ScheduledTask, TriggerType

WEEKDAY_LABELS = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)


def parse_iso(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def interval_delta(config: dict[str, Any]) -> timedelta | None:
    minutes = int(config.get("interval_minutes") or 0)
    hours = int(config.get("interval_hours") or 0)
    if minutes <= 0 and hours <= 0:
        preset = str(config.get("preset") or "").strip()
        presets = {
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "2h": timedelta(hours=2),
        }
        return presets.get(preset)
    total = minutes + hours * 60
    if total <= 0:
        return None
    return timedelta(minutes=total)


def compute_next_run(
    task: ScheduledTask,
    *,
    now: datetime | None = None,
    after_run: bool = False,
) -> datetime | None:
    """Следующий запуск UTC. Для once после выполнения — None."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)

    trigger: TriggerType = task.trigger_type
    cfg = dict(task.trigger_config or {})

    if not task.enabled and not after_run:
        return parse_iso(task.next_run_at)

    if trigger == "once":
        if task.last_run_at or after_run:
            return None
        run_at = parse_iso(str(cfg.get("run_at") or task.next_run_at or ""))
        return run_at

    if trigger == "interval":
        delta = interval_delta(cfg)
        if delta is None:
            return None
        if after_run:
            return current + delta
        nxt = parse_iso(task.next_run_at) or (current + delta)
        while nxt <= current:
            nxt += delta
        return nxt

    if trigger == "daily":
        local_now = current.astimezone()
        hour = int(cfg.get("hour", 9))
        minute = int(cfg.get("minute", 0))
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if after_run or candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    if trigger == "weekly":
        local_now = current.astimezone()
        weekday = int(cfg.get("weekday", 0)) % 7
        hour = int(cfg.get("hour", 9))
        minute = int(cfg.get("minute", 0))
        days_ahead = (weekday - local_now.weekday()) % 7
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        candidate += timedelta(days=days_ahead)
        if after_run or candidate <= local_now:
            candidate += timedelta(days=7)
        return candidate.astimezone(timezone.utc)

    return None


def is_task_due(task: ScheduledTask, *, now: datetime | None = None) -> bool:
    if not task.enabled:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    nxt = parse_iso(task.next_run_at)
    if nxt is None:
        return False
    return nxt <= current.astimezone(timezone.utc)


def trigger_summary(task: ScheduledTask) -> str:
    cfg = dict(task.trigger_config or {})
    tt = task.trigger_type
    if tt == "once":
        run_at = parse_iso(str(cfg.get("run_at") or task.next_run_at or ""))
        if run_at:
            local = run_at.astimezone()
            return f"Разово {local.strftime('%d.%m.%Y %H:%M')}"
        return "Разово"
    if tt == "interval":
        delta = interval_delta(cfg)
        if delta is None:
            return "Интервал"
        total_min = int(delta.total_seconds() // 60)
        if total_min % 60 == 0 and total_min >= 60:
            h = total_min // 60
            return f"Каждые {h} ч."
        return f"Каждые {total_min} мин."
    if tt == "daily":
        hour = int(cfg.get("hour", 9))
        minute = int(cfg.get("minute", 0))
        return f"Ежедневно в {hour:02d}:{minute:02d}"
    if tt == "weekly":
        weekday = int(cfg.get("weekday", 0)) % 7
        hour = int(cfg.get("hour", 9))
        minute = int(cfg.get("minute", 0))
        label = WEEKDAY_LABELS[weekday] if 0 <= weekday < 7 else "день недели"
        return f"Каждый {label.lower()} в {hour:02d}:{minute:02d}"
    return tt
