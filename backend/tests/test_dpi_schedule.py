from __future__ import annotations

from datetime import date

from kpi.sources.dpi_schedule import (
    DPI_SERIES_2026,
    event_matches_series,
    match_outlook_events,
    parse_rule,
    planned_date,
    planned_month,
    title_matches_dpi,
)


def test_parse_dom_and_nth_weekday():
    assert parse_rule("5 числа каждого месяца") == {"kind": "dom", "day": 5}
    assert parse_rule("1 пт месяца") == {"kind": "nth_weekday", "nth": 1, "weekday": 5}
    assert parse_rule("Во 2 вторник месяца") == {"kind": "nth_weekday", "nth": 2, "weekday": 2}


def test_september_2026_plan_shifts_weekend():
    by_name = {row.name: row for row in DPI_SERIES_2026}
    assert planned_date(by_name["ДПИ СУП"], 2026, 9) == date(2026, 9, 7)
    assert planned_date(by_name["ДПИ СР"], 2026, 9) == date(2026, 9, 4)
    assert planned_date(by_name["День подведения итогов отделов продаж"], 2026, 9) == date(2026, 9, 8)
    assert planned_date(by_name["ДПИ юридический отдел"], 2026, 9) == date(2026, 9, 7)
    assert planned_date(by_name["ДПИ производство №1, №2"], 2026, 9) == date(2026, 9, 14)


def test_seventeen_series_in_catalog():
    rows = planned_month(2026, 9)
    assert len(rows) == 17
    assert {row["plan_date"] for row in rows}


def test_outlook_match_by_title():
    series = next(item for item in DPI_SERIES_2026 if item.name == "ДПИ СУП")
    assert event_matches_series(series, "ДПИ СУПТЛ")
    events = [
        {"subject": "ДПИ СУП", "start": "2026-09-07T09:00:00"},
        {"subject": "Другое", "start": "2026-09-07T10:00:00"},
    ]
    rows = match_outlook_events(events, 2026, 9)
    sup = next(row for row in rows if row["name"] == "ДПИ СУП")
    assert sup["appointed"] is True
    assert sup["fact_date"] == "2026-09-07"


def test_title_variants_from_calendar():
    assert title_matches_dpi("ДПИ в службе качества", "ДПИ службы качества")
    assert title_matches_dpi("День подведения итогов КБ Гончаров", "День подведения итогов КБ")
    assert title_matches_dpi("ДПИ производство ЭЦ и БМИ", "ДПИ производство")
    assert not title_matches_dpi("ДПИ сектора внедрения ИИ", "а")
    assert not title_matches_dpi(
        "День подведения итогов по проектной деятельности по ГК Ануфриева",
        "Еженедельное ДПИ по плану Автоматизации ГК",
    )


def test_plan_comes_from_excel_month_column():
    excel_rows = [
        {
            "number": 1,
            "name": "ДПИ СУП",
            "rule": "5 числа каждого месяца",
            "owner": "Донцова",
            "excel_fact": {8: "2026-08-10"},
        }
    ]
    events = [{"subject": "ДПИ СУП", "start": "2026-08-10T09:00:00"}]
    rows = match_outlook_events(events, 2026, 8, excel_rows=excel_rows)
    assert rows[0]["plan_date"] == "2026-08-10"
    assert rows[0]["appointed"] is True
