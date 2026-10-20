from __future__ import annotations

import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.jwt import AuthContext
from app.db.base import Base
from app.models.position_kpi import (
    PositionKpiDailyReport,
    PositionKpiDailyRun,
    PositionKpiMetric,
    PositionKpiModule,
    PositionKpiProfile,
    PositionKpiSubjectFact,
)
from app.services.position_kpi import daily_run
from app.services.position_kpi.daily import _store_subject, subject_key

DAY = date(2026, 10, 16)
ASSISTANT = "Помощник руководителя"
ENGINEER = "Ведущий инженер"
CLERK = "Делопроизводитель"


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    for pid, name, dept, with_module in (
        ("p-assistant", ASSISTANT, "Дирекция", True),
        ("p-engineer", ENGINEER, "Цех 1", True),
        ("p-clerk", CLERK, "Канцелярия", False),
    ):
        db.add(PositionKpiProfile(id=pid, position_name=name, department=dept, source_import_id="imp"))
        db.add(
            PositionKpiMetric(
                id=f"{pid}-m1",
                profile_id=pid,
                code="m1",
                name="Сроки",
                sort_order=1,
                weight=60,
                formula_kind="ratio",
            )
        )
        db.add(
            PositionKpiMetric(
                id=f"{pid}-m2",
                profile_id=pid,
                code="m2",
                name="Качество",
                sort_order=2,
                weight=40,
                formula_kind="ratio",
            )
        )
        if with_module:
            db.add(
                PositionKpiModule(
                    id=f"{pid}-mod",
                    profile_id=pid,
                    metric_code="m1",
                    module_name=f"kpi.generated.{pid.replace('-', '_')}_m1",
                    source="def run():\n    return {}\n",
                )
            )
    db.commit()
    return db


def _auth(user_id: str = "u1", position: str = ASSISTANT, fio: str = "Иванова Анна Сергеевна") -> AuthContext:
    return AuthContext(user_id=user_id, fio=fio, position=position, department="Дирекция")


def test_own_claim_is_exclusive_and_stale_claim_is_taken_over() -> None:
    db = _session()
    first = daily_run.claim(db, _auth("u1"), "own", day=DAY)
    assert first["granted"] is True
    assert first["profiles"][0]["profile_id"] == "p-assistant"

    other = daily_run.claim(db, _auth("u2", fio="Петрова Ольга"), "own", day=DAY)
    assert other["granted"] is False
    assert daily_run.today_status(db, _auth("u2"), day=DAY)["status"] == "running_elsewhere"
    assert daily_run.today_status(db, _auth("u1"), day=DAY)["status"] == "running_here"

    row = db.scalar(select(PositionKpiDailyRun).where(PositionKpiDailyRun.profile_id == "p-assistant"))
    row.claimed_at = datetime.now(timezone.utc) - daily_run.CLAIM_TTL - timedelta(minutes=1)
    db.commit()
    assert daily_run.today_status(db, _auth("u2"), day=DAY)["status"] == "missing"
    retaken = daily_run.claim(db, _auth("u2", fio="Петрова Ольга"), "own", day=DAY)
    assert retaken["granted"] is True


def test_others_claim_skips_own_and_positions_without_modules() -> None:
    db = _session()
    result = daily_run.claim(db, _auth(), "others", day=DAY)
    assert [item["profile_id"] for item in result["profiles"]] == ["p-engineer"]
    assert result["skipped"] == ["p-clerk"]
    clerk = daily_run._run_row(db, "p-clerk", DAY)
    assert clerk is not None and clerk.status == "skipped"
    again = daily_run.claim(db, _auth("u2"), "others", day=DAY)
    assert again["profiles"] == []
    status = daily_run.today_status(db, _auth("u3", position=CLERK), day=DAY)
    assert status["status"] == "no_modules"


