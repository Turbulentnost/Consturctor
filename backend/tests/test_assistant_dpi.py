from datetime import date

from kpi.sources.assistant_dpi import (
    compute_dpi_appointment_kpi,
    score_dpi_appointment_kpi,
)

AS_OF = date(2026, 9, 23)
START = date(2026, 9, 1)
END = date(2026, 9, 30)


def _rule(**extra):
    row = {
        "role": "plan",
        "number": 1,
        "name": "ДПИ СУП",
        "rule": "5 числа каждого месяца",
        "excel_fact": {9: "2026-09-01"},
    }
    row.update(extra)
    return row


def test_plan_date_comes_from_rule_not_month_cell():
    rows = [
        _rule(),
        {"role": "fact", "subject": "ДПИ СУП", "start": "2026-09-07T10:00:00"},
    ]
    report = score_dpi_appointment_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["plan_total"] == 1
    assert report["rows"][0]["plan_date"] == "2026-09-07"
    assert report["rows"][0]["appointed"] is True
    assert report["fact_pct"] == 100.0
    assert report["contrib_pct"] == 10.0


def test_red_marked_rule_is_not_in_plan():
    rows = [
        _rule(),
        _rule(number=17, name="ДПИ сектора внедрения ИИ", rule="15 числа каждого месяца", excluded=True),
        {"role": "fact", "subject": "ДПИ СУП", "start": "2026-09-07T10:00:00"},
    ]
    report = score_dpi_appointment_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["plan_total"] == 1
    assert report["rows"][0]["number"] == 1


def test_missing_calendar_event_lowers_fact():
    rows = [
        _rule(),
        _rule(number=16, name="ДПИ юридический отдел", rule="5 числа каждого месяца"),
        {"role": "fact", "subject": "ДПИ СУП", "start": "2026-09-07T10:00:00"},
    ]
    report = score_dpi_appointment_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["plan_total"] == 2
    assert report["in_calendar"] == 1
    assert report["fact_pct"] == 50.0
    assert report["contrib_pct"] == 5.0


def test_compute_reads_rules_and_outlook():
    class _Ctx:
        date_from = START
        date_to = END

        def load_for(self, extra):
            assert extra.get("folder") == "Совещания"
            if extra.get("loader") == "files":
                return [_rule()]
            assert extra.get("loader") == "outlook"
            return [{"subject": "ДПИ СУП", "start": "2026-09-07T10:00:00"}]

    report = compute_dpi_appointment_kpi(_Ctx(), as_of=AS_OF)
    assert report["plan_total"] == 1
    assert report["in_calendar"] == 1
    assert report["rows"][0]["plan_date"] == "2026-09-07"
