from __future__ import annotations

from datetime import date

from kpi.sources.sd_rk_protocols import (
    add_workdays,
    classify_meeting,
    classify_protocol,
    gate_score,
    protocol_deadline,
    score_protocol_kpi,
)


def test_add_workdays_skips_weekend():
    assert add_workdays(date(2026, 8, 7), 2) == date(2026, 8, 11)
    assert add_workdays(date(2026, 8, 28), 2) == date(2026, 9, 1)
    assert protocol_deadline(date(2026, 9, 15)) == date(2026, 9, 17)


def test_classify_skips_secretary_prep():
    assert classify_meeting("Совет директоров по Группе компаний") == "sd"
    assert classify_meeting("Еженедельное совещание с ревизионной комиссией") == "rk"
    assert (
        classify_meeting(
            "Секретарь РК еженедельно до проведения совещания формирует и утверждает "
            "у Руководителя РК повестку заседания ревизионной комиссии"
        )
        is None
    )


def test_classify_protocol_uses_topic_not_psd_prefix():
    assert classify_protocol("ПСД_001_О_174", "Совет директоров по ГК") == "sd"
    assert classify_protocol("ПСД_001_О_231", "Совещание по поручению АСТ00-00057") is None
    assert classify_protocol("РК__001_О_035", "Еженедельное совещание с ревизионной комиссией") == "rk"


def test_gate_then_ratio():
    assert gate_score(100) == 100
    assert gate_score(95) == 100
    assert gate_score(80) == 84.2


def test_august_plan_fact_all_on_time():
    events = [
        {"subject": "Совет директоров ГК (ИТЦ, Авион, Магакян)", "start": "2026-08-07T16:00:00"},
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-08-25T14:00:00"},
        {"subject": "Совет директоров по Группе компаний", "start": "2026-08-27T10:00:00"},
        {"subject": "Совет директоров ГК (ИТЦ, Авион, Магакян)", "start": "2026-08-28T14:00:00"},
        {
            "subject": "Секретарь РК еженедельно формирует и утверждает повестку заседания",
            "start": "2026-08-25T07:30:00",
        },
    ]
    protocols = [
        {
            "number": "ПСД_001_О_174",
            "date": "2026-08-07",
            "posted": True,
            "status": "Закрыт",
            "meeting_topic": "Совет директоров по ГК",
        },
        {
            "number": "РК__001_О_035",
            "date": "2026-08-25",
            "posted": True,
            "status": "Закрыт",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        },
        {
            "number": "ПСД_001_О_201",
            "date": "2026-08-27",
            "posted": True,
            "status": "НаИсполнении",
            "meeting_topic": "Совет директоров по ГК",
        },
        {
            "number": "ПСД_001_О_209",
            "date": "2026-08-28",
            "posted": True,
            "status": "Закрыт",
            "meeting_topic": "Совет директоров по ГК (ООО «ИТЦ», ООО «Авион» и ИП Магакян Е.И.)",
        },
        {
            "number": "ПСД_001_О_180",
            "date": "2026-08-12",
            "posted": True,
            "status": "Закрыт",
            "meeting_topic": "Совет директоров по ГК",
        },
    ]
    report = score_protocol_kpi(
        events,
        protocols,
        as_of=date(2026, 9, 21),
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
    )
    assert report["p_total"] == 4
    assert report["p_on_time"] == 4
    assert report["fact_pct"] == 100
    assert report["score_pct"] == 100
    assert report["contrib_pct"] == 25
    numbers = {row["protocol_number"] for row in report["rows"] if row["due"]}
    assert "ПСД_001_О_180" not in numbers


def test_open_meeting_counts_until_deadline_future_stays_out():
    events = [
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-09-15T10:00:00"},
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-09-22T14:00:00"},
        {"subject": "Совет директоров по Группе компаний", "start": "2026-09-30T15:00:00"},
    ]
    protocols = [
        {
            "number": "РК__001_О_038",
            "date": "2026-09-15",
            "posted": True,
            "status": "НаИсполнении",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        },
        {
            "number": "РК__001_О_039",
            "date": "2026-09-22",
            "posted": False,
            "status": "Подготовлен",
            "needs_review": True,
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        },
        {
            "number": "ПСД_001_О_226",
            "date": "2026-09-30",
            "posted": False,
            "status": "Подготовлен",
            "needs_review": True,
            "meeting_topic": "Совет директоров по ГК",
        },
    ]
    report = score_protocol_kpi(events, protocols, as_of=date(2026, 9, 21))
    due = [row for row in report["rows"] if row["due"]]
    assert {row["plan_date"] for row in due} == {"2026-09-15", "2026-09-22"}
    issued = next(row for row in due if row["plan_date"] == "2026-09-15")
    assert issued["protocol_number"] == "РК__001_О_038"
    assert issued["on_time"] is True
    still_open = next(row for row in due if row["plan_date"] == "2026-09-22")
    assert still_open["issued"] is False
    assert still_open["on_time"] is True
    pending = [row for row in report["rows"] if not row["due"]]
    assert {row["plan_date"] for row in pending} == {"2026-09-30"}
    assert report["fact_pct"] == 100.0


def test_month_slice_ignores_previous_month():
    events = [
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-08-25T14:00:00"},
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-09-25T14:00:00"},
    ]
    protocols = [
        {
            "number": "РК__001_О_035",
            "date": "2026-08-25",
            "posted": True,
            "status": "Закрыт",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        }
    ]
    report = score_protocol_kpi(
        events,
        protocols,
        as_of=date(2026, 9, 24),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert [row["plan_date"] for row in report["rows"]] == ["2026-09-25"]
    assert report["plan_source"] == "outlook"
    assert report["p_total"] == 1
    assert report["p_on_time"] == 1
    assert report["fact_pct"] == 100.0


def test_empty_calendar_uses_protocols_of_the_month():
    protocols = [
        {
            "number": "РК__001_О_036",
            "date": "2026-09-01",
            "posted": True,
            "status": "Закрыт",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        },
        {
            "number": "РК__001_О_039",
            "date": "2026-09-22",
            "posted": True,
            "status": "НаИсполнении",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        },
        {
            "number": "ПСД_001_О_226",
            "date": "2026-09-30",
            "posted": False,
            "status": "Подготовлен",
            "needs_review": True,
            "meeting_topic": "Совет директоров по ГК",
        },
        {
            "number": "РК__001_О_035",
            "date": "2026-08-25",
            "posted": True,
            "status": "Закрыт",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        },
    ]
    report = score_protocol_kpi(
        [],
        protocols,
        as_of=date(2026, 9, 24),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert report["plan_source"] == "protocols"
    assert {row["plan_date"] for row in report["rows"] if row["due"]} == {"2026-09-01", "2026-09-22"}
    assert report["p_total"] == 2
    assert report["fact_pct"] == 100.0


def test_late_protocol_fails_gate():
    events = [
        {"subject": "Совет директоров по Группе компаний", "start": "2026-08-07T16:00:00"},
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-08-25T14:00:00"},
    ]
    protocols = [
        {
            "number": "ПСД_001_О_174",
            "date": "2026-08-14",
            "posted": True,
            "status": "Закрыт",
            "meeting_topic": "Совет директоров по ГК",
        },
        {
            "number": "РК__001_О_035",
            "date": "2026-08-25",
            "posted": True,
            "status": "Закрыт",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        },
    ]
    report = score_protocol_kpi(events, protocols, as_of=date(2026, 9, 21))
    assert report["p_total"] == 2
    assert report["p_on_time"] == 1
    assert report["fact_pct"] == 50.0
    assert report["score_pct"] == 52.6