def test_publish_stores_tiles_and_report_then_status_is_ready() -> None:
    db = _session()
    auth = _auth()
    daily_run.claim(db, auth, "own", day=DAY)
    xlsx = b"PK\x03\x04fake-xlsx"
    result = daily_run.publish(
        db,
        auth,
        {
            "profile_id": "p-assistant",
            "month": "2026-10",
            "status": "done",
            "people": [
                {
                    "fio": "Иванова Анна Сергеевна",
                    "status": "ok",
                    "report_base64": base64.b64encode(xlsx).decode("ascii"),
                    "report_filename": "ИЦПП_Иванова_2026-10.xlsx",
                    "metrics": [
                        {"metric_code": "m2", "output": '{"fact_pct": 80, "score_pct": 80, "contrib_pct": 32}'},
                        {
                            "metric_code": "m1",
                            "output": "считаю...\n{\"fact_pct\": 95.5, \"score_pct\": 100, \"contrib_pct\": 60}",
                        },
                        {"metric_code": "zz", "output": "{}"},
                    ],
                }
            ],
        },
        day=DAY,
    )
    assert result["subjects"] == 1
    assert result["reports"] == 1
    assert result["unknown_metric_codes"] == ["zz"]

    fact = db.scalar(select(PositionKpiSubjectFact))
    assert fact.subject == subject_key("Иванова Анна Сергеевна")
    assert fact.period_from == date(2026, 10, 1) and fact.period_to == date(2026, 10, 31)
    tiles = fact.payload["tiles"]
    assert [tile["code"] for tile in tiles] == ["m1", "m2"]
    assert tiles[0]["fact"] == 95.5 and tiles[1]["contrib"] == 32
    assert fact.payload["source"] == daily_run.AGENT_SOURCE
    assert [item["metric_code"] for item in fact.payload["modules"]] == ["m2", "m1"]
    assert "95.5" in str(fact.payload["modules"][1]["output"])

    report = db.scalar(select(PositionKpiDailyReport))
    assert report.content == xlsx
    assert daily_run.own_report(db, auth, day=DAY).filename == "ИЦПП_Иванова_2026-10.xlsx"

    status = daily_run.today_status(db, auth, day=DAY)
    assert status["status"] == "ready"
    assert status["report_available"] is True
    assert status["own_facts"] is True


def test_publish_reads_fact_from_module_stdout() -> None:
    db = _session()
    auth = _auth()
    stdout = (
        "Показатель: Сроки\nВес: 60%\nПлан: 95.0\nФакт: 83.33\n"
        "Выполнение: 87.72%\nВклад: 21.93%\n"
    )
    daily_run.publish(
        db,
        auth,
        {
            "profile_id": "p-assistant",
            "month": "2026-10",
            "status": "done",
            "people": [{"fio": auth.fio, "metrics": [{"metric_code": "m1", "output": stdout}]}],
        },
        day=DAY,
    )
    tile = db.scalar(select(PositionKpiSubjectFact)).payload["tiles"][0]
    assert tile["fact"] == 83.33
    assert tile["score"] == 87.72
    assert tile["contrib"] == 21.93


def test_backend_recompute_does_not_overwrite_agent_tiles() -> None:
    db = _session()
    auth = _auth()
    daily_run.publish(
        db,
        auth,
        {
            "profile_id": "p-assistant",
            "status": "done",
            "people": [{"fio": auth.fio, "metrics": [{"metric_code": "m1", "output": {"fact_pct": 70}}]}],
        },
        day=DAY,
    )
    profile = db.get(PositionKpiProfile, "p-assistant")
    _store_subject(
        db,
        profile=profile,
        subject=subject_key(auth.fio),
        subject_fio=auth.fio,
        as_of=DAY,
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 31),
        payload={"tiles": []},
        computed_at=datetime.now(timezone.utc),
    )
    fact = db.scalar(select(PositionKpiSubjectFact))
    assert fact.payload["source"] == daily_run.AGENT_SOURCE
    assert fact.payload["tiles"][0]["fact"] == 70


def test_failed_publish_needs_explicit_retry() -> None:
    db = _session()
    auth = _auth()
    daily_run.claim(db, auth, "own", day=DAY)
    daily_run.publish(db, auth, {"profile_id": "p-assistant", "status": "failed", "error": "1С не ответила"}, day=DAY)
    status = daily_run.today_status(db, auth, day=DAY)
    assert status["status"] == "failed"
    assert status["run"]["error"] == "1С не ответила"
    assert daily_run.claim(db, auth, "own", day=DAY)["granted"] is False
    assert daily_run.claim(db, auth, "own", retry_failed=True, day=DAY)["granted"] is True


def test_publish_rejects_bad_input() -> None:
    db = _session()
    with pytest.raises(daily_run.DailyRunError):
        daily_run.publish(db, _auth(), {"profile_id": "nope", "status": "done"}, day=DAY)
    with pytest.raises(daily_run.DailyRunError):
        daily_run.publish(
            db,
            _auth(),
            {"profile_id": "p-assistant", "status": "done", "people": [{"fio": "А Б", "report_base64": "%%%"}]},
            day=DAY,
        )


def test_publish_tool_is_registered_for_the_launch_agent() -> None:
    from app.api.v1.tools import _SERVER_TOOLS
    from app.services.local_mcp import tool_contracts
    from app.services.workflows.kpi_launch_playbook import kpi_launch_runtime_tools

    assert "kpi.publish_position_result" in _SERVER_TOOLS
    assert "kpi.publish_position_result" in tool_contracts()
    assert "kpi.publish_position_result" in kpi_launch_runtime_tools()
