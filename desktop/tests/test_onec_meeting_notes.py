from datetime import date

from app.tools.ac.workers.onec_actions import ALLOWED_ONEC_TOOLS, list_meeting_service_notes
from app.tools.ac.workers.onec_com32_helper import connection_string
from app.tools.ac.workers.onec_meeting_notes import (
    assert_select_only,
    build_document_search_query_latin,
    build_incoming_search_query_latin,
    build_meeting_notes_query,
    build_meeting_notes_query_latin,
    document_from_com32_row,
    meeting_params_from_row,
    parse_note_period,
    person_needles,
    pick_document_name,
)
from app.tools.ac.onec_tools import ONEC_COM32_RUNTIME, ONEC_COM32_TOOLS, OneCMeetingServiceNotesTool
from app.tools.hitl import needs_confirmation


def test_period_single_day() -> None:
    start, end = parse_note_period({"date": "2026-08-19"})
    assert start == end == date(2026, 8, 19)


def test_period_range() -> None:
    start, end = parse_note_period({"date_from": "2026-08-01", "date_to": "2026-08-19"})
    assert start == date(2026, 8, 1)
    assert end == date(2026, 8, 19)


def test_query_is_select_only() -> None:
    query, theme_fields, person_fields = build_meeting_notes_query(
        document_name="ТД_СлужебнаяЗаписка",
        requisites=["ТемаСлужебнойЗаписки", "Кому", "Комментарий"],
        date_from=date(2026, 8, 19),
        date_to=date(2026, 8, 19),
        fio="Ильченко Екатерина Александровна",
        limit=20,
    )
    assert_select_only(query)
    folded = query.casefold()
    assert folded.startswith("выбрать")
    assert "записать" not in folded
    assert "удалить" not in folded
    assert "провести" not in folded
    assert "организация совещаний" in folded
    assert "ильченко" in folded
    assert "темаслужебнойзаписки" in theme_fields[0].casefold()
    assert "Кому" in person_fields


def test_person_needles_use_last_name() -> None:
    needles = person_needles("Ильченко Екатерина Александровна")
    assert "Ильченко" in needles


def test_pick_preferred_document() -> None:
    chosen = pick_document_name(
        [
            {"name": "Прочее", "synonym": "Прочее"},
            {"name": "ТД_СлужебнаяЗаписка", "synonym": "Служебная записка"},
        ]
    )
    assert chosen is not None
    assert chosen["name"] == "ТД_СлужебнаяЗаписка"


def test_tool_is_readonly_and_registered() -> None:
    assert "onec.meeting_service_notes" in ALLOWED_ONEC_TOOLS
    assert "onec.meeting_service_notes" in ONEC_COM32_TOOLS
    assert not needs_confirmation("onec.meeting_service_notes")
    stub = type("W", (), {"execute": lambda *_a, **_k: None})()
    tool = OneCMeetingServiceNotesTool(stub)
    assert tool.definition.requires_human_approval is False
    assert "не записывает" in (tool.definition.description or "").casefold()
    assert tool.definition.runtime == ONEC_COM32_RUNTIME


def test_latin_query_has_ascii_aliases() -> None:
    query, columns = build_meeting_notes_query_latin(
        document_name="ТД_СлужебнаяЗаписка",
        date_from=date(2026, 8, 19),
        date_to=date(2026, 8, 19),
        fio="Ильченко Екатерина Александровна",
        limit=20,
    )
    assert columns[0:3] == ["Number", "DocDate", "Theme"]
    assert "MeetingTopic" in columns
    assert "Place" in columns
    assert "Addressee" in columns
    assert "КАК Number" in query
    assert "ТемаСлужебнойЗаписки.Наименование" in query
    assert "ПРЕДСТАВЛЕНИЕ(Д.ТемаСовещания) КАК MeetingTopic" in query
    assert "ПРЕДСТАВЛЕНИЕ(Д.МестоПроведенияСовещания)" in query
    assert "МенеджерКому.Наименование" in query
    assert_select_only(query)
    presented, _ = build_meeting_notes_query_latin(
        document_name="ТД_СлужебнаяЗаписка",
        date_from=date(2026, 8, 19),
        date_to=date(2026, 8, 19),
        fio="Ильченко Екатерина Александровна",
        limit=20,
        presentation=True,
        deref=False,
    )
    assert "ПРЕДСТАВЛЕНИЕ(Д.МенеджерКому)" in presented
    assert "ПРЕДСТАВЛЕНИЕ(Д.МестоПроведенияСовещания)" in presented
    assert_select_only(presented)


