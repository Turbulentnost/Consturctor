from datetime import date

from kpi.sources.assistant_unplanned import score_unplanned_meetings_kpi

AS_OF = date(2026, 9, 24)
START = date(2026, 9, 1)
END = date(2026, 9, 30)


def _memo(**extra):
    row = {
        "role": "plan",
        "Number": "СЗ-1",
        "DeletionMark": False,
        "Статус": "Согласована",
        "НаУровнеПСД": False,
        "ТемаСлужебнойЗаписки_Name": "Организация совещаний (регл.)",
        "ТемаСовещания": "Комиссионная приёмка",
        "ДатаПроведенияСовещания": "2026-09-10T00:00:00",
    }
    row.update(extra)
    return row


def _event(subject: str, start: str) -> dict:
    return {"role": "fact", "subject": subject, "start": start}


def test_psd_mark_is_not_in_plan():
    rows = [
        _memo(Number="СЗ-1", ТемаСовещания="Комиссионная приёмка"),
        _memo(
            Number="СЗ-2",
            НаУровнеПСД=True,
            ТемаСовещания="Совещание с ПСД",
            ДатаПроведенияСовещания="2026-09-12T09:00:00",
        ),
        _event("Комиссионная приёмка", "2026-09-10T10:00:00"),
    ]
    report = score_unplanned_meetings_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert [row["number"] for row in report["rows"]] == ["СЗ-1"]
    assert report["plan_total"] == 1
    assert report["in_calendar"] == 1
    assert report["violations"] == 0
    assert report["score_pct"] == 100.0
    assert report["weight"] == 30
    assert report["contrib_pct"] == 30.0


def test_missing_calendar_event_is_a_violation():
    rows = [
        _memo(Number="СЗ-1"),
        _event("Другая встреча", "2026-09-11T10:00:00"),
    ]
    report = score_unplanned_meetings_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["plan_total"] == 1
    assert report["in_calendar"] == 0
    assert report["violations"] == 1
    assert report["score_pct"] == 100.0
