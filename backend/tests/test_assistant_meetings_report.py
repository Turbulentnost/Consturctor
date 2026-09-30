from __future__ import annotations

from datetime import date

from kpi.sources.assistant_meetings_report import (
    PLAN_ENTITY,
    compute_report_plan_fact_kpi,
    format_report,
    score_report_plan_fact,
)

LEADER = "f74842ae-4ca2-11ee-93e5-6cb31113810e"
START = date(2026, 9, 1)
END = date(2026, 9, 30)
THEMES = [
    {"Ref_Key": "t1", "ВидСовещания": "Отчетное", "ТемаКругаУправления": True},
    {"Ref_Key": "t2", "ВидСовещания": "Внеплановое", "ТемаКругаУправления": True},
    {"Ref_Key": "t3", "ВидСовещания": "Отчетное", "ТемаКругаУправления": False},
]


def _protocol(day: str, theme: str = "t1", kind: str = "Отчетное", **extra) -> dict:
    return {
        "Date": f"{day}T10:00:00",
        "ТемаСовещания_Key": theme,
        "ВидСовещания": kind,
        "Руководитель_Key": LEADER,
        "DeletionMark": False,
        **extra,
    }


def _plan(day: str, theme: str = "t1") -> dict:
    return {"ДатаСовещания": f"{day}T00:00:00", "ТемаСовещания_Key": theme, "РуководительСовещания_Key": LEADER}


def _score(plan, protocols, **kwargs):
    return score_report_plan_fact(
        plan, protocols, THEMES, leader_key=LEADER, as_of=END, date_from=START, date_to=END, **kwargs
    )


def test_empty_calendar_shows_facts_like_report_and_no_score() -> None:
    report = _score(
        [],
        [
            _protocol("2026-09-01"),
            _protocol("2026-09-01"),
            _protocol("2026-09-02"),
            _protocol("2026-09-02", theme="t3"),
            _protocol("2026-09-02", kind="Внеплановое"),
            _protocol("2026-09-02", DeletionMark=True),
            {**_protocol("2026-09-02"), "Руководитель_Key": "other"},
        ],
    )
    assert report["rows"] == [
        {"day": "2026-09-01", "plan": 0, "fact": 2, "deviation": 2},
        {"day": "2026-09-02", "plan": 0, "fact": 1, "deviation": 1},
    ]
    assert report["score_pct"] is None and report["fact_pct"] is None
    assert "нет плана" in format_report(report)


def test_missed_planned_meetings_are_violations() -> None:
    plan = [_plan("2026-09-0%d" % day) for day in range(1, 8)] + [_plan("2026-09-08", theme="t2")]
    protocols = [_protocol("2026-09-01"), _protocol("2026-09-02"), _protocol("2026-09-02")]
    report = _score(plan, protocols)
    assert report["plan_total"] == 7
    assert report["fact_total"] == 3
    assert report["violations"] == 5
    assert report["score_pct"] == 50.0
    assert report["contrib_pct"] == 20.0
    assert report["rows"][1] == {"day": "2026-09-02", "plan": 1, "fact": 2, "deviation": 1}


def test_empty_calendar_can_borrow_plan_from_fact() -> None:
    report = _score([], [_protocol("2026-09-01"), _protocol("2026-09-02")], plan_from_fact=True)
    assert report["plan_source"] == "fact"
    assert report["plan_total"] == report["fact_total"] == 2
    assert report["violations"] == 0
    assert report["score_pct"] == 100.0
    assert report["rows"][0] == {"day": "2026-09-01", "plan": 1, "fact": 1, "deviation": 0}
    assert "План = факт = 2 (временно" in format_report(report)


def test_real_calendar_wins_over_fact_fallback() -> None:
    report = _score([_plan("2026-09-01"), _plan("2026-09-02")], [_protocol("2026-09-01")], plan_from_fact=True)
    assert report["plan_source"] == "calendar"
    assert report["violations"] == 1


class _Ctx:
    def __init__(self, *, plan_published: bool, extra: dict | None = None) -> None:
        self.as_of = END
        self.date_from = START
        self.date_to = END
        self.source_errors: list[str] = []
        self.plan_published = plan_published
        self.extra = extra or {}
        self.requests: list[dict] = []

    def extra_for(self, *_args):
        return dict(self.extra)

    def load_for(self, extra: dict) -> list[dict]:
        self.requests.append(extra)
        entity = extra["entity"]
        if entity == "Catalog_Пользователи":
            return [{"Ref_Key": LEADER, "Description": "Донцова Анна Егоровна"}]
        if entity == "Catalog_ТД_ТемыСовещаний":
            return THEMES
        if entity == "Document_ТД_Протокол":
            return [_protocol("2026-09-03")]
        if entity == PLAN_ENTITY:
            if not self.plan_published:
                self.source_errors.append(f"1С {entity}: 1C OData HTTP 404: Сущность не найдена")
                return []
            return [_plan("2026-09-03")]
        raise AssertionError(entity)


def test_unpublished_calendar_uses_fact_as_plan_by_default() -> None:
    ctx = _Ctx(plan_published=False)
    report = compute_report_plan_fact_kpi(ctx, as_of=END)
    assert ctx.source_errors == []
    assert report["plan_source"] == "fact"
    assert report["score_pct"] == 100.0
    assert "не опубликован в OData" in format_report(report)


def test_unpublished_calendar_without_fallback_explains_itself_and_keeps_facts() -> None:
    ctx = _Ctx(plan_published=False, extra={"plan_from_fact": False})
    report = compute_report_plan_fact_kpi(ctx, as_of=END)
    assert ctx.source_errors == []
    assert report["fact_total"] == 1
    assert report["score_pct"] is None
    assert "не опубликован в OData" in format_report(report)
    protocol_request = next(item for item in ctx.requests if item["entity"] == "Document_ТД_Протокол")
    assert f"Руководитель_Key eq guid'{LEADER}'" in protocol_request["filter"]
    assert "ТемаСовещания_Key" in protocol_request["select"]


def test_published_calendar_scores_like_report() -> None:
    report = compute_report_plan_fact_kpi(_Ctx(plan_published=True), as_of=END)
    assert report["plan_total"] == 1 and report["fact_total"] == 1
    assert report["violations"] == 0
    assert report["score_pct"] == 100.0
