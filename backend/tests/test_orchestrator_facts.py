from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.agent_run import AgentRun
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.orchestrator.facts import (
    WorkItem,
    compute_tile_updates,
    is_infra_text,
)
from app.services.orchestrator.ilchenko import ilchenko_tiles
from app.services.orchestrator.service import get_orchestrator


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _user(db: Session, user_id: str, fio: str) -> None:
    now = datetime.now(timezone.utc)
    db.add(AppUser(id=user_id, fio=fio, position="Помощник", created_at=now, updated_at=now))
    db.commit()


def _workflow(db: Session, user_id: str, workflow_id: str, title: str) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        Workflow(
            id=workflow_id,
            user_id=user_id,
            title=title,
            phase="done",
            plan_json={"goal": "Развернуть совещания и проконтролировать пакет"},
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()


def _run(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    run_id: str,
    status: str,
    answer: str,
    events: list | None = None,
    hours_ago: int = 2,
) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        AgentRun(
            id=run_id,
            workflow_id=workflow_id,
            user_id=user_id,
            message="запуск",
            status=status,
            answer=answer,
            source="chat",
            events_json=events or [],
            started_at=now - timedelta(hours=hours_ago),
            finished_at=now - timedelta(hours=hours_ago, minutes=-20),
        )
    )
    db.commit()


def test_infra_text_is_ignored() -> None:
    assert is_infra_text("Cursor API HTTP 401: Invalid User API Key")
    assert is_infra_text("Cursor SDK не отвечает")
    assert is_infra_text("Запуск не завершился за отведённое время.")
    assert not is_infra_text("Проверил СЗ и записал две встречи в календарь")


def test_compute_updates_skips_infra_and_marks_return() -> None:
    tiles = ilchenko_tiles()
    items = [
        WorkItem(
            workflow_id="wf-1",
            title="Развёртка плановых совещаний",
            status="ok",
            answer="Записал встречу по СЗ 000013243 в календарь",
            events_text="",
            source="run",
            tags={"meeting", "package", "instructions"},
        ),
        WorkItem(
            workflow_id="wf-1",
            title="Развёртка плановых совещаний",
            status="ok",
            answer="Пакет сдан, возврат на доработку по замечаниям",
            events_text="returned",
            source="run",
            tags={"meeting", "package", "returned"},
        ),
        WorkItem(
            workflow_id="wf-2",
            title="Развёртка внеплановых совещаний",
            status="error",
            answer="Не собрал пакет к заседанию",
            events_text="",
            source="run",
            tags={"meeting", "package"},
        ),
    ]
    updates = {item["id"]: item for item in compute_tile_updates(tiles, items)}
    assert updates["package_on_time"]["fact"]["value"] == 66.7
    assert updates["quality"]["fact"]["value"] == 33.3
    assert updates["quality"]["score_percent"] == 33.3
    assert "000013243" in updates["package_on_time"]["evidence"]


def test_get_orchestrator_writes_facts_from_agent_runs() -> None:
    db = _session()
    user_id = "A2DCC949FEDEC70D40318ABA83C618F4"
    _user(db, user_id, "Ильченко Екатерина Александровна")
    _workflow(db, user_id, "wf-meet", "Развёртка плановых совещаний")
    _run(
        db,
        user_id=user_id,
        workflow_id="wf-meet",
        run_id="run-ok",
        status="ok",
        answer="Проверил СЗ 000013233 и записал встречу в календарь",
    )
    _run(
        db,
        user_id=user_id,
        workflow_id="wf-meet",
        run_id="run-401",
        status="error",
        answer="Cursor API HTTP 401: Invalid User API Key",
    )
    snap = get_orchestrator(db, user_id=user_id, fio="Ильченко Екатерина Александровна")
    assert snap.needs_calc is False
    assert len(snap.tiles) == 4
    assert all(tile.fact.value == 100 for tile in snap.tiles)
    assert all(tile.score_percent == 100 for tile in snap.tiles)
    assert all(tile.color == "green" for tile in snap.tiles)
    assert "000013233" in (snap.tiles[0].evidence or "")


def test_no_work_runs_keeps_empty_fact() -> None:
    db = _session()
    user_id = "A2DCC949FEDEC70D40318ABA83C618F4"
    _user(db, user_id, "Ильченко Екатерина Александровна")
    _workflow(db, user_id, "wf-meet", "Развёртка плановых совещаний")
    snap = get_orchestrator(db, user_id=user_id, fio="Ильченко Екатерина Александровна")
    assert all(tile.fact.value is None for tile in snap.tiles)
    assert "прогонов" in (snap.tiles[0].evidence or "")
