from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.orchestrator.ilchenko import ILCHENKO_SUMMARY, is_ilchenko, ilchenko_tiles
from app.services.orchestrator.service import (
    OrchestratorError,
    agent_fingerprint,
    apply_tile_updates,
    ensure_orchestrator,
    get_orchestrator,
    list_active_agent_briefs,
    list_due_orchestrators,
    orch_calc_task_id,
    save_formed,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _user(db: Session, user_id: str, fio: str, *, position: str = "Должность") -> None:
    now = datetime.now(timezone.utc)
    db.add(AppUser(id=user_id, fio=fio, position=position, created_at=now, updated_at=now))
    db.commit()


def _workflow(db: Session, user_id: str, workflow_id: str, title: str) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        Workflow(
            id=workflow_id,
            user_id=user_id,
            title=title,
            phase="done",
            plan_json={"goal": f"Цель {title}", "steps": [{"id": "s1", "title": "Шаг", "action": "Сделать"}]},
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()


def _sample_tiles() -> list[dict]:
    tiles = []
    for index, name in enumerate(["Сроки документов", "Качество ответов", "Контроль поручений"], start=1):
        tiles.append(
            {
                "id": f"tile_{index}",
                "name": name,
                "plan": {"label": "План", "value": 95, "unit": "%", "description": "норма"},
                "fact": {"label": "Факт", "value": None, "unit": "%", "description": "факт"},
                "measure": {"kind": f"tile_{index}", "params": {"weight": 33}, "formula": "ok/all"},
                "method": {
                    "plan_explanation": "План из должности.",
                    "fact_explanation": "Факт из Outlook и 1С.",
                    "score_explanation": "Оценка совпадает с фактом.",
                    "system": "count documents",
                    "how": "count",
                    "when": "раз в сутки",
                    "plan_update": "не менять",
                    "fact_update": "раз в сутки",
                    "percent_formula": "факт",
                    "green_min": 90,
                    "yellow_min": 70,
                    "schedule": {"kind": "interval", "interval_seconds": 86400},
                },
            }
        )
    return tiles


def test_is_ilchenko_by_id_and_fio() -> None:
    assert is_ilchenko(user_id="A2DCC949FEDEC70D40318ABA83C618F4")
    assert is_ilchenko(fio="Ильченко Екатерина Александровна")
    assert not is_ilchenko(user_id="other", fio="Анна Де Армас")


def test_ilchenko_seed_has_four_locked_tiles() -> None:
    tiles = ilchenko_tiles()
    assert len(tiles) == 4
    assert [item["id"] for item in tiles] == [
        "package_on_time",
        "protocol_on_time",
        "instructions",
        "quality",
    ]
    assert all(item["fact"]["value"] is None for item in tiles)
    assert tiles[0]["plan"]["value"] == 95
    assert tiles[3]["plan"]["value"] == 98
    assert tiles[0]["method"]["green_min"] == 95
    assert tiles[2]["method"]["schedule"]["interval_seconds"] == 6 * 3600
    assert tiles[0]["method"]["schedule"]["interval_seconds"] == 24 * 3600
    assert all(item["next_run_at"] for item in tiles)


def test_get_seeds_ilchenko_and_never_needs_form() -> None:
    db = _session()
    user_id = "A2DCC949FEDEC70D40318ABA83C618F4"
    _user(db, user_id, "Ильченко Екатерина Александровна")
    _workflow(db, user_id, "wf-1", "Ревизионная комиссия")
    first = get_orchestrator(db, user_id=user_id, fio="Ильченко Екатерина Александровна")
    assert first.locked is True
    assert first.needs_form is False
    assert len(first.tiles) == 4
    assert first.summary == ILCHENKO_SUMMARY
    assert first.needs_calc is True
    _workflow(db, user_id, "wf-2", "Новый агент")
    second = get_orchestrator(db, user_id=user_id, fio="Ильченко Екатерина Александровна")
    assert second.needs_form is False
    assert [tile.id for tile in second.tiles] == [tile.id for tile in first.tiles]


def test_ilchenko_save_formed_rejected() -> None:
    db = _session()
    user_id = "user-ilchenko"
    _user(db, user_id, "Ильченко Екатерина Александровна")
    _workflow(db, user_id, "wf-1", "Агент")
    get_orchestrator(db, user_id=user_id, fio="Ильченко Екатерина Александровна")
    try:
        save_formed(db, user_id=user_id, tiles=_sample_tiles(), fio="Ильченко Екатерина Александровна")
        raise AssertionError("expected OrchestratorError")
    except OrchestratorError as exc:
        assert exc.status_code == 409


def test_other_user_needs_form_then_fingerprint_change() -> None:
    db = _session()
    user_id = "user-2"
    _user(db, user_id, "Петров Петр")
    empty = get_orchestrator(db, user_id=user_id, fio="Петров Петр")
    assert empty.needs_form is False
    assert empty.status == "empty"
    _workflow(db, user_id, "wf-a", "Контроль сроков")
    waiting = get_orchestrator(db, user_id=user_id, fio="Петров Петр")
    assert waiting.needs_form is True
    formed = save_formed(
        db,
        user_id=user_id,
        tiles=_sample_tiles(),
        summary="KPI сотрудника",
        fio="Петров Петр",
    )
    assert formed.needs_form is False
    assert formed.status == "ready"
    assert len(formed.tiles) == 3
    row = db.get(Workflow, "wf-a")
    assert row is not None
    row.title = "Контроль сроков v2"
    db.commit()
    changed = get_orchestrator(db, user_id=user_id, fio="Петров Петр")
    assert changed.needs_form is True
    assert changed.current_fingerprint != changed.source_fingerprint


def test_paused_agent_excluded_from_fingerprint() -> None:
    db = _session()
    user_id = "user-3"
    _user(db, user_id, "Сидоров")
    _workflow(db, user_id, "wf-live", "Живой")
    _workflow(db, user_id, "wf-pause", "На паузе")
    paused = db.get(Workflow, "wf-pause")
    assert paused is not None
    paused.local_run = {"paused": True}
    db.commit()
    briefs = list_active_agent_briefs(db, user_id)
    assert [item["id"] for item in briefs] == ["wf-live"]
    assert agent_fingerprint(briefs) == agent_fingerprint([briefs[0]])


def test_ensure_sets_forming_and_calc_lock() -> None:
    db = _session()
    user_id = "user-4"
    _user(db, user_id, "Иванов")
    _workflow(db, user_id, "wf-1", "Агент")
    forming = ensure_orchestrator(db, user_id=user_id, mode="form", fio="Иванов")
    assert forming.status == "forming"
    save_formed(db, user_id=user_id, tiles=_sample_tiles(), fio="Иванов")
    calc = ensure_orchestrator(db, user_id=user_id, mode="calc", fio="Иванов")
    assert calc.status == "calculating"
    assert calc.needs_calc is False


def test_due_list_and_apply_updates() -> None:
    db = _session()
    user_id = "user-5"
    _user(db, user_id, "Иванов")
    _workflow(db, user_id, "wf-1", "Агент")
    save_formed(db, user_id=user_id, tiles=_sample_tiles(), fio="Иванов")
    due = list_due_orchestrators(db)
    assert len(due) == 1
    _row, tile_ids = due[0]
    assert set(tile_ids) == {"tile_1", "tile_2", "tile_3"}
    updated = apply_tile_updates(
        db,
        user_id=user_id,
        fio="Иванов",
        updates=[
            {
                "id": "tile_1",
                "fact": {"value": 100, "unit": "%"},
                "score_percent": 100,
                "evidence": "2 из 2 вовремя",
            }
        ],
    )
    assert updated.tiles[0].fact.value == 100
    assert updated.tiles[0].score_percent == 100
    assert updated.tiles[0].color == "green"
    later = list_due_orchestrators(db, now=datetime.now(timezone.utc) + timedelta(seconds=30))
    assert later == []


def test_empty_user_without_agents_does_not_form() -> None:
    db = _session()
    user_id = "user-6"
    _user(db, user_id, "Без агентов")
    ensured = ensure_orchestrator(db, user_id=user_id, mode="form", fio="Без агентов")
    assert ensured.status == "empty"
    assert ensured.needs_form is False
    assert ensured.tiles == []


def test_form_prompt_mentions_employee_not_agent_runs() -> None:
    db = _session()
    user_id = "user-7"
    _user(db, user_id, "Смирнов", position="Секретарь")
    _workflow(db, user_id, "wf-1", "Пакет к заседанию")
    snap = get_orchestrator(db, user_id=user_id, fio="Смирнов", position="Секретарь")
    assert snap.needs_form is True
    assert "сотрудника" in snap.form_prompt.casefold() or "должности" in snap.form_prompt.casefold()
    assert "success_rate" in snap.form_prompt


def test_dispatch_due_orchestrator_pushes_desktop_command(monkeypatch) -> None:
    from app.models.orchestrator import UserOrchestrator
    from app.services.orchestrator.service import dispatch_due_orchestrator

    db = _session()
    user_id = "user-8"
    _user(db, user_id, "Иванов")
    _workflow(db, user_id, "wf-1", "Агент")
    save_formed(db, user_id=user_id, tiles=_sample_tiles(), fio="Иванов")
    row = db.query(UserOrchestrator).filter(UserOrchestrator.user_id == user_id).one()
    pushed: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "app.services.desktop_commands.push_desktop_command",
        lambda uid, payload: pushed.append((uid, payload)) or True,
    )
    assert dispatch_due_orchestrator(db, row, ["tile_1"]) is True
    assert pushed[0][0] == user_id
    assert pushed[0][1]["type"] == "calc_orchestrator"
    assert pushed[0][1]["tile_ids"] == ["tile_1"]


def test_orch_calc_task_id_stable() -> None:
    now = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)
    left = orch_calc_task_id("u1", ["b", "a"], now=now)
    right = orch_calc_task_id("u1", ["a", "b"], now=now)
    assert left == right
    assert "a,b" in left
