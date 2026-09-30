"""Board protocol pair (current + previous СД ГК) and the task completeness check."""

from __future__ import annotations

from datetime import date

from app.services import meeting_protocols
from app.services.meeting_protocols import (
    SD_BOARD_TOPIC,
    _pick_pair,
    build_protocol_filter,
    build_protocol_list_path,
    check_protocol_tasks,
)

CURRENT_KEY = "037475af-adcd-11f1-987e-6cb31113810c"
PREVIOUS_KEY = "4a6f9cda-a892-11ef-95b7-6cb31113810e"
PROCESS_ID = "38f8111b-bcb2-11e8-8282-ac1f6b05524d"


def _protocol(number: str, day: str, *, draft: bool, ref_key: str = "") -> dict:
    return {
        "ref_key": ref_key or number,
        "number": number,
        "date": f"{day}T10:00:00",
        "posted": not draft,
        "status": "Подготовлен" if draft else "НаИсполнении",
        "needs_review": draft,
    }


def test_topic_filter_is_added_and_kept_in_path() -> None:
    filt = build_protocol_filter(
        {"meeting_kind": "sd", "topic": SD_BOARD_TOPIC, "review_only": False, "include_closed": True},
        kind="sd",
    )
    assert "ТемаСовещания/Description eq 'Совет директоров по ГК'" in filt
    assert "Posted eq false" not in filt
    assert "Закрыт" not in filt
    path = build_protocol_list_path(odata_filter=filt, limit=5)
    assert "ТемаСовещания/Description" in path


def test_pick_pair_without_date_takes_newest_draft_and_the_one_before() -> None:
    rows = [
        _protocol("ПСД_001_О_201", "2026-08-27", draft=False),
        _protocol("ПСД_001_О_226", "2026-09-30", draft=True),
        _protocol("ПСД_001_О_159", "2026-07-31", draft=False),
    ]
    current, previous = _pick_pair(rows, anchor=date(2026, 9, 30), explicit_day=False)
    assert current["number"] == "ПСД_001_О_226"
    assert previous["number"] == "ПСД_001_О_201"


def test_pick_pair_with_date_and_no_protocol_that_day() -> None:
    rows = [_protocol("ПСД_001_О_201", "2026-08-27", draft=False)]
    current, previous = _pick_pair(rows, anchor=date(2026, 10, 27), explicit_day=True)
    assert current is None
    assert previous["number"] == "ПСД_001_О_201"


def test_check_protocol_tasks_findings() -> None:
    form = {
        "tasks": [
            {"item": "1", "text": "Отчёт ОПУ", "executor": "Иванов И.И.", "due": "2026-09-01",
             "sent": True, "has_file": True, "note": "Выполнено"},
            {"item": "2", "text": "Отчёт ДДС", "executor": "", "due": "", "sent": False, "has_file": False},
            {"item": "3", "text": "Реестр рисков", "executor": "Петров П.П.", "due": "2026-09-01",
             "process_started": True, "has_file": True},
        ]
    }
    check = check_protocol_tasks(form, posted=True, today=date(2026, 9, 30))
    by_item = {task["item"]: task for task in check["tasks"]}
    assert by_item["1"]["complete"] is True
    assert set(by_item["2"]["findings"]) == {
        "не указан исполнитель",
        "не указан срок",
        "не отправлена исполнителю в 1С",
        "нет вложенного файла",
    }
    assert by_item["3"]["findings"] == ["срок 2026-09-01 прошёл, нет отметки об исполнении"]
    assert check["tasks_incomplete"] == 2
    assert check["complete"] is False


def test_check_protocol_tasks_empty_is_a_gap() -> None:
    check = check_protocol_tasks({"tasks": []}, posted=True, today=date(2026, 9, 30))
    assert check["complete"] is False
    assert check["gaps"] == ["в «Поставленных задачах» протокола нет ни одной задачи"]


def test_draft_tasks_are_not_required_to_be_sent() -> None:
    form = {"tasks": [{"text": "Отчёт", "executor": "Иванов И.И.", "due": "2026-10-20", "has_file": True}]}
    check = check_protocol_tasks(form, posted=False, today=date(2026, 9, 30))
    assert check["complete"] is True


