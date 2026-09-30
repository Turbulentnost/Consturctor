from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.finance import FinanceImport, FinanceSalaryEntry
from app.models.org import OrgPerson, OrgPosition, OrgUnit
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
            OrgUnit.__table__,
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


def _mock_salary_extraction(
    monkeypatch, amount: int, effective_from: date, rows: list[dict] | None = None
) -> None:
    monkeypatch.setattr(
        finance,
        "extract_salary_document",
        lambda _name, _raw: {
            "effective_from": effective_from.isoformat(),
            "rows": rows
            or [
                {
                    "position_name": "Финансовый директор",
                    "amount": str(amount),
                    "currency": "RUB",
                }
            ],
        },
    )


def test_salary_depends_on_department(db: Session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(finance.settings, "finance_storage_dir", tmp_path)
    db.add(OrgUnit(id="UNIT-SALES", name="Продажи"))
    db.add(
        OrgPerson(
            id="PERSON-SALES",
            fio="Петров Пётр Петрович",
            fio_key="петров петр петрович",
            position_id="POS-1",
            position="Финансовый директор",
            department="Продажи",
            is_active=True,
        )
    )
    db.add(
        OrgPerson(
            id="PERSON-OTHER",
            fio="Сидоров Сидор Сидорович",
            fio_key="сидоров сидор сидорович",
            position_id="POS-1",
            position="Финансовый директор",
            department="Склад",
            is_active=True,
        )
    )
    db.add(
        FinanceSalaryEntry(
            id="LEGACY",
            position_id="POS-1",
            department="",
            amount=Decimal("100000"),
            effective_from=date(2026, 1, 1),
            import_id="legacy-import",
        )
    )
    db.commit()
    _mock_salary_extraction(
        monkeypatch,
        0,
        date(2026, 3, 1),
        rows=[
            {"department_name": "финансы", "position_name": "Финансовый директор", "amount": "150000"},
            {"department_name": "Продажи", "position_name": "Финансовый директор", "amount": "200000"},
        ],
    )
    payload = finance.create_import(
        db,
        kind="salary",
        filename="штатное.docx",
        raw=b"x",
        user_id="finance-user",
        user_fio="Финансовый Директор",
    )
    assert [row["department"] for row in payload["draft"]["rows"]] == ["Финансы", "Продажи"]
    assert payload["validation"]["errors"] == []
    finance.confirm_import(db, payload["id"])

    employees = {
        row["id"]: row
        for row in finance.list_employees(
            db,
            login_fios=[
                "Иванова Анна Ивановна",
                "Петров Пётр Петрович",
                "Сидоров Сидор Сидорович",
            ],
        )["rows"]
    }
    assert employees["PERSON-1"]["department"] == "Финансы"
    assert employees["PERSON-1"]["salary"] == "150000.00"
    assert employees["PERSON-SALES"]["salary"] == "200000.00"
    assert employees["PERSON-OTHER"]["salary"] == "100000.00"


def test_salary_import_rejects_unknown_department(db: Session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(finance.settings, "finance_storage_dir", tmp_path)
    _mock_salary_extraction(
        monkeypatch,
        0,
        date(2026, 3, 1),
        rows=[
            {"department_name": "Марс", "position_name": "Финансовый директор", "amount": "1"},
        ],
    )
    payload = finance.create_import(
        db,
        kind="salary",
        filename="штатное.docx",
        raw=b"x",
        user_id="finance-user",
        user_fio="Финансовый Директор",
    )
    assert [error["field"] for error in payload["validation"]["errors"]] == ["department"]


def test_salary_requires_department(db: Session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(finance.settings, "finance_storage_dir", tmp_path)
    db.add(OrgPosition(id="POS-2", name="Кладовщик", is_active=True))
    for suffix, department in (("A", "Склад"), ("B", "Продажи")):
        db.add(
            OrgPerson(
                id=f"PERSON-{suffix}",
                fio=f"Кладовщик {suffix}",
                fio_key=f"кладовщик {suffix.lower()}",
                position_id="POS-2",
                position="Кладовщик",
                department=department,
                is_active=True,
            )
        )
    db.commit()
    _mock_salary_extraction(
        monkeypatch,
        0,
        date(2026, 3, 1),
        rows=[
            {"department_name": "", "position_name": "Финансовый директор", "amount": "1"},
            {"department_name": "", "position_name": "Кладовщик", "amount": "1"},
        ],
    )
    payload = finance.create_import(
        db,
        kind="salary",
        filename="штатное.docx",
        raw=b"x",
        user_id="finance-user",
        user_fio="Финансовый Директор",
    )
    # A position staffed in one department only gets it filled in automatically.
    assert [row["department"] for row in payload["draft"]["rows"]] == ["Финансы", ""]
    assert payload["validation"]["errors"] == [
        {"row": 1, "field": "department", "message": "Выберите подразделение"}
    ]
    assert finance.position_departments(db)["POS-2"] == ["Продажи", "Склад"]


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


def _history_import(
    import_id: str, kind: str, draft: dict, confirmed_at: datetime | None
) -> FinanceImport:
    return FinanceImport(
        id=import_id,
        kind=kind,
        status="confirmed" if confirmed_at else "review",
        original_name=f"{import_id}.docx",
        created_by="finance-user",
        draft_json=draft,
        confirmed_at=confirmed_at,
    )


def _salary_row(position: str, department: str, amount: str) -> dict:
    return {
        "position_id": "",
        "position_name": position,
        "department": department,
        "amount": amount,
        "currency": "RUB",
        "effective_from": "2026-03-01",
    }


def test_import_history_reports_salary_version_changes(db: Session) -> None:
    db.add_all(
        [
            _history_import(
                "S-1",
                "salary",
                {
                    "rows": [
                        _salary_row("Бухгалтер", "Финансы", "100 000"),
                        _salary_row("Кассир", "Финансы", "60000"),
                        _salary_row("Юрист", "Финансы", "90000"),
                        _salary_row("Кладовщик", "Склад", "50000"),
                    ]
                },
                datetime(2026, 3, 1, tzinfo=timezone.utc),
            ),
            _history_import(
                "S-2",
                "salary",
                {
                    "rows": [
                        _salary_row("Бухгалтер", "Финансы", "100000,00"),
                        _salary_row("Кассир", "Финансы", "65000"),
                        _salary_row("Аналитик", "Финансы", "120000"),
                    ]
                },
                None,
            ),
        ]
    )
    db.commit()

    listed = {row["id"]: row["changes"] for row in finance.list_imports(db)["rows"]}
    assert listed["S-1"]["summary"] == {
        "added": 4, "updated": 0, "removed": 0, "unchanged": 0, "has_baseline": False
    }
    detail = finance.import_changes(db, "S-2")
    # «Склад» is outside the new file, so its salary is not reported as removed.
    assert detail["summary"] == {
        "added": 1, "updated": 1, "removed": 1, "unchanged": 1, "has_baseline": True
    }
    assert [item["position"] for item in detail["added"]] == ["Аналитик"]
    assert detail["updated"][0]["changes"] == [
        {"label": "Оклад", "before": "60000.00", "after": "65000.00"}
    ]
    assert [item["position"] for item in detail["removed"]] == ["Юрист"]


def test_import_history_reports_kpi_metric_changes(db: Session) -> None:
    def profile(metrics: list[dict]) -> dict:
        return {"position_name": "Секретарь", "department": "Управление делами", "metrics": metrics}

    db.add_all(
        [
            _history_import(
                "M-1",
                "material_incentive",
                {
                    "effective_from": "2026-03-01",
                    "profiles": [
                        profile(
                            [
                                {"name": "Сроки", "weight": 60, "plan_value": 95},
                                {"name": "Архив", "weight": 40},
                            ]
                        )
                    ],
                },
                datetime(2026, 3, 1, tzinfo=timezone.utc),
            ),
            _history_import(
                "M-2",
                "material_incentive",
                {
                    "effective_from": "2026-06-01",
                    "profiles": [
                        profile(
                            [
                                {"name": "Сроки", "weight": 70, "plan_value": 95},
                                {"name": "Обращения", "weight": 30},
                            ]
                        )
                    ],
                },
                datetime(2026, 6, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    db.commit()

    detail = finance.import_changes(db, "M-2")
    assert detail["summary"]["updated"] == 1
    assert detail["updated"][0]["changes"] == [
        {"label": "KPI «Сроки»: вес", "before": "60%", "after": "70%"},
        {"label": "KPI добавлен", "before": "", "after": "Обращения — 30%"},
        {"label": "KPI удалён", "before": "Архив — 40%", "after": ""},
    ]
    assert finance.import_changes(db, "M-1")["summary"]["added"] == 1


def test_material_parse_stores_kpi_per_department(db: Session, monkeypatch) -> None:
    db.add(
        OrgPerson(
            id="PERSON-SALES",
            fio="Петров Пётр Петрович",
            fio_key="петров петр петрович",
            position_id="POS-1",
            position="Финансовый директор",
            department="Продажи",
            is_active=True,
        )
    )
    db.commit()
    _mock_material(monkeypatch, 100)

    draft = finance._parse_material(db, "положение.pdf", b"")

    assert [item["department"] for item in draft["profiles"]] == ["Продажи", "Финансы"]
    assert draft["profiles"][0]["metrics"][0] is not draft["profiles"][1]["metrics"][0]
    db.add(
        FinanceImport(
            id="IMP-PARSED",
            kind="material_incentive",
            status="review",
            original_name="положение.pdf",
            created_by="finance-user",
            draft_json=draft,
        )
    )
    db.commit()
    finance.confirm_import(db, "IMP-PARSED")

    stored = db.scalars(
        select(PositionKpiProfile).where(PositionKpiProfile.source_import_id == "IMP-PARSED")
    ).all()
    assert sorted(profile.department for profile in stored) == ["Продажи", "Финансы"]


def _mock_material(
    monkeypatch, weight: int, department: str = "", positions: list[str] | None = None
) -> None:
    monkeypatch.setattr(finance, "read_full_text", lambda _name, _raw: "Положение от 01.03.2026.")
    monkeypatch.setattr(
        finance,
        "extract_material_document",
        lambda _name, _text: {
            "effective_from": "2026-03-01",
            "department_name": department,
            "positions": [
                {
                    "position_name": title,
                    "department_name": "",
                    "metrics": [{"name": "Отчётность", "weight": weight, "formula": "менее 5 = 100%"}],
                }
                for title in positions or ["Финансовый директор"]
            ],
        },
    )


def test_material_parse_uses_regulation_department(db: Session, monkeypatch) -> None:
    db.add(OrgUnit(id="UNIT-UD", name="Управление делами"))
    db.add(
        OrgPerson(
            id="PERSON-SALES",
            fio="Петров Пётр Петрович",
            fio_key="петров петр петрович",
            position_id="POS-1",
            position="Финансовый директор",
            department="Продажи",
            is_active=True,
        )
    )
    db.commit()
    _mock_material(
        monkeypatch,
        100,
        department="управление делами",
        positions=["Финансовый директор", "Секретарь / Архивариус"],
    )

    draft = finance._parse_material(db, "положение.pdf", b"")

    assert draft["effective_from"] == "2026-03-01"
    assert [(item["position_name"], item["department"]) for item in draft["profiles"]] == [
        ("Финансовый директор", "Управление делами"),
        ("Секретарь / Архивариус", "Управление делами"),
    ]
    assert draft["profiles"][0]["position_id"] == "POS-1"
    assert draft["profiles"][1]["position_id"] == ""
    assert draft["profiles"][0]["metrics"][0]["weight"] == 100
    assert draft["profiles"][0]["metrics"][0]["formula_kind"] == "violation_bands"


def test_material_upload_writes_kpi_without_manual_confirm(
    db: Session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(finance.settings, "finance_storage_dir", tmp_path)
    _mock_material(monkeypatch, 100)

    payload = finance.create_import(
        db,
        kind="material_incentive",
        filename="положение.pdf",
        raw=b"pdf",
        user_id="finance-user",
        user_fio="Финансовый Директор",
    )

    assert payload["status"] == "confirmed"
    profile = resolve_profile(
        db, "Финансовый директор", as_of=date(2026, 3, 15), department="Финансы"
    )
    assert profile is not None
    assert profile.department == "Финансы"
    assert profile.source_import_id == payload["id"]


def test_material_upload_with_errors_waits_for_review(
    db: Session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(finance.settings, "finance_storage_dir", tmp_path)
    _mock_material(monkeypatch, 60)

    payload = finance.create_import(
        db,
        kind="material_incentive",
        filename="положение.pdf",
        raw=b"pdf",
        user_id="finance-user",
        user_fio="Финансовый Директор",
    )

    assert payload["status"] == "review"
    assert payload["validation"]["errors"]
    assert db.scalars(select(PositionKpiProfile)).first() is None


def test_kpi_profile_prefers_employee_department(db: Session) -> None:
    db.add(OrgUnit(id="UNIT-FIN", name="Финансы"))
    db.add(
        FinanceImport(
            id="IMP-DEPT",
            kind="material_incentive",
            status="review",
            original_name="положение.pdf",
            created_by="finance-user",
            draft_json={
                "effective_from": "2026-03-01",
                "profiles": [
                    {
                        "position_name": "Финансовый директор",
                        "department": "",
                        "bonus_base_pct": 100,
                        "metrics": [{"name": "Общая метрика", "weight": 100}],
                    },
                    {
                        "position_name": "Финансовый директор",
                        "department": "Финансы",
                        "bonus_base_pct": 100,
                        "metrics": [{"name": "Метрика финансов", "weight": 100}],
                    },
                ],
            },
        )
    )
    db.commit()
    finance.confirm_import(db, "IMP-DEPT")

    day = date(2026, 3, 15)
    own = resolve_profile(db, "Финансовый директор", as_of=day, department="финансы")
    shared = resolve_profile(db, "Финансовый директор", as_of=day, department="Склад")
    assert own is not None and own.department == "Финансы"
    assert shared is not None and shared.department == ""
    employee = finance.employee_kpi(
        db, "PERSON-1", period_from=date(2026, 3, 1), period_to=date(2026, 3, 31)
    )
    assert employee["tiles"][0]["name"] == "Метрика финансов"
