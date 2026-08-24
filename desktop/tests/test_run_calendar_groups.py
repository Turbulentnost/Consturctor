from datetime import datetime, timedelta, timezone

from app.api_client import CalendarEvent
from app.ui.widgets.run_calendar import group_by_slot, group_summary, parse_iso, _runs_word


def _event(wid: str, hour: int, minute: int = 0, status: str = "scheduled") -> CalendarEvent:
    return CalendarEvent(
        id=wid,
        workflow_id=wid,
        title=wid,
        start_at=f"2026-08-19T{hour:02d}:{minute:02d}:00+03:00",
        status=status,
        run_id=f"run-{wid}",
    )


def test_single_slot_stays_ungrouped() -> None:
    groups = group_by_slot([_event("a", 9), _event("b", 10)])
    assert [len(group) for group in groups] == [1, 1]


def test_same_hour_is_one_cell_group() -> None:
    groups = group_by_slot([_event("a", 10, 0), _event("b", 10, 15), _event("c", 10, 40)])
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_same_minute_different_agents_group() -> None:
    groups = group_by_slot([_event("a", 10, 6), _event("b", 10, 6), _event("c", 10, 6)])
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_same_agent_hour_is_history() -> None:
    events = [
        CalendarEvent(
            id=f"r{index}",
            workflow_id="wf-1",
            title="Контроль",
            start_at=f"2026-08-19T10:{minute:02d}:00+03:00",
            status="ok",
        )
        for index, minute in enumerate((6, 26, 46))
    ]
    groups = group_by_slot(events)
    assert len(groups) == 1
    assert len(groups[0]) == 3
    _title, subtitle, _color = group_summary(groups[0])
    assert subtitle == "История"


def test_error_badge_and_running_summary() -> None:
    title, subtitle, color = group_summary(
        [_event("a", 10, status="ok"), _event("b", 10, status="error"), _event("c", 10)]
    )
    assert "3" in title
    assert subtitle == "1 ошибка"
    assert color == "#D64545"
    _, running, _ = group_summary(
        [_event("a", 10, status="running"), _event("b", 10, status="running"), _event("c", 10)]
    )
    assert running == "Выполняются 2 из 3"


def test_same_agent_errors_keep_red_badge() -> None:
    events = [
        CalendarEvent(id="1", workflow_id="wf", title="A", start_at="2026-08-19T10:00:00+03:00", status="ok"),
        CalendarEvent(id="2", workflow_id="wf", title="A", start_at="2026-08-19T10:20:00+03:00", status="error"),
    ]
    _title, subtitle, color = group_summary(events)
    assert subtitle == "1 ошибка"
    assert color == "#D64545"


def test_missed_group_is_not_history() -> None:
    events = [
        CalendarEvent(
            id="1",
            workflow_id="wf",
            title="A",
            start_at="2026-08-19T10:00:00+03:00",
            status="missed",
        ),
        CalendarEvent(
            id="2",
            workflow_id="wf",
            title="A",
            start_at="2026-08-19T10:20:00+03:00",
            status="missed",
        ),
    ]
    _title, subtitle, color = group_summary(events)
    assert subtitle == "Не запущены"
    assert color == "#B0893A"


def test_runs_word() -> None:
    assert _runs_word(1) == "запуск"
    assert _runs_word(2) == "запуска"
    assert _runs_word(3) == "запуска"
    assert _runs_word(5) == "запусков"


def test_parse_iso_utc_keeps_instant() -> None:
    stamp = parse_iso("2026-08-21T05:23:46.869678+00:00")
    assert stamp is not None
    utc = stamp.astimezone(timezone.utc)
    assert utc.hour == 5
    assert utc.minute == 23
    naive = parse_iso("2026-08-21T05:23:46.869678")
    assert naive is not None
    assert naive.astimezone(timezone.utc).hour == 5
