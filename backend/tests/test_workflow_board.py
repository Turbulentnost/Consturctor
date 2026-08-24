from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.agent_run import AgentRun
from app.models.trigger import AgentTrigger
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.workflows.board import get_workflow_board
from app.services.workflows.service import resume_auto_run, stop_auto_run


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _seed(db: Session) -> tuple[str, str]:
    user_id = "user-1"
    workflow_id = "wf-1"
    now = datetime.now(timezone.utc)
    db.add(AppUser(id=user_id, fio="Тест"))
    db.add(
        Workflow(
            id=workflow_id,
            user_id=user_id,
            title="Контроль сроков",
            phase="done",
            document_name="регламент.pdf",
            plan_json={"goal": "Следит за сроками проектов"},
        )
    )
    db.add(
        AgentTrigger(
            id="tr-1",
            owner_user_id=user_id,
            workflow_id=workflow_id,
            message="проверить сроки",
            fire_at=now + timedelta(hours=2),
            interval_seconds=24 * 3600,
            once=False,
            enabled=True,
        )
    )
    db.add(
        AgentRun(
            id="run-ok",
            workflow_id=workflow_id,
            user_id=user_id,
            message="проверить",
            status="ok",
            answer="всё в порядке",
            source="trigger",
            trigger_kind="interval",
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=2, minutes=50),
        )
    )
    db.commit()
    return user_id, workflow_id


def test_board_stats_and_past_event() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    now = datetime.now(timezone.utc)
    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=(now - timedelta(days=1)).isoformat(),
        window_to=(now + timedelta(days=8)).isoformat(),
    )
    assert board.stats.active_agents == 1
    assert board.stats.runs_today == 1
    assert board.agents[0].id == workflow_id
    assert board.agents[0].status == "active"
    assert "сроками" in board.agents[0].description
    past = [item for item in board.events if not item.is_future]
    assert len(past) == 1
    assert past[0].status == "ok"
    assert past[0].source == "schedule"


def test_board_expands_interval_across_week() -> None:
    db = _session()
    user_id, _workflow_id = _seed(db)
    now = datetime.now(timezone.utc)
    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=now.isoformat(),
        window_to=(now + timedelta(days=3, hours=3)).isoformat(),
    )
    future = [item for item in board.events if item.is_future]
    assert len(future) >= 2
    assert all(item.status == "scheduled" for item in future)


def test_short_interval_fills_window() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    now = datetime.now(timezone.utc)
    trigger.interval_seconds = 20 * 60
    trigger.fire_at = now + timedelta(minutes=5)
    db.commit()
    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=now.isoformat(),
        window_to=(now + timedelta(hours=2)).isoformat(),
    )
    future = [item for item in board.events if item.is_future and item.workflow_id == workflow_id]
    assert len(future) >= 4


def test_board_merges_overlapping_runs_into_one_slot() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    now = datetime.now(timezone.utc)
    slot = now.replace(second=0, microsecond=0) - timedelta(minutes=16)
    trigger.interval_seconds = 20 * 60
    trigger.fire_at = slot + timedelta(minutes=20)
    db.add(
        AgentRun(
            id="run-started",
            workflow_id=workflow_id,
            user_id=user_id,
            message="проверить",
            status="started",
            source="trigger",
            trigger_id="tr-1",
            trigger_kind="interval",
            started_at=slot,
        )
    )
    db.add(
        AgentRun(
            id="run-busy",
            workflow_id=workflow_id,
            user_id=user_id,
            message="проверить",
            status="error",
            answer="Cursor Agent занят",
            source="trigger",
            trigger_id="tr-1",
            trigger_kind="interval",
            started_at=slot + timedelta(minutes=1),
        )
    )
    db.add(
        AgentRun(
            id="run-again",
            workflow_id=workflow_id,
            user_id=user_id,
            message="проверить",
            status="started",
            source="trigger",
            trigger_id="tr-1",
            trigger_kind="interval",
            started_at=slot + timedelta(minutes=8),
        )
    )
    db.commit()
    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=(slot - timedelta(minutes=1)).isoformat(),
        window_to=(slot + timedelta(hours=1)).isoformat(),
    )
    items = [item for item in board.events if item.workflow_id == workflow_id]
    past = [item for item in items if not item.is_future]
    future = [item for item in items if item.is_future]
    assert len(past) == 1
    assert past[0].status == "running"
    assert past[0].run_id == "run-again"
    extra_starts = {
        (slot + timedelta(minutes=1)).isoformat(),
        (slot + timedelta(minutes=8)).isoformat(),
    }
    assert extra_starts.isdisjoint({item.start_at for item in items})
    assert len(future) >= 2
    assert all(item.status == "scheduled" for item in future)


