from __future__ import annotations

from datetime import date

from kpi.sources.assistant_tasks import (
    compute_individual_tasks_kpi,
    score_individual_tasks_kpi,
)

AS_OF = date(2026, 9, 24)
START = date(2026, 9, 1)
END = date(2026, 9, 30)
PERFORMER = "Акинина Татьяна Владимировна"
AUTHOR = "Донцова Анна Егоровна"


def _task(**extra):
    row = {
        "number": "Т-1",
        "description": "Подготовить справку",
        "performer": PERFORMER,
        "author": AUTHOR,
        "begin": "2026-09-10T09:00:00",
        "executed": False,
    }
    row.update(extra)
    return row


def test_plan_is_month_tasks_from_dontsova_fact_is_done():
    rows = [
        _task(number="Т-1", executed=True),
        _task(number="Т-2", description="Согласовать график", begin="2026-09-12T09:00:00"),
        _task(number="Т-3", author="Ильченко Екатерина Александровна"),
        _task(number="Т-4", performer="Ильченко Екатерина Александровна"),
        _task(number="Т-5", begin="2026-08-31T09:00:00", executed=True),
    ]
    report = score_individual_tasks_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["plan_total"] == 2
    assert report["done_total"] == 1
    assert report["fact_pct"] == 50.0
    assert report["score_pct"] == 50.0
    assert report["contrib_pct"] == 5.0
    assert [row["number"] for row in report["rows"]] == ["Т-1", "Т-2"]


def test_initials_match_full_names():
    rows = [
        _task(
            performer="Акинина Т.В.",
            author="Донцова А.Е.",
            executed=True,
        )
    ]
    report = score_individual_tasks_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["plan_total"] == 1
    assert report["done_total"] == 1
    assert report["fact_pct"] == 100.0


def test_other_dontsova_is_not_the_author():
    rows = [_task(author="Донцова Мария Ивановна")]
    report = score_individual_tasks_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["plan_total"] == 0
    assert report["fact_pct"] is None
    assert report["score_pct"] is None


def test_empty_month_has_no_score():
    report = score_individual_tasks_kpi([], as_of=AS_OF, date_from=START, date_to=END)
    assert report["plan_total"] == 0
    assert report["done_total"] is None
    assert report["contrib_pct"] is None


def test_status_text_counts_as_done():
    rows = [_task(executed=False, state="Выполнена")]
    report = score_individual_tasks_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["done_total"] == 1


def test_open_cache_flag_is_kept():
    rows = [_task(_includes_completed=False)]
    report = score_individual_tasks_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["includes_completed"] is False
    assert report["done_total"] == 0


def test_compute_loads_through_context():
    class _Ctx:
        date_from = START
        date_to = END

        def extra_for(self):
            return {}

        def load_for(self, extra):
            assert extra.get("loader") == "docflow"
            assert extra.get("performer") == PERFORMER
            return [_task(executed=True), _task(number="Т-2", begin="2026-09-20T09:00:00")]

    report = compute_individual_tasks_kpi(_Ctx(), as_of=AS_OF)
    assert report["plan_total"] == 2
    assert report["done_total"] == 1
    assert report["fact_pct"] == 50.0
