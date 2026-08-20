from datetime import datetime

from app.tools.ac.com_backed_tools import (
    OutlookCreateEventComTool,
    OutlookReadCalendarComTool,
)

from app.tools.ac.workers.outlook_com_actions import (
    _compute_free_slots,
    stamp_ai_agent_meeting,
)


class _DummyWorker:
    def execute(self, task):
        return None


def test_outlook_com_timeout_allows_slow_calendar() -> None:
    worker = _DummyWorker()
    assert OutlookReadCalendarComTool(worker).definition.timeout_seconds >= 180
    assert OutlookCreateEventComTool(worker).definition.timeout_seconds >= 180


def test_outlook_create_runs_in_gui_process() -> None:
    from app.tools.ac.dispatch import build_registry
    from app.tools.ac.workers.outlook_com_worker import OutlookComWorker
    from app.tools.ac.workers.subprocess_com_worker import SubprocessComWorker

    registry = build_registry()
    create = registry.get("outlook.create_event")
    read = registry.get("outlook.read_calendar")
    assert isinstance(create._worker, OutlookComWorker)
    assert isinstance(read._worker, SubprocessComWorker)


def test_outlook_save_failure_is_retried() -> None:
    from app.tools.ac.workers.outlook_com_actions import _is_transient_com_error

    err = Exception("placeholder")
    err.args = (
        -2147352567,
        "Ошибка.",
        (4096, "Microsoft Outlook", "Не выполнено.", None, 0, -2147467263),
        None,
    )
    assert _is_transient_com_error(err)


def test_stamp_ai_agent_meeting_adds_prefix_and_footer() -> None:
    subject, body = stamp_ai_agent_meeting("Серия совещаний", "План на неделю")
    assert subject.startswith("[ИИ-агент]")
    assert "Серия совещаний" in subject
    assert "Создано ИИ-агентом Constructor." in body


def test_stamp_ai_agent_meeting_is_idempotent() -> None:
    subject, body = stamp_ai_agent_meeting("[ИИ-агент] Уже помечено", "Создано ИИ-агентом Constructor.")
    assert subject.count("[ИИ-агент]") == 1
    assert body.count("Создано ИИ-агентом Constructor.") == 1


def test_verify_save_requires_entry_id() -> None:
    from app.tools.ac.workers.outlook_com_actions import (
        OutlookAccessError,
        _verify_saved_appointment,
    )

    class _Appt:
        EntryID = ""

    try:
        _verify_saved_appointment(object(), _Appt())
    except OutlookAccessError as exc:
        assert "не вернул идентификатор" in str(exc).casefold() or "идентификатор" in str(exc).casefold()
        return
    raise AssertionError("empty EntryID must fail verification")


def test_verify_save_requires_readable_item() -> None:
    from app.tools.ac.workers.outlook_com_actions import (
        OutlookAccessError,
        _verify_saved_appointment,
    )

    class _Appt:
        EntryID = "entry-1"

    class _Ns:
        def GetItemFromID(self, _entry_id):
            return None

    class _Outlook:
        def GetNamespace(self, _kind):
            return _Ns()

    try:
        _verify_saved_appointment(_Outlook(), _Appt())
    except OutlookAccessError:
        return
    raise AssertionError("missing calendar item after Save must fail")


def test_calendar_default_range_is_a_year() -> None:
    from app.tools.ac.workers.outlook_com_actions import (
        DEFAULT_CALENDAR_MAX_RESULTS,
        DEFAULT_DAYS_FORWARD,
        MAX_CALENDAR_RESULTS,
    )

    assert DEFAULT_DAYS_FORWARD >= 365
    assert DEFAULT_CALENDAR_MAX_RESULTS > 50
    assert MAX_CALENDAR_RESULTS > 50


def test_free_slots_skip_busy_work_hours() -> None:
    start = datetime(2026, 8, 20, 0, 0, 0)  # Thursday
    end = datetime(2026, 8, 21, 0, 0, 0)
    events = [
        {"start": "2026-08-20 10:00:00", "end": "2026-08-20 11:00:00"},
    ]
    slots = _compute_free_slots(events, start, end)
    assert slots[0]["start"].startswith("2026-08-20T09:00")
    assert any(item["start"].startswith("2026-08-20T11:00") for item in slots)
    assert all(not (item["start"] <= "2026-08-20T10:00" < item["end"]) for item in slots)
