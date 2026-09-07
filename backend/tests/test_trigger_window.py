from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.trigger import AgentTrigger
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.triggers.service import (
    next_windowed_slot,
    skip_trigger_slot,
    slot_key,
    windowed_slots_between,
)
from app.services.workflows.board import _expand_slot_times


MSK = timezone(timedelta(hours=3))


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_windowed_slots_stay_inside_work_hours() -> None:
    start = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 3, 21, 0, tzinfo=timezone.utc)
    slots = windowed_slots_between(
        start=start,
        end=end,
        interval_seconds=10800,
        window_start_min=8 * 60,
        window_end_min=17 * 60,
        active_days={0, 1, 2, 3, 4},
    )
    local = [stamp.astimezone(MSK) for stamp in slots]
    assert [stamp.hour for stamp in local] == [8, 11, 14, 17]
    assert all(stamp.weekday() == 3 for stamp in local)


def test_expand_without_window_keeps_weekday_filter() -> None:
    origin = datetime(2026, 9, 3, 7, 23, tzinfo=timezone.utc)
    times = _expand_slot_times(
        fire_at=origin,
        interval_seconds=10800,
        window_start=datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 9, 8, 21, 0, tzinfo=timezone.utc),
        active_days="0,1,2,3,4",
    )
    assert times
    assert all(stamp.astimezone(MSK).weekday() < 5 for stamp in times)


def test_skip_trigger_slot_hides_current_fire() -> None:
    db = _session()
    user_id = "user-1"
    workflow_id = "wf-1"
    fire_at = datetime(2026, 9, 3, 5, 0, tzinfo=timezone.utc)
    db.add(AppUser(id=user_id, fio="Test"))
    db.add(Workflow(id=workflow_id, user_id=user_id, title="Planner", phase="done"))
    db.add(
        AgentTrigger(
            id="tr-skip",
            owner_user_id=user_id,
            workflow_id=workflow_id,
            message="plan",
            fire_at=fire_at,
            interval_seconds=10800,
            active_days="0,1,2,3,4",
            window_start_min=8 * 60,
            window_end_min=17 * 60,
            once=False,
            enabled=True,
            skipped_slots=[],
        )
    )
    db.commit()

    skip_trigger_slot(db, user_id=user_id, trigger_id="tr-skip", at=fire_at)
    row = db.get(AgentTrigger, "tr-skip")
    assert row is not None
    skipped = {str(item) for item in (row.skipped_slots or [])}
    assert skipped
    assert row.enabled is True
    nxt = next_windowed_slot(
        fire_at,
        interval_seconds=10800,
        window_start_min=8 * 60,
        window_end_min=17 * 60,
        active_days={0, 1, 2, 3, 4},
    )
    assert nxt is not None
    assert nxt.astimezone(MSK).hour == 11
