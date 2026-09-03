from datetime import datetime

from app.tools.ac.com_backed_tools import (
    OutlookCreateEventComTool,
    OutlookReadCalendarComTool,
)

from app.tools.ac.workers.outlook_com_actions import (
    _attach_attendees,
    _compute_free_slots,
    _meeting_specs,
    _open_shared_calendar,
    _people_from_input,
    _people_names,
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


def test_people_names_from_string_and_list() -> None:
    assert _people_names("Иванов Иван; Петров П.П.") == ["Иванов Иван", "Петров П.П."]
    assert _people_from_input(
        {"attendees": [{"fio": "Сидоров"}, "a@turbo-don.ru"], "people": "Сидоров"}
    ) == ["Сидоров", "a@turbo-don.ru"]


def test_meeting_specs_keep_attendees_and_organizer() -> None:
    specs = _meeting_specs(
        {
            "subject": "Планерка",
            "start": "2026-09-07T10:00:00",
            "duration_minutes": 45,
            "attendees": ["Мангасарян Давид Каренович", "Уставицкий А. А."],
            "organizer": "Ильченко Екатерина Александровна",
        }
    )
    assert len(specs) == 1
    assert specs[0]["attendees"] == [
        "Мангасарян Давид Каренович",
        "Уставицкий А. А.",
    ]
    assert specs[0]["organizer"] == "Ильченко Екатерина Александровна"
    assert specs[0]["send_invites"] is True


def test_attach_attendees_marks_meeting() -> None:
    class _Recipients:
        def __init__(self) -> None:
            self.added: list[str] = []

        def Add(self, name: str):
            self.added.append(name)
            return type("R", (), {"Type": 0})()

        def ResolveAll(self) -> bool:
            return True

    appt = type("A", (), {})()
    appt.MeetingStatus = 0
    appt.Recipients = _Recipients()
    added = _attach_attendees(appt, ["Иванов", "Петров"])
    assert added == ["Иванов", "Петров"]
    assert appt.MeetingStatus == 1
    assert appt.Recipients.added == ["Иванов", "Петров"]


def test_open_shared_calendar_unresolved() -> None:
    class _Recipient:
        Resolved = False

        def Resolve(self) -> bool:
            return False

    class _Ns:
        def CreateRecipient(self, _name: str):
            return _Recipient()

    folder, status = _open_shared_calendar(_Ns(), "Неизвестный")
    assert folder is None
    assert status == "unresolved"


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


def test_com_worker_cancel_kills_process() -> None:
    from app.tools.ac.workers.subprocess_com_worker import SubprocessComWorker

    worker = SubprocessComWorker()

    class _Proc:
        def __init__(self) -> None:
            self.killed = False

        def poll(self):
            return None

        def kill(self) -> None:
            self.killed = True

    proc = _Proc()
    worker._process = proc  # type: ignore[assignment]
    assert worker.cancel() is True
    assert proc.killed is True
    assert worker._cancelled is True


def test_calendar_default_range_is_a_year() -> None:
    from app.tools.ac.workers.outlook_com_actions import (
        DEFAULT_CALENDAR_MAX_RESULTS,
        DEFAULT_DAYS_FORWARD,
        MAX_CALENDAR_RESULTS,
    )

    assert DEFAULT_DAYS_FORWARD >= 365
    assert DEFAULT_CALENDAR_MAX_RESULTS > 50
    assert MAX_CALENDAR_RESULTS > 50


class _CountHangItems:
    def __init__(self, rows: list) -> None:
        self._rows = rows
        self._index = -1
        self.count_calls = 0

    @property
    def Count(self) -> int:
        self.count_calls += 1
        raise AssertionError("Count must not be used for recurring calendar items")

    def GetFirst(self):
        self._index = 0
        return self._rows[0] if self._rows else None

    def GetNext(self):
        self._index += 1
        if 0 <= self._index < len(self._rows):
            return self._rows[self._index]
        return None

    def __iter__(self):
        raise AssertionError("for-in must not walk Outlook Items")


class _Event:
    def __init__(self, start: datetime, subject: str = "Meeting") -> None:
        self.Start = start
        self.End = start.replace(hour=start.hour + 1) if start.hour < 23 else start
        self.EntryID = "id-1"
        self.Subject = subject
        self.Location = "Room"
        self.Body = "X" * 400

    def __getattr__(self, name: str):
        if name == "PropertyAccessor":
            raise RuntimeError("no accessor in unit test")
        raise AttributeError(name)


def test_calendar_iterates_without_count() -> None:
    from app.tools.ac.workers.outlook_com_actions import _collect_calendar_events

    start = datetime(2026, 8, 20, 10, 0, 0)
    items = _CountHangItems([_Event(start)])
    events, scanned = _collect_calendar_events(
        items, datetime(2026, 8, 20), datetime(2026, 8, 21), 10, 20
    )
    assert scanned == 1
    assert events[0]["subject"] == "Meeting"
    assert events[0]["body_preview"] == ""
    assert items.count_calls == 0


def test_calendar_body_is_opt_in() -> None:
    from app.tools.ac.workers.outlook_com_actions import _collect_calendar_events

    start = datetime(2026, 8, 20, 10, 0, 0)
    items = _CountHangItems([_Event(start)])
    events, _scanned = _collect_calendar_events(
        items,
        datetime(2026, 8, 20),
        datetime(2026, 8, 21),
        10,
        20,
        include_body=True,
    )
    assert events[0]["body_preview"]


def test_month_windows_split_year() -> None:
    from app.tools.ac.workers.outlook_com_actions import _month_windows

    windows = _month_windows(datetime(2026, 8, 1), datetime(2026, 10, 1))
    assert len(windows) == 2
    assert windows[0][0] == datetime(2026, 8, 1)
    assert windows[0][1] == datetime(2026, 9, 1)
    assert windows[1][1] == datetime(2026, 10, 1)


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


def test_event_involves_person_by_organizer_and_attendees() -> None:
    from app.tools.ac.workers.outlook_com_actions import event_involves_person

    ilchenko = "Ильченко Екатерина Александровна"
    assert event_involves_person(
        {"organizer": "Ильченко Екатерина Александровна", "required_attendees": ""},
        ilchenko,
    )
    assert event_involves_person(
        {
            "organizer": "Донцова Анна Егоровна",
            "required_attendees": "Ильченко Е.А.; Мангасарян Д.К.",
        },
        ilchenko,
    )
    assert event_involves_person(
        {"subject": "Планерка с Ильченко Екатериной", "organizer": "Донцова"},
        ilchenko,
    )
    assert not event_involves_person(
        {
            "organizer": "Мангасарян Давид Каренович",
            "required_attendees": "Уставицкий А. А.",
            "subject": "Планерное совещание",
        },
        ilchenko,
    )


def test_same_calendar_person_matches_partial_fio() -> None:
    from app.tools.ac.workers.outlook_com_actions import _same_calendar_person

    assert _same_calendar_person(
        "Ильченко Екатерина Александровна",
        "Ильченко Екатерина Александровна",
    )
    assert _same_calendar_person("Ильченко Екатерина Александровна", "Ильченко Е. А.")
    assert not _same_calendar_person("Ильченко", "")


def test_restrict_filters_put_russian_locale_first() -> None:
    from app.tools.ac.workers.outlook_com_actions import restrict_filter_strings

    filters = restrict_filter_strings(datetime(2026, 8, 31, 0, 0), datetime(2026, 9, 7, 0, 0))
    assert filters[0] == "[Start] >= '31.08.2026 00:00' AND [Start] <= '07.09.2026 00:00'"
    assert any("08/31/2026" in item for item in filters)


def test_iso_com_datetime_normalizes_naive_and_text() -> None:
    from app.tools.ac.workers.outlook_com_actions import _iso_com_datetime

    assert _iso_com_datetime(datetime(2026, 9, 3, 14, 0, 0)) == "2026-09-03T14:00:00"
    assert _iso_com_datetime("2026-09-03 14:00:00") == "2026-09-03T14:00:00"


def test_collect_range_retries_restrict_when_us_filter_is_empty() -> None:
    from app.tools.ac.workers.outlook_com_actions import _collect_calendar_range

    class _Item:
        def __init__(self) -> None:
            self.EntryID = "e1"
            self.Subject = "Планерка"
            self.Start = datetime(2026, 9, 3, 10, 0, 0)
            self.End = datetime(2026, 9, 3, 11, 0, 0)
            self.Location = ""
            self.PropertyAccessor = type("A", (), {"GetProperty": staticmethod(lambda _s: "")})()

    class _Items:
        def Restrict(self, restriction: str):
            if "31.08.2026" in restriction:
                return [_Item()]
            return []

    events, scanned = _collect_calendar_range(
        _Items(),
        datetime(2026, 8, 31),
        datetime(2026, 9, 7),
        max_results=20,
        max_scan_items=50,
        include_body=False,
    )
    assert scanned >= 1
    assert events[0]["subject"] == "Планерка"
    assert events[0]["start"] == "2026-09-03T10:00:00"
