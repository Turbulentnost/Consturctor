from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.position_kpi import PositionKpiProfile, PositionKpiSubjectFact
from app.services.position_kpi.daily import attach_tile_history, subject_key

FIO = "Ильченко Екатерина Александровна"


def test_attach_tile_history_orders_days_and_ends_with_today() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, future=True)()
    db.add(PositionKpiProfile(id="p1", position_name="Помощник", status="active", effective_from=date(2026, 9, 1)))
    for index, (day, fact) in enumerate([(3, 40.0), (1, 20.0), (2, None)]):
        db.add(
            PositionKpiSubjectFact(
                id=f"f{index}",
                profile_id="p1",
                subject=subject_key(FIO),
                subject_fio=FIO,
                day=date(2026, 9, day),
                period_from=date(2026, 9, 1),
                period_to=date(2026, 9, 30),
                payload={"tiles": [{"code": "m1", "fact": fact}]},
            )
        )
    db.commit()

    payload = {
        "profile_id": "p1",
        "period_from": "2026-09-01",
        "period_to": "2026-09-30",
        "as_of": "2026-09-04",
        "tiles": [{"code": "m1", "fact": 55.0}, {"code": "m2", "fact": None}],
    }
    result = attach_tile_history(db, payload, subject=FIO)

    assert [p["value"] for p in result["tiles"][0]["history"]] == [20.0, 40.0, 55.0]
    assert result["tiles"][1]["history"] == []
    assert "history" not in payload["tiles"][0]
