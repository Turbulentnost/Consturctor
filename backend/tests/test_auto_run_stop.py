from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.agent_run import AgentRun
from app.models.notification import Notification
from app.models.trigger import AgentTrigger
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.notifications.service import clear_inbox, list_inbox
from app.services.triggers.service import cancel_triggers_for_workflow, due_commands
from app.services.workflows.board import get_workflow_board
from app.services.workflows.kpi_calc import list_due_workflows
from app.services.workflows.service import delete_workflow, list_workflows, stop_auto_run


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _seed(db: Session, *, enabled: bool = True) -> tuple[str, str]:
    user_id = "user-1"
    workflow_id = "wf-1"
    db.add(AppUser(id=user_id, fio="Тест"))
    db.add(
        Workflow(
            id=workflow_id,
            user_id=user_id,
            title="Контроль сроков",
            phase="done",
            local_run={
                "kpi": {
                    "tiles": [
                        {
                            "id": "ok_rate",
                            "next_run_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                        }
                    ]
                }
            },
        )
    )
    db.add(
        AgentTrigger(
            id="tr-1",
            owner_user_id=user_id,
            workflow_id=workflow_id,
            message="проверить сроки",
            fire_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            interval_seconds=900,
            once=False,
            enabled=enabled,
        )
    )
    db.add(
        AgentRun(
            id="run-1",
            workflow_id=workflow_id,
            user_id=user_id,
            message="прошлый запуск",
            status="ok",
            answer="готово",
            source="trigger",
            trigger_kind="interval",
            started_at=datetime.now(timezone.utc) - timedelta(hours=2),
            finished_at=datetime.now(timezone.utc) - timedelta(hours=1, minutes=50),
        )
    )
    db.commit()
    return user_id, workflow_id


def test_due_commands_skip_disabled_and_missing_workflow() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    assert [row.id for row in due_commands(db, user_id=user_id)] == ["tr-1"]

    cancel_triggers_for_workflow(db, user_id=user_id, workflow_id=workflow_id)
    assert due_commands(db, user_id=user_id) == []

    db.add(
        AgentTrigger(
            id="tr-orphan",
            owner_user_id=user_id,
            workflow_id="missing-wf",
            message="orphan",
            fire_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            enabled=True,
        )
    )
    db.commit()
    assert due_commands(db, user_id=user_id) == []


def test_stop_auto_run_disables_triggers_and_keeps_history() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    items = list_workflows(db, user_id=user_id)
    assert items[0].auto_run is True
    assert items[0].paused is False
    assert list_due_workflows(db)

    result = stop_auto_run(db, user_id=user_id, workflow_id=workflow_id)
    assert result.ok is True
    assert result.stopped >= 1
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    assert trigger.enabled is False
    assert due_commands(db, user_id=user_id) == []
    item = list_workflows(db, user_id=user_id)[0]
    assert item.auto_run is False
    assert item.paused is True
    assert list_due_workflows(db) == []
    assert db.get(AgentRun, "run-1") is not None


def test_delete_workflow_stops_schedule_but_keeps_run_history() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    now = datetime.now(timezone.utc)
    db.add(
        Notification(
            id="n-1",
            sender_user_id=user_id,
            recipient_user_id=user_id,
            title="Сводка",
            body="от агента",
            workflow_id=workflow_id,
            send_at=now,
        )
    )
    db.commit()
    assert list_inbox(db, user_id=user_id)[0].workflow_id == workflow_id

    delete_workflow(db, user_id=user_id, workflow_id=workflow_id)
    row = db.get(Workflow, workflow_id)
    assert row is not None
    assert bool((row.local_run or {}).get("deleted")) is True
    assert db.get(AgentTrigger, "tr-1") is None
    assert db.get(Notification, "n-1") is None
    assert db.get(AgentRun, "run-1") is not None
    assert due_commands(db, user_id=user_id) == []
    assert list_workflows(db, user_id=user_id) == []
    assert list_inbox(db, user_id=user_id) == []

    board = get_workflow_board(
        db,
        user_id=user_id,
        window_from=(now - timedelta(days=1)).isoformat(),
        window_to=(now + timedelta(days=1)).isoformat(),
    )
    assert board.agents == []
    past = [item for item in board.events if not item.is_future]
    assert len(past) == 1
    assert past[0].run_id == "run-1"
    assert [item for item in board.events if item.is_future] == []


def test_inbox_hides_link_to_missing_workflow() -> None:
    db = _session()
    user_id, _workflow_id = _seed(db)
    now = datetime.now(timezone.utc)
    db.add(
        Notification(
            id="n-orphan",
            sender_user_id=user_id,
            recipient_user_id=user_id,
            title="Старое",
            body="агент уже нет",
            workflow_id="deleted-wf",
            send_at=now,
        )
    )
    db.commit()
    items = list_inbox(db, user_id=user_id)
    assert items[0].id == "n-orphan"
    assert items[0].workflow_id == ""
    assert items[0].agent_deleted is True
    assert clear_inbox(db, user_id=user_id) == 1
    assert list_inbox(db, user_id=user_id) == []
