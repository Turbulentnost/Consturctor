from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.user import UserKpiPin
from app.services.position_kpi import pin as kpi_pin


@pytest.fixture(autouse=True)
def _reset_attempts() -> None:
    kpi_pin._attempts.clear()


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _code(fn, *args) -> int:
    with pytest.raises(kpi_pin.KpiPinError) as exc:
        fn(*args)
    return exc.value.status_code


def test_set_pin_requires_matching_four_digits() -> None:
    db = _session()
    assert kpi_pin.has_pin(db, "u1") is False
    assert _code(kpi_pin.set_pin, db, "u1", "12a4", "12a4") == 400
    assert _code(kpi_pin.set_pin, db, "u1", "12345", "12345") == 400
    assert _code(kpi_pin.set_pin, db, "u1", "1234", "4321") == 400

    kpi_pin.set_pin(db, "u1", "1234", "1234")
    assert kpi_pin.has_pin(db, "u1") is True
    assert kpi_pin.has_pin(db, "u2") is False
    assert _code(kpi_pin.set_pin, db, "u1", "5555", "5555") == 409

    stored = db.get(UserKpiPin, "u1")
    assert stored is not None and "1234" not in stored.pin_hash


def test_verify_and_change_pin() -> None:
    db = _session()
    assert _code(kpi_pin.verify_pin, db, "u1", "1234") == 409
    kpi_pin.set_pin(db, "u1", "1234", "1234")
    kpi_pin.verify_pin(db, "u1", "1234")
    assert _code(kpi_pin.verify_pin, db, "u1", "0000") == 403

    assert _code(kpi_pin.change_pin, db, "u1", "0000", "5678", "5678") == 403
    assert _code(kpi_pin.change_pin, db, "u1", "1234", "5678", "8765") == 400
    assert _code(kpi_pin.change_pin, db, "u1", "1234", "1234", "1234") == 400
    kpi_pin.change_pin(db, "u1", "1234", "5678", "5678")
    kpi_pin.verify_pin(db, "u1", "5678")
    assert _code(kpi_pin.verify_pin, db, "u1", "1234") == 403


def test_verify_pin_rate_limit() -> None:
    db = _session()
    kpi_pin.set_pin(db, "u1", "1234", "1234")
    for _ in range(5):
        assert _code(kpi_pin.verify_pin, db, "u1", "0000") == 403
    assert _code(kpi_pin.verify_pin, db, "u1", "1234") == 429
