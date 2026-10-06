from datetime import date

from app.services.docflow_protocols import is_board_report_task, pick_month_protocol

TASK = (
    "За 2 рабочих дня до проведения Совета директоров по ГК предоставлять "
    "управленческую отчетность за прошедший месяц"
)


def test_board_report_task_matches_director_report() -> None:
    assert is_board_report_task(TASK)
    assert is_board_report_task(TASK.replace("отчетность", "отчётность"))
    assert not is_board_report_task("Доклад по повестке совета директоров")
    assert not is_board_report_task("")


def test_pick_month_protocol_prefers_current_month() -> None:
    older = {"Date": "2026-09-30T00:00:00", "Number": "226"}
    current = {"Date": "2026-10-02T00:00:00", "Number": "250"}
    picked = pick_month_protocol([older, current], date(2026, 10, 5))
    assert picked is current


def test_pick_month_protocol_falls_back_to_latest() -> None:
    latest = {"Date": "2026-09-30T00:00:00", "Number": "226"}
    older = {"Date": "2026-08-27T00:00:00", "Number": "201"}
    picked = pick_month_protocol([older, latest], date(2026, 10, 5))
    assert picked is latest