def test_board_shows_missed_scheduled_slots() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    now = datetime.now(timezone.utc)
    trigger.interval_seconds = 20 * 60
    trigger.fire_at = now + timedelta(minutes=5)
    trigger.created_at = now - timedelta(hours=2)
    db.commit()
    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=(now - timedelta(hours=2)).isoformat(),
        window_to=(now + timedelta(hours=1)).isoformat(),
    )
    items = [item for item in board.events if item.workflow_id == workflow_id]
    missed = [item for item in items if item.status == "missed"]
    future = [item for item in items if item.is_future]
    assert missed
    assert all(not item.is_future for item in missed)
    assert all(item.run_id == "" for item in missed)
    assert all(item.source == "schedule" for item in missed)
    assert future
    assert all(item.status == "scheduled" for item in future)


def test_overdue_slot_stays_scheduled_and_is_next_run() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    now = datetime.now(timezone.utc)
    due = now - timedelta(minutes=4)
    trigger.interval_seconds = 20 * 60
    trigger.fire_at = due
    trigger.created_at = now - timedelta(hours=2)
    db.commit()
    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=(now - timedelta(hours=2)).isoformat(),
        window_to=(now + timedelta(hours=1)).isoformat(),
    )
    due_iso = due.isoformat()
    pending = [
        item
        for item in board.events
        if item.status == "scheduled"
        and abs(
            (
                datetime.fromisoformat(item.start_at.replace("Z", "+00:00")) - due
            ).total_seconds()
        )
        < 2
    ]
    assert len(pending) == 1
    assert pending[0].is_future is True
    assert board.stats.next_run_at
    next_stamp = datetime.fromisoformat(board.stats.next_run_at.replace("Z", "+00:00"))
    assert abs((next_stamp - due).total_seconds()) < 2
    agent = next(item for item in board.agents if item.id == workflow_id)
    assert agent.next_run_at
    older = [item for item in board.events if item.status == "missed"]
    assert older


def test_skipped_slot_stays_on_board_as_missed() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    now = datetime.now(timezone.utc)
    due = now - timedelta(minutes=1)
    trigger.interval_seconds = 20 * 60
    trigger.fire_at = due + timedelta(minutes=20)
    trigger.created_at = now - timedelta(hours=2)
    db.commit()
    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=(now - timedelta(hours=2)).isoformat(),
        window_to=(now + timedelta(hours=1)).isoformat(),
    )
    skipped = [
        item
        for item in board.events
        if item.workflow_id == workflow_id
        and abs(
            (
                datetime.fromisoformat(item.start_at.replace("Z", "+00:00")) - due
            ).total_seconds()
        )
        < 2
    ]
    assert len(skipped) == 1
    assert skipped[0].status == "missed"
    assert skipped[0].is_future is False
    assert skipped[0].run_id == ""


def test_event_trigger_has_no_future_slots() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    trigger.condition_text = "пришло новое резюме"
    trigger.interval_seconds = 0
    db.commit()
    now = datetime.now(timezone.utc)
    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=now.isoformat(),
        window_to=(now + timedelta(days=7)).isoformat(),
    )
    agent = next(item for item in board.agents if item.id == workflow_id)
    assert agent.trigger_kind == "event"
    assert "зависит от события" in agent.next_run_label
    assert [item for item in board.events if item.is_future] == []


def test_paused_skips_active_stats_and_future_slots() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    stop_auto_run(db, user_id=user_id, workflow_id=workflow_id)
    now = datetime.now(timezone.utc)
    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=(now - timedelta(days=1)).isoformat(),
        window_to=(now + timedelta(days=2)).isoformat(),
    )
    assert board.stats.active_agents == 0
    agent = next(item for item in board.agents if item.id == workflow_id)
    assert agent.status == "paused"
    assert [item for item in board.events if item.is_future] == []
    past = [item for item in board.events if not item.is_future]
    assert len(past) == 1
    resume_auto_run(db, user_id=user_id, workflow_id=workflow_id)
    board = get_workflow_board(db, user_id=user_id)
    agent = next(item for item in board.agents if item.id == workflow_id)
    assert agent.status == "active"
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    assert trigger.enabled is True


def test_stale_started_run_becomes_error_on_board() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    now = datetime.now(timezone.utc)
    db.add(
        AgentRun(
            id="run-stuck",
            workflow_id=workflow_id,
            user_id=user_id,
            message="проверить",
            status="started",
            source="trigger",
            trigger_id="tr-1",
            trigger_kind="interval",
            started_at=now - timedelta(hours=1),
        )
    )
    db.commit()
    board = get_workflow_board(db, user_id=user_id)
    stuck = next(item for item in board.events if item.run_id == "run-stuck")
    assert stuck.status == "error"
