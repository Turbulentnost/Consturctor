from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.notification import Notification
from app.models.trigger import AgentTrigger
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.triggers.runner import execute_scheduled_agent_run
from app.services.triggers.service import (
    CHECK_INTERVAL,
    agent_run_task_id,
    claim_due_agent_jobs,
    claim_due_trigger,
    due_commands,
    kpi_calc_task_id,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _seed(db: Session) -> tuple[str, str]:
    user_id = "user-1"
    workflow_id = "wf-1"
    db.add(AppUser(id=user_id, fio="Тест"))
    db.add(Workflow(id=workflow_id, user_id=user_id, title="Контроль сроков", phase="done"))
    db.add(
        AgentTrigger(
            id="tr-1",
            owner_user_id=user_id,
            workflow_id=workflow_id,
            message="проверить сроки",
            fire_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            interval_seconds=900,
            once=False,
            enabled=True,
        )
    )
    db.commit()
    return user_id, workflow_id


def test_claim_due_trigger_only_one_winner() -> None:
    db = _session()
    user_id, _workflow_id = _seed(db)
    assert [row.id for row in due_commands(db, user_id=user_id)] == ["tr-1"]
    assert claim_due_trigger(db, "tr-1") is True
    assert claim_due_trigger(db, "tr-1") is False
    assert due_commands(db, user_id=user_id) == []


def test_claim_due_agent_jobs_returns_each_trigger_once() -> None:
    db = _session()
    user_id, _workflow_id = _seed(db)
    first = claim_due_agent_jobs(db, user_id=user_id)
    assert [row.id for row in first] == ["tr-1"]
    assert claim_due_agent_jobs(db, user_id=user_id) == []


def test_claim_again_after_check_interval() -> None:
    db = _session()
    user_id, _workflow_id = _seed(db)
    assert claim_due_trigger(db, "tr-1") is True
    row = db.get(AgentTrigger, "tr-1")
    assert row is not None
    row.last_checked_at = datetime.now(timezone.utc) - CHECK_INTERVAL - timedelta(seconds=1)
    db.commit()
    assert claim_due_trigger(db, "tr-1") is True


def test_agent_run_task_id_stable_inside_window() -> None:
    now = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)
    first = agent_run_task_id("tr-1", now=now)
    second = agent_run_task_id("tr-1", now=now + timedelta(seconds=10))
    later = agent_run_task_id("tr-1", now=now + CHECK_INTERVAL)
    assert first == second
    assert first != later
    assert first.startswith("agent-run:tr-1:")


def test_kpi_calc_task_id_includes_tiles() -> None:
    now = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)
    left = kpi_calc_task_id("wf-1", ["b", "a"], now=now)
    right = kpi_calc_task_id("wf-1", ["a", "b"], now=now)
    assert left == right
    assert "a,b" in left


def test_execute_scheduled_skips_paused() -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    row = db.get(Workflow, workflow_id)
    assert row is not None
    row.local_run = {"paused": True}
    db.commit()
    result = execute_scheduled_agent_run(db, trigger_id="tr-1")
    assert result["ok"] is False
    assert result["reason"] == "paused"


