from datetime import date

from kpi.sources.assistant_orders import (
    DIRECTIVE_ENTITY,
    ORDER_ENTITY,
    USER_ENTITY,
    compute_orders_registration_kpi,
    odata_filter,
    score_orders_registration_kpi,
)

AS_OF = date(2026, 9, 24)
START = date(2026, 9, 1)
END = date(2026, 9, 30)
USER = "7a3fa603-0899-11f0-9637-6cb31113810e"


def test_plan_equals_fact_for_orders_and_directives():
    rows = [
        {"kind": "order", "number": "НП00-000337", "date": "2026-09-23", "subject": "Архив"},
        {"kind": "directive", "number": "НП00-000104", "date": "2026-09-23", "subject": "ТС"},
        {"kind": "order", "number": "НП00-000200", "date": "2026-08-31", "subject": "прошлый месяц"},
    ]
    report = score_orders_registration_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["orders"] == 1
    assert report["directives"] == 1
    assert report["count"] == 2
    assert report["plan"] == report["fact"] == 2
    assert report["fact_pct"] == 100.0
    assert report["contrib_pct"] == 10.0
    by_kind = {row["doc_kind"]: row["content"] for row in report["rows"]}
    assert by_kind == {"Приказ": "Архив", "Распоряжение": "ТС"}
    assert all("subject" not in row for row in report["rows"])


def test_empty_month_still_matches():
    report = score_orders_registration_kpi([], as_of=AS_OF, date_from=START, date_to=END)
    assert report["count"] == 0
    assert report["plan"] == 0
    assert report["fact"] == 0
    assert report["fact_pct"] == 100.0


def test_deleted_document_is_skipped():
    rows = [
        {"kind": "order", "Number": "НП00-1", "Date": "2026-09-02T10:00:00", "DeletionMark": True},
        {"entity": ORDER_ENTITY, "Number": "НП00-2", "Date": "2026-09-02T10:00:00", "Posted": False},
    ]
    report = score_orders_registration_kpi(rows, as_of=AS_OF, date_from=START, date_to=END)
    assert report["orders"] == 1
    assert report["rows"][0]["posted"] is False
    assert report["rows"][0]["number"] == "НП00-2"


def test_compute_pages_both_entities():
    calls: list[dict] = []

    class _Ctx:
        date_from = START
        date_to = END

        def extra_for(self):
            return {}

        def load_for(self, extra):
            calls.append(dict(extra))
            if extra.get("entity") == USER_ENTITY:
                return [{"Ref_Key": USER, "Description": "Акинина Татьяна Владимировна"}]
            if extra.get("entity") == ORDER_ENTITY and not extra.get("skip"):
                return [{"Number": "НП00-1", "Date": "2026-09-02T09:00:00", "Ref_Key": "a"}]
            if extra.get("entity") == DIRECTIVE_ENTITY and not extra.get("skip"):
                return [{"Number": "НП00-9", "Date": "2026-09-14T15:00:00", "Ref_Key": "b"}]
            return []

    report = compute_orders_registration_kpi(_Ctx(), as_of=AS_OF)
    entities = [call.get("entity") for call in calls]
    assert USER_ENTITY in entities
    assert ORDER_ENTITY in entities
    assert DIRECTIVE_ENTITY in entities
    assert report["orders"] == 1
    assert report["directives"] == 1
    assert report["plan"] == report["fact"] == 2
    assert USER in odata_filter(USER, START, END)
