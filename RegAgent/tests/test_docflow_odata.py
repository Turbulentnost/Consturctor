"""Unit-тесты поручений Документ.ТД_Поручения (без живого ERP)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.services.docflow_odata import (
    _map_line,
    _parse_odata_dt,
    docflow_base_url,
    sort_tasks,
    urgency_tier,
)
from app.services.erp_task_utils import from_1c_datetime, parse_date


def test_docflow_base_url_from_erp(monkeypatch) -> None:
    monkeypatch.setenv("ODATA_BASE_URL", "http://host/erp_pm/odata/standard.odata")
    assert docflow_base_url() == "http://host/erp_pm/odata/standard.odata"


def test_parse_odata_dt_skips_empty() -> None:
    assert _parse_odata_dt("") is None
    assert _parse_odata_dt("0001-01-01T00:00:00") is None
    parsed = _parse_odata_dt("2026-08-17T12:00:00")
    assert parsed == datetime(2026, 8, 17, 12, 0, 0)


def test_from_1c_datetime_year_offset() -> None:
    raw = datetime(4026, 8, 17, 12, 0, 0)
    assert from_1c_datetime(raw) == datetime(2026, 8, 17, 12, 0, 0)


def test_urgency_tier_overdue_pastel() -> None:
    tier, color, label = urgency_tier(
        due_at=datetime(2026, 8, 20, 18, 0, 0),
        done=False,
        today=date(2026, 8, 21),
    )
    assert tier == "overdue"
    assert color == "#FECACA"
    assert label == "Просрочено"


def test_urgency_tier_due_soon_orange() -> None:
    tier, color, label = urgency_tier(
        due_at=datetime(2026, 8, 22, 18, 0, 0),
        done=False,
        today=date(2026, 8, 21),
    )
    assert tier == "due_soon"
    assert color == "#FFE0B2"
    assert label == "Срок 1 день и меньше"


def test_urgency_tier_due_3days_yellow() -> None:
    tier, color, _ = urgency_tier(
        due_at=datetime(2026, 8, 24, 18, 0, 0),
        done=False,
        today=date(2026, 8, 21),
    )
    assert tier == "due_3days"
    assert color == "#FFF9C4"


def test_urgency_tier_accepted_green() -> None:
    tier, color, label = urgency_tier(
        due_at=datetime(2026, 9, 1, 18, 0, 0),
        done=False,
        status="Принято",
        today=date(2026, 8, 21),
    )
    assert tier == "accepted"
    assert color == "#D4EDDA"
    assert label == "Принято"


def test_urgency_tier_accepted_overdue_is_green() -> None:
    tier, color, label = urgency_tier(
        due_at=datetime(2026, 8, 10, 18, 0, 0),
        done=False,
        status="Принято",
        today=date(2026, 8, 21),
    )
    assert tier == "accepted"
    assert color == "#D4EDDA"
    assert label == "Принято"


def test_map_line_accepted_not_overdue_color() -> None:
    doc = {
        "Ref_Key": "a1b2",
        "Number": "АСТ00-00003",
        "Date": "2026-08-10T09:00:00",
        "Статус": "Принято",
        "ОЧем": "Тема",
        "Основание": "основание",
    }
    line = {
        "LineNumber": "1",
        "Мероприятие": "Задача",
        "СрокИсполнения": "2026-08-12T18:00:00",
    }
    item = _map_line(doc, line, performer="Иванов", today=date(2026, 8, 21))
    assert item["urgency_tier"] == "accepted"
    assert item["color"] == "#D4EDDA"
    assert item["late"] is False


def test_sort_tasks_by_number_desc() -> None:
    tasks = [
        {"number": "АСТ00-00001", "line_number": "1"},
        {"number": "АСТ00-00090", "line_number": "2"},
        {"number": "АСТ00-00090", "line_number": "1"},
        {"number": "АСТ00-00010", "line_number": "1"},
    ]
    sorted_tasks = sort_tasks(tasks)
    numbers = [(t["number"], t["line_number"]) for t in sorted_tasks]
    assert numbers == [
        ("АСТ00-00090", "2"),
        ("АСТ00-00090", "1"),
        ("АСТ00-00010", "1"),
        ("АСТ00-00001", "1"),
    ]


def test_parse_date_end_of_day() -> None:
    parsed = parse_date("2026-08-21", end=True)
    assert parsed.hour == 23
    assert parsed.minute == 59


def test_parse_date_invalid() -> None:
    with pytest.raises(Exception):
        parse_date("не-дата")