def test_board_protocol_pair_marks_not_carried_tasks(monkeypatch) -> None:
    listed = [
        _protocol("ПСД_001_О_226", "2026-09-30", draft=True, ref_key=CURRENT_KEY),
        _protocol("ПСД_001_О_201", "2026-08-27", draft=False, ref_key=PREVIOUS_KEY),
    ]
    seen_args: list[dict] = []

    def fake_list(args, *, access=None):
        seen_args.append(args)
        return {"protocols": listed, "count": len(listed)}

    forms = {
        CURRENT_KEY: {"tasks": [{"text": "Отчёт ОПУ", "executor": "Иванов И.И.", "due": "2026-10-20",
                                 "has_file": True}]},
        PREVIOUS_KEY: {
            "next_meeting_date": "2026-09-30",
            "tasks": [
                {"text": "Отчёт ОПУ", "executor": "Иванов И.И.", "due": "2026-09-20", "sent": True,
                 "has_file": True, "note": ""},
                {"text": "Реестр рисков", "executor": "Петров П.П.", "due": "2026-09-20", "sent": True,
                 "has_file": True, "note": ""},
                {"text": "Бюджет", "executor": "Сидоров С.С.", "due": "2026-09-20", "sent": True,
                 "has_file": True, "note": "Выполнено"},
            ],
        },
    }
    monkeypatch.setattr(meeting_protocols, "list_meeting_protocols", fake_list)
    monkeypatch.setattr(
        "app.services.meeting_protocol_write.read_protocol_card", lambda ref: {"Ref_Key": ref}
    )
    monkeypatch.setattr(
        "app.services.meeting_protocol_write.read_protocol_form",
        lambda ref, card=None: {"form": forms[ref]},
    )

    result = meeting_protocols.board_protocol_pair({"meeting_kind": "sd", "pair": True})

    assert seen_args[0]["topic"] == SD_BOARD_TOPIC
    assert seen_args[0]["review_only"] is False
    assert result["current"]["number"] == "ПСД_001_О_226"
    assert result["previous"]["number"] == "ПСД_001_О_201"
    previous = {task["text"]: task for task in result["previous"]["check"]["tasks"]}
    assert "не перенесена в протокол ПСД_001_О_226 на контроль" in previous["Реестр рисков"]["findings"]
    assert all("не перенесена" not in item for item in previous["Бюджет"]["findings"])
    assert all("не перенесена" not in item for item in previous["Отчёт ОПУ"]["findings"])
    assert result["gaps"] == []


def test_board_protocol_pair_reports_missing_protocols(monkeypatch) -> None:
    monkeypatch.setattr(
        meeting_protocols,
        "list_meeting_protocols",
        lambda args, *, access=None: {"protocols": [], "count": 0},
    )
    result = meeting_protocols.board_protocol_pair({"pair": True, "date": "2026-10-27"})
    assert result["current"] is None and result["previous"] is None
    assert any("текущего заседания" in gap and "2026-10-27" in gap for gap in result["gaps"])
    assert any("прошлого заседания" in gap for gap in result["gaps"])


def test_list_meeting_protocols_routes_pair(monkeypatch) -> None:
    monkeypatch.setattr(
        meeting_protocols, "board_protocol_pair", lambda args, *, access=None: {"pair": True, "args": args}
    )
    result = meeting_protocols.list_meeting_protocols({"meeting_kind": "sd", "pair": "true"})
    assert result["pair"] is True


def test_read_protocol_form_task_flags(monkeypatch) -> None:
    from app.services import meeting_protocol_write

    monkeypatch.setattr(meeting_protocol_write, "_prefetch_descriptions", lambda card, cache: None)
    monkeypatch.setattr(meeting_protocol_write, "_description_of", lambda entity, key, cache: "")
    card = {
        "Ref_Key": PREVIOUS_KEY,
        "Number": "ПСД_001_О_201",
        "Posted": True,
        "ПеременныеЗадачиПротокола": [
            {"LineNumber": "1", "Задача": "Отчёт ОПУ", "Отправлена": True, "ПроцессID": PROCESS_ID,
             "ДатаФактическогоИсполнения": "2026-09-20T23:59:59"},
        ],
        "ПостоянныеЗадачиПротокола": [
            {"LineNumber": "1", "Задача": "Отчёт ОПУ", "Ответственный": "Иванов И.И.",
             "Файл_Base64Data": "UEsDBAo="},
        ],
    }
    form = meeting_protocol_write.read_protocol_form(PREVIOUS_KEY, card=card)["form"]
    assert len(form["tasks"]) == 1
    task = form["tasks"][0]
    assert task["sent"] is True
    assert task["process_started"] is True
    assert task["has_file"] is True
    assert task["due"] == "2026-09-20"