def test_execute_scheduled_skips_offline_and_notifies(monkeypatch) -> None:
    from app.services.notifications.service import list_inbox

    db = _session()
    user_id, workflow_id = _seed(db)
    monkeypatch.setattr("app.services.triggers.runner.is_user_online", lambda _user_id: False)
    monkeypatch.setattr("app.services.triggers.runner.current_session_id", lambda _user_id: "")
    monkeypatch.setattr("app.services.triggers.runner.run_agent_task", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")))
    result = execute_scheduled_agent_run(db, trigger_id="tr-1")
    assert result["ok"] is False
    assert result["reason"] == "offline"
    items = list_inbox(db, user_id=user_id)
    assert items
    assert "не запускал приложение" in items[0].body
    assert items[0].workflow_id == workflow_id
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    assert trigger.enabled is True
    assert trigger.fire_at is not None
    assert trigger.last_evidence and "не запускал приложение" in trigger.last_evidence


def test_execute_scheduled_defers_when_session_alive_without_toast(monkeypatch) -> None:
    from app.services.notifications.service import list_inbox

    db = _session()
    user_id, _workflow_id = _seed(db)
    monkeypatch.setattr("app.services.triggers.runner.is_user_online", lambda _user_id: False)
    monkeypatch.setattr("app.services.triggers.runner.current_session_id", lambda _user_id: "sid-alive")
    monkeypatch.setattr("app.services.triggers.runner.run_agent_task", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")))
    result = execute_scheduled_agent_run(db, trigger_id="tr-1")
    assert result["ok"] is False
    assert result["reason"] == "reconnecting"
    assert list_inbox(db, user_id=user_id) == []
    trigger = db.get(AgentTrigger, "tr-1")
    assert trigger is not None
    assert trigger.last_evidence and "ожидание подключения" in trigger.last_evidence


def test_execute_scheduled_runs_when_online(monkeypatch) -> None:
    db = _session()
    _seed(db)
    monkeypatch.setattr("app.services.triggers.runner.is_user_online", lambda _user_id: True)
    monkeypatch.setattr(
        "app.services.triggers.runner.check_trigger_condition",
        lambda *args, **kwargs: {"matched": True, "changed": "ok"},
    )
    monkeypatch.setattr(
        "app.services.triggers.runner.start_agent_run",
        lambda *args, **kwargs: SimpleNamespace(id="run-1"),
    )
    monkeypatch.setattr(
        "app.services.triggers.runner.run_agent_task",
        lambda *args, **kwargs: {"answer": "готово"},
    )
    monkeypatch.setattr("app.services.triggers.runner.finish_agent_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.triggers.runner.mark_fired",
        lambda *args, **kwargs: SimpleNamespace(id="tr-1"),
    )
    result = execute_scheduled_agent_run(db, trigger_id="tr-1")
    assert result["ok"] is True


def test_enqueue_due_agent_runs_calls_apply_async_once(monkeypatch) -> None:
    from sqlalchemy.pool import StaticPool

    from app.tasks import scheduled

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    seed_db = factory()
    _seed(seed_db)
    seed_db.close()

    queued: list[dict] = []
    monkeypatch.setattr(scheduled, "SessionLocal", factory)
    monkeypatch.setattr(
        scheduled.run_scheduled_agent,
        "apply_async",
        lambda *args, **kwargs: queued.append(kwargs) or SimpleNamespace(id="1"),
    )
    assert scheduled.enqueue_due_agent_runs() == 1
    assert queued[0]["args"] == ["tr-1"]
    assert queued[0]["task_id"].startswith("agent-run:tr-1:")
    assert scheduled.enqueue_due_agent_runs() == 0
    assert len(queued) == 1


def test_enqueue_due_kpi_calls_calc_once(monkeypatch) -> None:
    from app.tasks import scheduled

    queued: list[dict] = []
    db = _session()
    user_id = "user-1"
    workflow_id = "wf-kpi"
    db.add(AppUser(id=user_id, fio="Тест"))
    db.add(
        Workflow(
            id=workflow_id,
            user_id=user_id,
            title="KPI",
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
    db.commit()

    monkeypatch.setattr(scheduled, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        scheduled.calc_workflow_kpi,
        "apply_async",
        lambda *args, **kwargs: queued.append(kwargs) or SimpleNamespace(id="k"),
    )
    count = scheduled.enqueue_due_kpi()
    assert count == 1
    assert queued[0]["args"] == [workflow_id, ["ok_rate"]]
    assert queued[0]["task_id"].startswith("kpi-calc:wf-kpi:")


def test_notifications_ws_does_not_dispatch_triggers() -> None:
    from app.api.v1 import notifications
    from app.api.v1 import triggers

    assert not hasattr(triggers, "dispatch_due_triggers")
    assert "dispatch_due_triggers" not in notifications.__dict__
