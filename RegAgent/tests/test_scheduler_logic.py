from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import ScheduledTask
from app.scheduler.logic import compute_next_run, format_iso, is_task_due, parse_iso, trigger_summary


def _utc(y, m, d, h=0, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_once_future_run():
    run_at = _utc(2026, 8, 22, 10, 0)
    task = ScheduledTask(
        card_id="c1",
        title="Test",
        prompt="Do it",
        trigger_type="once",
        trigger_config={"run_at": format_iso(run_at)},
        next_run_at=format_iso(run_at),
        enabled=True,
    )
    now = _utc(2026, 8, 21, 12, 0)
    assert is_task_due(task, now=now) is False
    nxt = compute_next_run(task, now=now)
    assert nxt == run_at


def test_once_after_run_disabled():
    run_at = _utc(2026, 8, 21, 9, 0)
    task = ScheduledTask(
        card_id="c1",
        trigger_type="once",
        trigger_config={"run_at": format_iso(run_at)},
        next_run_at=format_iso(run_at),
        last_run_at=format_iso(run_at),
        enabled=True,
    )
    assert compute_next_run(task, after_run=True) is None


def test_interval_advances():
    task = ScheduledTask(
        card_id="c1",
        trigger_type="interval",
        trigger_config={"preset": "15m"},
        next_run_at=format_iso(_utc(2026, 8, 21, 10, 0)),
        enabled=True,
    )
    now = _utc(2026, 8, 21, 10, 20)
    nxt = compute_next_run(task, now=now)
    assert nxt == _utc(2026, 8, 21, 10, 30)


def test_interval_after_run():
    task = ScheduledTask(
        card_id="c1",
        trigger_type="interval",
        trigger_config={"interval_minutes": 30},
        enabled=True,
    )
    ran = _utc(2026, 8, 21, 10, 0)
    task.last_run_at = format_iso(ran)
    nxt = compute_next_run(task, now=ran, after_run=True)
    assert nxt == _utc(2026, 8, 21, 10, 30)


def test_daily_next_slot():
    # 14:00 UTC = 17:00 MSK+3 in summer — use fixed offset
    tz = timezone(timedelta(hours=3))
    local_now = datetime(2026, 8, 21, 16, 0, tzinfo=tz)
    now = local_now.astimezone(timezone.utc)
    task = ScheduledTask(
        card_id="c1",
        trigger_type="daily",
        trigger_config={"hour": 18, "minute": 0},
        enabled=True,
    )
    nxt = compute_next_run(task, now=now)
    assert nxt is not None
    local_next = nxt.astimezone(tz)
    assert local_next.hour == 18
    assert local_next.minute == 0
    assert local_next.date() == local_now.date()


def test_weekly_next_slot():
    tz = timezone(timedelta(hours=3))
    # Thursday 2026-08-21
    local_now = datetime(2026, 8, 21, 10, 0, tzinfo=tz)
    now = local_now.astimezone(timezone.utc)
    task = ScheduledTask(
        card_id="c1",
        trigger_type="weekly",
        trigger_config={"weekday": 4, "hour": 9, "minute": 0},  # Friday
        enabled=True,
    )
    nxt = compute_next_run(task, now=now)
    assert nxt is not None
    local_next = nxt.astimezone(tz)
    assert local_next.weekday() == 4
    assert local_next.hour == 9


def test_is_task_due():
    due_at = _utc(2026, 8, 21, 10, 0)
    task = ScheduledTask(
        card_id="c1",
        trigger_type="once",
        trigger_config={"run_at": format_iso(due_at)},
        next_run_at=format_iso(due_at),
        enabled=True,
    )
    assert is_task_due(task, now=_utc(2026, 8, 21, 10, 1)) is True
    assert is_task_due(task, now=_utc(2026, 8, 21, 9, 59)) is False


def test_trigger_summary_interval():
    task = ScheduledTask(
        card_id="c1",
        trigger_type="interval",
        trigger_config={"preset": "1h"},
    )
    assert "ч." in trigger_summary(task)


def test_scheduled_task_repository_roundtrip(tmp_path):
    from app.storage.scheduled_repository import ScheduledTaskRepository

    repo = ScheduledTaskRepository(tmp_path / "cards.db")
    run_at = format_iso(_utc(2026, 9, 1, 8, 0))
    task = ScheduledTask(
        card_id="card-1",
        title="Daily check",
        prompt="Run check",
        trigger_type="daily",
        trigger_config={"hour": 8, "minute": 0},
        next_run_at=run_at,
        enabled=True,
    )
    repo.save(task)
    loaded = repo.get(task.id)
    assert loaded is not None
    assert loaded.title == "Daily check"
    assert loaded.trigger_type == "daily"
    counts = repo.count_by_card()
    assert counts.get("card-1") == 1
