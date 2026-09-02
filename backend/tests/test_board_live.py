from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.trigger import AgentTrigger
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.models.agent_run import AgentRun
from app.services.agent_runs import finish_agent_run, start_agent_run
from app.services.workflows.board_live import push_board_updated, relay_board_message
from app.services.workflows.service import stop_auto_run


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
        )
    )
    db.add(
        AgentTrigger(
            id="tr-1",
            owner_user_id=user_id,
            workflow_id=workflow_id,
            message="проверить сроки",
            fire_at=now + timedelta(hours=1),
            interval_seconds=20 * 60,
            once=False,
            enabled=True,
        )
    )
    db.commit()
    return user_id, workflow_id


def test_push_board_updated_includes_stats_and_agents(monkeypatch) -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "app.services.workflows.board_live.hub.schedule_push",
        lambda uid, payload: sent.append((uid, payload)) or True,
    )
    monkeypatch.setattr("app.services.workflows.board_live._publish_redis", lambda *_a, **_k: False)
    payload = push_board_updated(db, user_id=user_id, workflow_id=workflow_id, status="started")
    assert payload is not None
    assert payload["type"] == "board_updated"
    assert payload["stats"]["active_agents"] == 1
    assert payload["agents"][0]["id"] == workflow_id
    assert sent and sent[0][0] == user_id


def test_start_and_finish_run_push_board(monkeypatch) -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    statuses: list[str] = []
    monkeypatch.setattr(
        "app.services.workflows.board_live.hub.schedule_push",
        lambda _uid, payload: statuses.append(str(payload.get("status") or "")) or True,
    )
    monkeypatch.setattr("app.services.workflows.board_live._publish_redis", lambda *_a, **_k: False)
    row = start_agent_run(db, user_id=user_id, workflow_id=workflow_id, message="проверить")
    assert "started" in statuses
    finish_agent_run(db, run_id=row.id, status="ok", answer="готово")
    assert "ok" in statuses


def test_finish_agent_run_keeps_canceled_status(monkeypatch) -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    monkeypatch.setattr("app.services.workflows.board_live.hub.schedule_push", lambda *_a, **_k: True)
    monkeypatch.setattr("app.services.workflows.board_live._publish_redis", lambda *_a, **_k: False)
    row = start_agent_run(db, user_id=user_id, workflow_id=workflow_id, message="проверить")
    finish_agent_run(db, run_id=row.id, status="cancelled", answer="Агент уже выполняется")
    stored = db.get(AgentRun, row.id)
    assert stored is not None
    assert stored.status == "canceled"
    assert "уже выполняется" in (stored.answer or "")


def test_finish_agent_run_empty_ok_becomes_canceled(monkeypatch) -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    monkeypatch.setattr("app.services.workflows.board_live.hub.schedule_push", lambda *_uid, **_k: True)
    monkeypatch.setattr("app.services.workflows.board_live._publish_redis", lambda *_a, **_k: False)
    row = start_agent_run(db, user_id=user_id, workflow_id=workflow_id, message="проверить")
    finish_agent_run(db, run_id=row.id, status="ok", answer="")
    stored = db.get(AgentRun, row.id)
    assert stored is not None
    assert stored.status == "canceled"


def test_stop_auto_run_pushes_paused(monkeypatch) -> None:
    db = _session()
    user_id, workflow_id = _seed(db)
    reasons: list[str] = []
    monkeypatch.setattr(
        "app.services.workflows.board_live.hub.schedule_push",
        lambda _uid, payload: reasons.append(str(payload.get("reason") or "")) or True,
    )
    monkeypatch.setattr("app.services.workflows.board_live._publish_redis", lambda *_a, **_k: False)
    stop_auto_run(db, user_id=user_id, workflow_id=workflow_id)
    assert "paused" in reasons


def test_relay_board_message_pushes_hub(monkeypatch) -> None:
    import asyncio

    sent: list[tuple[str, dict]] = []

    async def fake_push(user_id: str, payload: dict, client: str = "") -> bool:
        sent.append((user_id, payload))
        _ = client
        return True

    monkeypatch.setattr("app.services.workflows.board_live.hub.push", fake_push)
    asyncio.run(
        relay_board_message(
            '{"user_id":"user-1","payload":{"type":"board_updated","stats":{"active_agents":1}}}'
        )
    )
    assert sent[0][0] == "user-1"
    assert sent[0][1]["type"] == "board_updated"
