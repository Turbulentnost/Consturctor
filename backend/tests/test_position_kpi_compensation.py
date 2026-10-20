from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.jwt import AuthContext
from app.db.base import Base
from app.models.finance import FinanceImport, FinanceSalaryEntry
from app.models.org import OrgPerson, OrgPosition
from app.models.position_kpi import PositionCompRule, PositionKpiProfile
from app.services.admin import salary_source
from app.services.position_kpi import compensation
from app.services.position_kpi import pin as kpi_pin
from app.services.position_kpi.erp_salary import PlannedSalary, revisions_from_rates


POSITION = "Помощник Председателя совета директоров"
AUTH = AuthContext(user_id="user-1", fio="Ильченко Екатерина Александровна", position=POSITION)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    db.add(OrgPosition(id="position-1", name=POSITION, is_active=True))
    db.add(
        OrgPerson(
            id="person-1",
            fio=AUTH.fio or "",
            fio_key="ильченко екатерина александровна",
            user_id=AUTH.user_id,
            position_id="position-1",
            position=POSITION,
            unit_id="unit-1",
            department="Управление делами",
            is_active=True,
        )
    )
    db.add(
        FinanceImport(
            id="import-1",
            kind="salary",
            status="confirmed",
            original_name="salary.docx",
            storage_path="salary.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            sha256="hash",
            size_bytes=1,
            created_by="admin",
            created_by_fio="Admin",
        )
    )
    db.add(
        FinanceSalaryEntry(
            id="salary-1",
            position_id="position-1",
            amount=Decimal("235000.00"),
            currency="RUB",
            effective_from=date(2026, 9, 1),
            revision=1,
            is_current=True,
            import_id="import-1",
            position_snapshot=POSITION,
        )
    )
    db.add(
        PositionKpiProfile(
            id="profile-1",
            position_name=POSITION,
            department="Управление делами",
            status="active",
            effective_from=date(2026, 3, 1),
        )
    )
    db.add(
        PositionCompRule(
            id="rule-1",
            profile_id="profile-1",
            bonus_kind="salary_times_crp_times_sum",
            bonus_base_pct=100,
        )
    )
    db.commit()
    return db


def test_masked_compensation_never_returns_money() -> None:
    result = compensation.masked_compensation(_session(), AUTH, as_of=date(2026, 9, 29))
    assert result["available"] is True
    assert result["unlocked"] is False
    assert result["salary"] is None
    assert result["bonus"] is None
    assert result["total"] is None


def test_unlock_checks_pin_and_calculates_bonus(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session()
    monkeypatch.setattr(
        compensation,
        "get_or_compute_position_kpi",
        lambda *_args, **_kwargs: {"tiles": [{"contrib": 25}, {"contrib": 35}]},
    )

    with pytest.raises(compensation.CompensationError) as exc:
        compensation.unlock_compensation(db, AUTH, pin="1111")
    assert exc.value.status_code == 409

    kpi_pin.set_pin(db, AUTH.user_id, "1111", "1111")
    with pytest.raises(compensation.CompensationError) as exc:
        compensation.unlock_compensation(db, AUTH, pin="0000")
    assert exc.value.status_code == 403

    result = compensation.unlock_compensation(
        db,
        AUTH,
        pin="1111",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert result["salary"] == "235000.00"
    assert result["bonus"] == "141000.00"
    assert result["total"] == "376000.00"


def test_file_source_rejected_until_salary_file_is_confirmed() -> None:
    db = _session()
    imported = db.get(FinanceImport, "import-1")
    assert imported is not None
    imported.status = "review"
    db.commit()

    state = salary_source.salary_source_state(db)
    assert state["mode"] == "onec"
    assert state["can_use_file"] is False
    with pytest.raises(salary_source.SalarySourceError) as exc:
        salary_source.set_salary_source(db, "file")
    assert exc.value.status_code == 409

    imported.status = "confirmed"
    db.commit()
    switched = salary_source.set_salary_source(db, "file")
    assert switched["mode"] == "file"
    assert switched["can_use_file"] is True


def test_onec_source_sets_bonus_equal_to_salary(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session()
    salary_source.set_salary_source(db, "onec")
    kpi_pin.set_pin(db, AUTH.user_id, "1111", "1111")
    monkeypatch.setattr(
        compensation,
        "lookup_salary_history",
        lambda _fio, _as_of: [
            PlannedSalary(amount=Decimal("35000.00"), effective_from=date(2025, 12, 22)),
            PlannedSalary(amount=Decimal("40000.00"), effective_from=date(2026, 4, 6)),
            PlannedSalary(amount=Decimal("57500.00"), effective_from=date(2026, 6, 1)),
            PlannedSalary(amount=Decimal("60000.00"), effective_from=date(2026, 7, 28)),
            PlannedSalary(amount=Decimal("75000.00"), effective_from=date(2026, 9, 1)),
        ],
    )

    masked = compensation.masked_compensation(db, AUTH, as_of=date(2026, 9, 30))
    assert masked["available"] is True
    assert masked["salary"] is None

    result = compensation.unlock_compensation(db, AUTH, pin="1111", date_to=date(2026, 9, 30))
    assert result["salary"] == "75000.00"
    assert result["bonus"] == "75000.00"
    assert result["total"] == "150000.00"
    assert result["effective_from"] == "2026-09-01"
    assert [point["effective_from"] for point in result["history"]] == [
        "2025-12-22",
        "2026-04-06",
        "2026-06-01",
        "2026-07-28",
        "2026-09-01",
    ]
    assert [point["total"] for point in result["history"]] == [
        "70000.00",
        "80000.00",
        "115000.00",
        "120000.00",
        "150000.00",
    ]


def test_salary_rates_keep_only_real_changes() -> None:
    revisions = revisions_from_rates(
        [
            (date(2025, 12, 22), Decimal("35000")),
            (date(2026, 1, 1), Decimal("35000")),
            (date(2026, 4, 6), Decimal("40000")),
            (date(2026, 6, 1), Decimal("40000")),
            (date(2026, 6, 1), Decimal("57500")),
            (date(2026, 7, 28), Decimal("60000")),
            (date(2026, 8, 3), Decimal("60000")),
            (date(2026, 9, 1), Decimal("60000")),
            (date(2026, 9, 1), Decimal("75000")),
        ]
    )
    assert [(item.effective_from, item.amount) for item in revisions] == [
        (date(2025, 12, 22), Decimal("35000.00")),
        (date(2026, 4, 6), Decimal("40000.00")),
        (date(2026, 6, 1), Decimal("57500.00")),
        (date(2026, 7, 28), Decimal("60000.00")),
        (date(2026, 9, 1), Decimal("75000.00")),
    ]
