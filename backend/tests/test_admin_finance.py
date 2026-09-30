from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.finance import FinanceImport, FinanceSalaryEntry
from app.models.org import OrgPerson, OrgPosition
from app.models.position_kpi import (
    PositionCompRule,
    PositionKpiDailyFact,
    PositionKpiMetric,
    PositionKpiModule,
    PositionKpiProfile,
    PositionKpiSource,
    PositionKpiSubjectFact,
)
from app.services.admin import finance
from app.services.position_kpi.daily import resolve_profile


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            OrgPosition.__table__,
            OrgPerson.__table__,
            FinanceImport.__table__,
            FinanceSalaryEntry.__table__,
            PositionKpiProfile.__table__,
            PositionCompRule.__table__,
            PositionKpiMetric.__table__,
            PositionKpiSource.__table__,
            PositionKpiModule.__table__,
            PositionKpiDailyFact.__table__,
            PositionKpiSubjectFact.__table__,
        ],
    )
    with Session(engine) as session:
        session.add(
            OrgPosition(id="POS-1", name="Финансовый директор", is_active=True)
        )
        session.add(
            OrgPerson(
                id="PERSON-1",
                fio="Иванова Анна Ивановна",
                fio_key="иванова анна ивановна",
                position_id="POS-1",
                position="Финансовый директор",
                department="Финансы",
                is_active=True,
            )
        )
        session.commit()
        yield session


def _salary_xlsx(amount: int, effective_from: date) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["ФИО", "Должность", "Оклад", "Валюта", "Действует с"])
    sheet.append(
        [
            "Иванова Анна Ивановна",
            "Финансовый директор",
            amount,
            "RUB",
            effective_from,
        ]
    )
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _mock_salary_extraction(monkeypatch, amount: int, effective_from: date) -> None:
    monkeypatch.setattr(
        finance,
        "extract_salary_document",
        lambda _name, _raw: {
            "effective_from": effective_from.isoformat(),
            "rows": [
                {
                    "position_name": "Финансовый директор",
                    "amount": str(amount),
                    "currency": "RUB",
                }
            ],
        },
    )


def test_employee_list_follows_login_directory(db: Session) -> None:
    payload = finance.list_employees(
        db,
        login_fios=[
            "Петров Пётр Петрович",
            "Service Account",
            "Иванова Анна Ивановна",
        ],
    )

    assert [row["fio"] for row in payload["rows"]] == [
        "Петров Пётр Петрович",
        "Иванова Анна Ивановна",
    ]
    assert payload["rows"][0]["id"] == ""
    assert payload["rows"][0]["position"] == ""
    assert payload["rows"][1]["id"] == "PERSON-1"
    assert payload["rows"][1]["position"] == "Финансовый директор"


def test_salary_import_matches_employee_and_confirms(db: Session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(finance.settings, "finance_storage_dir", tmp_path)
    _mock_salary_extraction(monkeypatch, 150_000, date(2026, 3, 1))
    payload = finance.create_import(
        db,
        kind="salary",
        filename="оклады.xlsx",
        raw=_salary_xlsx(150_000, date(2026, 3, 1)),
        user_id="finance-user",
        user_fio="Финансовый Директор",
    )

    assert payload["status"] == "review"
    assert payload["draft"]["rows"][0]["position_id"] == "POS-1"
    assert payload["validation"]["errors"] == []
    confirmed = finance.confirm_import(db, payload["id"])

    assert confirmed["status"] == "confirmed"
    salary = db.scalar(select(FinanceSalaryEntry))
    assert salary is not None
    assert salary.amount == Decimal("150000.00")
    assert salary.position_id == "POS-1"
    assert salary.revision == 1

    db.add(
        OrgPerson(
            id="PERSON-2",
            fio="Петров Пётр Петрович",
            fio_key="петров петр петрович",
            position_id="POS-1",
            position="Финансовый директор",
            department="Финансы",
            is_active=True,
        )
    )
    db.commit()
    shared_history = finance.employee_salaries(db, "PERSON-2")
    assert shared_history["rows"][0]["amount"] == "150000.00"


def test_salary_reimport_keeps_audit_revision(db: Session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(finance.settings, "finance_storage_dir", tmp_path)
    ids = []
    for amount in (150_000, 170_000):
        _mock_salary_extraction(monkeypatch, amount, date(2026, 3, 1))
        payload = finance.create_import(
            db,
            kind="salary",
            filename=f"оклады-{amount}.xlsx",
            raw=_salary_xlsx(amount, date(2026, 3, 1)),
            user_id="finance-user",
            user_fio="Финансовый Директор",
        )
        finance.confirm_import(db, payload["id"])
        ids.append(payload["id"])

    rows = db.scalars(
        select(FinanceSalaryEntry).order_by(FinanceSalaryEntry.revision)
    ).all()
    assert [row.revision for row in rows] == [1, 2]
    assert [row.is_current for row in rows] == [False, True]
    assert rows[1].replaced_entry_id == rows[0].id
    assert rows[1].import_id == ids[1]


def test_material_import_creates_effective_kpi_versions(db: Session) -> None:
    first = FinanceImport(
        id="IMP-1",
        kind="material_incentive",
        status="review",
        original_name="положение-1.pdf",
        created_by="finance-user",
        draft_json={
            "effective_from": "2026-03-01",
            "profiles": [
                {
                    "position_name": "Финансовый директор",
                    "bonus_base_pct": 100,
                    "metrics": [{"name": "Отчётность", "weight": 100}],
                }
            ],
        },
    )
    second = FinanceImport(
        id="IMP-2",
        kind="material_incentive",
        status="review",
        original_name="положение-2.pdf",
        created_by="finance-user",
        draft_json={
            "effective_from": "2026-06-01",
            "profiles": [
                {
                    "position_name": "Финансовый директор",
                    "bonus_base_pct": 80,
                    "metrics": [{"name": "Отчётность без ошибок", "weight": 100}],
                }
            ],
        },
    )
    db.add_all([first, second])
    db.commit()

    finance.confirm_import(db, first.id)
    finance.confirm_import(db, second.id)

    march = resolve_profile(
        db, "Финансовый директор", as_of=date(2026, 3, 15)
    )
    june = resolve_profile(
        db, "Финансовый директор", as_of=date(2026, 6, 15)
    )
    assert march is not None and june is not None
    assert march.id != june.id
    assert march.effective_to == date(2026, 5, 31)
    assert june.source_import_id == "IMP-2"
    employee = finance.employee_kpi(
        db,
        "PERSON-1",
        period_from=date(2026, 6, 1),
        period_to=date(2026, 6, 30),
    )
    assert employee["tiles"][0]["name"] == "Отчётность без ошибок"