def test_meeting_params_map_form_fields() -> None:
    params = meeting_params_from_row(
        {
            "MeetingTopic": "Подготовка к запуску проекта",
            "Place": "Переговорная 3",
            "DesiredDate": "2026-08-20T00:00:00",
            "StartTime": "0001-01-01T10:00:00",
            "EndTime": "0001-01-01T11:30:00",
            "Leader": "Иванов Иван",
            "Priority": "Высокий",
            "MeetingKind": "Очное",
            "PsdLevel": "true",
            "Schedule": "<Не задана>",
            "Purpose": "",
        }
    )
    assert params["topic"] == "Подготовка к запуску проекта"
    assert params["place"] == "Переговорная 3"
    assert params["desired_date"] == "20.08.2026"
    assert params["start_time"] == "10:00"
    assert params["end_time"] == "11:30"
    assert params["duration_minutes"] == 90
    assert params["leader"] == "Иванов Иван"
    assert params["psd_level"] is True
    assert params["periodicity"] == ""
    presented = meeting_params_from_row(
        {
            "DesiredDate": "20.08.2026",
            "StartTime": "15:00:00",
            "EndTime": "15:30:00",
            "MeetingKind": "Внеплановое",
        }
    )
    assert presented["desired_date"] == "20.08.2026"
    assert presented["start_time"] == "15:00"
    assert presented["end_time"] == "15:30"
    assert presented["duration_minutes"] == 30
    assert presented["meeting_type"] == "Внеплановое"


def test_connection_string_quotes_fio_with_spaces(monkeypatch) -> None:
    monkeypatch.setenv("ONEC_COM_SERVER", "srv1")
    monkeypatch.setenv("ONEC_COM_REF", "erp_pm")
    monkeypatch.setenv("ERP_LOGIN", "Ильченко Екатерина Александровна")
    monkeypatch.setenv("ERP_PASSWORD", "secret")
    monkeypatch.delenv("ONEC_COM_CONNECTION_STRING", raising=False)
    conn = connection_string()
    assert 'Usr="Ильченко Екатерина Александровна"' in conn
    assert "Pwd=secret" in conn


def test_document_search_query_is_select_only() -> None:
    query, columns = build_document_search_query_latin(
        document_name="ТД_СлужебнаяЗаписка",
        query="000013243",
        limit=10,
        exact_number=True,
        include_meeting_fields=True,
    )
    assert_select_only(query)
    assert columns[0:3] == ["Number", "DocDate", "Theme"]
    assert "MeetingTopic" in columns
    assert "Place" in columns
    assert 'Д.Номер = "000013243"' in query
    assert "ТемаСлужебнойЗаписки.Наименование" in query
    like_query, _ = build_document_search_query_latin(
        document_name="ТД_СлужебнаяЗаписка",
        query="организация совещаний",
        limit=10,
        exact_number=False,
        include_meeting_fields=False,
    )
    assert_select_only(like_query)
    assert "ПОДОБНО" in like_query
    assert "ТемаСовещания" not in like_query
    incoming, incoming_columns = build_incoming_search_query_latin(
        query="000013243",
        limit=5,
        exact_number=True,
    )
    assert_select_only(incoming)
    assert incoming_columns == ["Number", "DocDate", "Theme"]
    assert "ТД_ВходящаяКорреспонденция" in incoming


def test_document_row_maps_meeting_fields() -> None:
    doc = document_from_com32_row(
        {
            "Number": "000013243",
            "DocDate": "19.08.2026 0:00:00",
            "Theme": "организация совещаний",
            "MeetingTopic": "Рабочая группа по форме 03-19 №182",
            "Place": "Переговорная",
            "DesiredDate": "20.08.2026",
            "StartTime": "15:00:00",
            "EndTime": "15:30:00",
            "Priority": "Высокий",
        },
        document_name="ТД_СлужебнаяЗаписка",
    )
    assert doc["found"] is True
    assert doc["number"] == "000013243"
    assert doc["meeting_topic"] == "Рабочая группа по форме 03-19 №182"
    assert doc["meeting"]["start_time"] == "15:00"
    assert doc["meeting"]["priority"] == "Высокий"


def test_com32_dispatch_search_and_card(monkeypatch) -> None:
    from app.tools.ac.workers.models import WorkerTask
    from app.tools.ac.workers.onec_com_actions import _dispatch_via_com32

    def fake_select(attempts, timeout=150):
        _ = attempts, timeout
        return (
            [
                {
                    "Number": "000013243",
                    "DocDate": "19.08.2026",
                    "Theme": "организация совещаний",
                    "MeetingTopic": "Рабочая группа по форме 03-19 №182",
                    "Place": "Переговорная",
                    "DesiredDate": "20.08.2026",
                    "StartTime": "15:00:00",
                    "EndTime": "15:30:00",
                    "Priority": "Высокий",
                }
            ],
            0,
        )

    monkeypatch.setattr(
        "app.tools.ac.workers.onec_com32_helper.run_select_first",
        fake_select,
    )
    search = _dispatch_via_com32(
        WorkerTask(task_id="t1", tool_name="onec.search_documents", input_data={"query": "000013243"})
    )
    assert search["source"] == "onec_com32"
    assert search["count"] == 1
    assert search["documents"][0]["number"] == "000013243"
    assert search["documents"][0]["meeting"]["priority"] == "Высокий"
    card = _dispatch_via_com32(
        WorkerTask(task_id="t2", tool_name="onec.get_document_card", input_data={"number": "000013243"})
    )
    assert card["document"]["number"] == "000013243"
    assert card["document"]["meeting_topic"].startswith("Рабочая группа")


def test_mock_action_does_not_invent_writes() -> None:
    result = list_meeting_service_notes({"date": "2026-08-19"})
    assert result["readonly"] is True
    assert result["notes"] == []
    assert result["theme"] == "организация совещаний"
