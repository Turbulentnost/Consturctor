from __future__ import annotations

from datetime import date

from kpi.sources.sd_rk_packages import package_deadline, score_package_kpi, series_key
from kpi.sources.sd_rk_protocols import sub_workdays


def test_package_deadline_skips_weekend():
    assert sub_workdays(date(2026, 8, 7), 2) == date(2026, 8, 5)
    assert sub_workdays(date(2026, 8, 25), 2) == date(2026, 8, 21)
    assert package_deadline(date(2026, 8, 28)) == date(2026, 8, 26)


def test_series_key_splits_sd_and_keeps_rk():
    assert series_key("rk", "Еженедельное совещание с ревизионной комиссией") == "rk"
    assert series_key("sd", "Совет директоров по Группе компаний") == "sd:gk"
    assert series_key("sd", "Совет директоров по ГК") == "sd:gk"
    assert series_key("sd", "Совет директоров ГК (ИТЦ, Авион, Магакян)") == "sd:itc"
    assert series_key("sd", "Совет директоров по ГК (ООО «ИТЦ», ООО «Авион»)") == "sd:itc"


def test_previous_closed_protocol_before_next_outlook_meeting():
    events = [
        {"subject": "Совет директоров ГК (ИТЦ, Авион, Магакян)", "start": "2026-08-07T16:00:00"},
        {"subject": "Совет директоров ГК (ИТЦ, Авион, Магакян)", "start": "2026-08-28T14:00:00"},
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-08-25T14:00:00"},
        {"subject": "Совет директоров по Группе компаний", "start": "2026-08-27T10:00:00"},
        {
            "subject": "Секретарь РК еженедельно формирует и утверждает повестку заседания",
            "start": "2026-08-25T07:30:00",
        },
    ]
    protocols = [
        {
            "number": "ПСД_001_О_160",
            "date": "2026-07-31",
            "status": "Закрыт",
            "meeting_topic": "Совет директоров по ГК (ООО «ИТЦ», ООО «Авион»)",
        },
        {
            "number": "ПСД_001_О_174",
            "date": "2026-08-07",
            "status": "Закрыт",
            "closed_at": "2026-08-26",
            "meeting_topic": "Совет директоров по ГК (ООО «ИТЦ», ООО «Авион»)",
        },
        {
            "number": "РК__001_О_034",
            "date": "2026-08-18",
            "status": "Закрыт",
            "closed_at": "2026-08-21",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        },
        {
            "number": "ПСД_001_О_190",
            "date": "2026-08-20",
            "status": "Закрыт",
            "closed_at": "2026-08-25",
            "meeting_topic": "Совет директоров по ГК",
        },
    ]
    report = score_package_kpi(
        events,
        protocols,
        as_of=date(2026, 9, 21),
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
    )
    by_date = {row["plan_date"]: row for row in report["rows"]}
    assert by_date["2026-08-07"]["protocol_number"] == "ПСД_001_О_160"
    assert by_date["2026-08-28"]["protocol_number"] == "ПСД_001_О_174"
    assert by_date["2026-08-25"]["protocol_number"] == "РК__001_О_034"
    assert by_date["2026-08-27"]["protocol_number"] == "ПСД_001_О_190"
    assert report["z_total"] == 4
    assert report["z_on_time"] == 4
    assert report["fact_pct"] == 100


def test_draft_or_late_previous_protocol_is_not_on_time():
    events = [
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-08-18T14:00:00"},
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-08-25T14:00:00"},
        {"subject": "Совет директоров по Группе компаний", "start": "2026-08-27T10:00:00"},
    ]
    protocols = [
        {
            "number": "РК__001_О_034",
            "date": "2026-08-18",
            "status": "Подготовлен",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        },
        {
            "number": "ПСД_001_О_190",
            "date": "2026-08-20",
            "status": "Закрыт",
            "closed_at": "2026-08-26",
            "meeting_topic": "Совет директоров по ГК",
        },
    ]
    report = score_package_kpi(
        events,
        protocols,
        as_of=date(2026, 9, 21),
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
    )
    by_date = {row["plan_date"]: row for row in report["rows"]}
    assert by_date["2026-08-18"]["on_time"] is False
    assert by_date["2026-08-25"]["protocol_number"] == "РК__001_О_034"
    assert by_date["2026-08-25"]["on_time"] is False
    assert by_date["2026-08-27"]["closed_at"] == "2026-08-26"
    assert by_date["2026-08-27"]["deadline"] == "2026-08-25"
    assert by_date["2026-08-27"]["on_time"] is False
    assert report["z_on_time"] == 0
    assert report["z_total"] == 3


def test_in_progress_status_counts_as_ready():
    events = [
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-08-25T14:00:00"},
    ]
    protocols = [
        {
            "number": "РК__001_О_034",
            "date": "2026-08-18",
            "status": "НаИсполнении",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        }
    ]
    report = score_package_kpi(events, protocols, as_of=date(2026, 9, 21))
    assert report["z_total"] == 1
    assert report["z_on_time"] == 1
    assert report["rows"][0]["closed_at"] == "2026-08-18"


def test_future_meeting_not_in_denominator():
    events = [
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-09-15T10:00:00"},
        {"subject": "Еженедельное совещание с ревизионной комиссией", "start": "2026-09-30T14:00:00"},
    ]
    protocols = [
        {
            "number": "РК__001_О_038",
            "date": "2026-09-15",
            "status": "Закрыт",
            "closed_at": "2026-09-18",
            "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
        }
    ]
    report = score_package_kpi(events, protocols, as_of=date(2026, 9, 21))
    due = [row for row in report["rows"] if row["due"]]
    pending = [row for row in report["rows"] if not row["due"]]
    assert {row["plan_date"] for row in due} == {"2026-09-15"}
    assert due[0]["on_time"] is False
    assert {row["plan_date"] for row in pending} == {"2026-09-30"}
    assert pending[0]["protocol_number"] == "РК__001_О_038"


def test_protocols_only_use_next_meeting_and_closed_date():
    protocols = [
        {
            "number": "ПСД_001_О_219",
            "date": "2026-09-04",
            "status": "Закрыт",
            "closed_at": "2026-09-09",
            "meeting_topic": "Совет директоров по ГК",
            "ДатаСледующегоСовещания": "2026-09-11",
        },
        {
            "number": "ПСД_001_О_225",
            "date": "2026-09-11",
            "status": "Подготовлен",
            "meeting_topic": "Совет директоров по ГК",
        },
    ]
    report = score_package_kpi([], protocols, as_of=date(2026, 9, 21))
    assert report["z_total"] == 1
    assert report["z_on_time"] == 1
    assert report["rows"][0]["protocol_number"] == "ПСД_001_О_219"
    assert report["rows"][0]["plan_date"] == "2026-09-11"
    assert report["rows"][0]["deadline"] == "2026-09-09"
    assert report["rows"][0]["closed_at"] == "2026-09-09"
