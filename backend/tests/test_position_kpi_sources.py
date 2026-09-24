from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.platform_task import PlatformTask
from app.models.position_kpi import PositionKpiDailyFact, PositionKpiSubjectFact
from app.services.position_kpi.connect import list_module_descriptors, upsert_generated_catalog
from app.services.position_kpi.daily import SourceBundle, get_or_compute_position_kpi
from app.services.position_kpi.explain import explain_metric
from app.services.position_kpi.sources import render_params, template_values, validate_spec
from kpi.seed_pl_npo_010 import upsert_catalog

POSITION = "Аналитик отдела закупок"
AS_OF = date(2026, 9, 22)
START = date(2026, 9, 1)
END = date(2026, 9, 30)

MODULE = '''
from datetime import date
from typing import Any

SOURCE = {"source": "platform.tasks", "params": {"role": "assignee"}}


def load_tasks_rows(ctx):
    return ctx.load_for(SOURCE)


def score_tasks_kpi(rows, *, as_of: date, date_from=None, date_to=None) -> dict[str, Any]:
    total = len(rows or [])
    done = sum(1 for row in rows or [] if row.get("done"))
    fact = round(100.0 * done / total, 1) if total else None
    return {"fact_pct": fact, "score_pct": fact, "contrib_pct": fact, "rows": rows or []}
'''

CATALOG = {
    "position_name": POSITION,
    "metrics": [
        {
            "code": "tasks",
            "name": "Исполнение задач",
            "weight": 100,
            "plan_value": 90,
            "formula_kind": "ratio_higher",
            "formula_human": "Исполненные задачи / все задачи за месяц",
            "sources": [],
        }
    ],
}


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    upsert_catalog(db)
    db.commit()
    return db


def _task(fio: str, status: str, day: int) -> PlatformTask:
    stamp = datetime(2026, 9, day, 12, tzinfo=timezone.utc)
    return PlatformTask(
        id=f"t-{fio}-{day}-{status}",
        author_user_id="boss",
        author_fio="Начальник Н. Н.",
        assignee_user_id=fio,
        assignee_fio=fio,
        description="Проверить договор",
        priority="normal",
        posted_at=stamp,
        due_at=stamp,
        status=status,
        status_at=stamp if status == "done" else None,
    )


def _unlink(db: Session, profile_id: str) -> None:
    for item in list_module_descriptors(db, profile_id):
        path = Path(item["path"])
        path.unlink(missing_ok=True)
        path.with_name(f"test_{path.stem}.py").unlink(missing_ok=True)


def test_validate_spec_rejects_unknown_and_missing_source() -> None:
    assert validate_spec({})["errors"]
    assert validate_spec({"source": "crm.deals"})["errors"]
    missing = validate_spec({"source": "onec.odata", "params": {}})
    assert any("entity" in error for error in missing["errors"])
    bad_var = validate_spec({"source": "platform.tasks", "params": {"fio": "{manager_fio}"}})
    assert any("manager_fio" in error for error in bad_var["errors"])
    assert validate_spec({"source": "platform.tasks", "params": {"fio": "{employee_fio}"}})["errors"] == []
    assert validate_spec({"loader": "odata"})["errors"] == []


def test_odata_entity_is_checked_against_catalog() -> None:
    known = validate_spec({"source": "onec.odata", "params": {"entity": "Document_ТД_Приказ"}})
    assert known["errors"] == []
    unknown = validate_spec({"source": "onec.odata", "params": {"entity": "Document_Выдуманный"}})
    assert unknown["errors"]


def test_local_xlsx_path_is_flagged_for_other_computers() -> None:
    check = validate_spec({"source": "files.xlsx", "params": {"file": "C:/Users/me/tracker.xlsx"}})
    assert check["errors"] == []
    assert any("UNC" in warning for warning in check["warnings"])


def test_template_params_use_employee_and_period() -> None:
    ctx = SourceBundle(as_of=AS_OF, date_from=START, date_to=END, subject_fio="Иванов Иван")
    rendered = render_params(
        {"filter": "Date ge datetime'{period_from_dt}' and Автор eq '{employee_fio}'"},
        template_values(ctx),
    )
    assert rendered["filter"] == "Date ge datetime'2026-09-01T00:00:00' and Автор eq 'Иванов Иван'"


def test_connect_rejects_module_without_source() -> None:
    db = _session()
    with pytest.raises(ValueError, match="откуда брать данные"):
        upsert_generated_catalog(
            db,
            position=POSITION,
            catalog=CATALOG,
            modules=[
                {
                    "metric_code": "tasks",
                    "code_text": "def score_tasks_kpi(rows, **_):\n    return {'fact_pct': 1}\n",
                }
            ],
        )


def test_one_module_counts_each_employee_separately() -> None:
    db = _session()
    profile_id = upsert_generated_catalog(
        db,
        position=POSITION,
        catalog=CATALOG,
        modules=[{"metric_code": "tasks", "code_text": MODULE}],
    )
    db.add_all(
        [
            _task("Петрова Анна", "done", 3),
            _task("Петрова Анна", "done", 5),
            _task("Сидоров Олег", "done", 4),
            _task("Сидоров Олег", "open", 8),
        ]
    )
    db.commit()
    try:
        anna = get_or_compute_position_kpi(
            db, POSITION, as_of=AS_OF, date_from=START, date_to=END, subject="Петрова Анна"
        )
        oleg = get_or_compute_position_kpi(
            db, POSITION, as_of=AS_OF, date_from=START, date_to=END, subject="сидоров  олег"
        )
        assert anna["tiles"][0]["fact"] == 100.0
        assert oleg["tiles"][0]["fact"] == 50.0
        assert anna["profile_id"] == oleg["profile_id"] == profile_id
        assert db.query(PositionKpiSubjectFact).count() == 2
        assert db.query(PositionKpiDailyFact).count() == 0
        again = get_or_compute_position_kpi(
            db, POSITION, as_of=AS_OF, date_from=START, date_to=END, subject="ПЕТРОВА анна"
        )
        assert again["cached"] is True
        assert again["tiles"][0]["fact"] == 100.0
    finally:
        _unlink(db, profile_id)


def test_explain_metric_returns_code_and_source() -> None:
    db = _session()
    profile_id = upsert_generated_catalog(
        db,
        position=POSITION,
        catalog=CATALOG,
        modules=[{"metric_code": "tasks", "code_text": MODULE}],
    )
    db.commit()
    try:
        card = explain_metric(db, POSITION, "tasks")
        assert card["module"]["origin"] == "generated"
        assert "score_tasks_kpi" in card["module"]["code"]
        assert card["data_source"]["source"] == "platform.tasks"
        assert card["data_source"]["registry"]["title"]
        assert card["data_source"]["validation"]["ok"] is True
        assert POSITION in card["shared_note"]
        assert card["formula_human"].startswith("Исполненные")
    finally:
        _unlink(db, profile_id)


def test_explain_builtin_scorer_reads_repo_source() -> None:
    db = _session()
    card = explain_metric(db, "Помощник Председателя совета директоров", "package_on_time")
    assert card["module"] is not None
    assert card["module"]["origin"] == "builtin"
    assert "def " in card["module"]["code"]
