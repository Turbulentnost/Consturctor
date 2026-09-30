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
    assert check["gaps"] == ["в протоколе нет ни поручений («Решения»), ни «Поставленных задач»"]


def test_each_board_decision_is_checked_separately() -> None:
    form = {
        "decisions": [
            {"item": "1", "text": "Автоматизация до 30.04.26", "due_in_text": "2026-04-30"},
            {"item": "2", "text": "Отчёт Авион", "due": "2026-10-20", "has_artifact": True,
             "result": "Сделано", "done_date": "2026-09-25", "sent": True},
            {"item": "3", "text": "Старый проект", "canceled": True, "cancel_reason": "неактуально"},
            {"item": "4", "text": "Без срока", "sent": True},
        ]
    }
    check = check_protocol_tasks(form, posted=True, today=date(2026, 9, 30))
    by_item = {item["item"]: item for item in check["decisions"]}
    assert set(by_item["1"]["findings"]) == {
        "нет артефакта (отметка «Наличие артефакта» не стоит)",
        "нет результата и даты исполнения",
        "срок 2026-04-30 прошёл, поручение не исполнено",
    }
    assert by_item["1"]["due_source"] == "текст поручения"
    assert by_item["2"]["complete"] is True and by_item["2"]["status"] == "исполнено"
    assert by_item["3"]["status"] == "отменено" and by_item["3"]["findings"] == []
    assert "не указан срок" in by_item["4"]["findings"]
    assert check["gaps"] == []
    assert check["decisions_incomplete"] == 2


def test_pair_reconciliation_has_a_row_per_item(monkeypatch) -> None:
    decision = {"item": "1", "text": "Перенести проект  до 30.09.26", "due_in_text": "2026-09-30"}
    forms = {
        CURRENT_KEY: {
            "decisions": [{**decision, "text": "Перенести проект до 30.09.26"}],
            "agenda": [{"item": "1", "question": "Доклад ГБ", "responsible": "", "has_file": False}],
        },
        PREVIOUS_KEY: {
            "decisions": [decision, {"item": "2", "text": "Отчёт Авион", "due": "2026-09-01"}],
        },
    }
    listed = [
        _protocol("ПСД_001_О_226", "2026-09-30", draft=True, ref_key=CURRENT_KEY),
        _protocol("ПСД_001_О_201", "2026-08-27", draft=False, ref_key=PREVIOUS_KEY),
    ]
    monkeypatch.setattr(
        meeting_protocols, "list_meeting_protocols",
        lambda args, *, access=None: {"protocols": listed, "count": 2},
    )
    monkeypatch.setattr("app.services.meeting_protocol_write.read_protocol_card", lambda ref: {"Ref_Key": ref})
    monkeypatch.setattr(
        "app.services.meeting_protocol_write.read_protocol_form", lambda ref, card=None: {"form": forms[ref]}
    )
    files = {
        PREVIOUS_KEY: [
            {"file_id": "f1", "name": "08_2026_БДР ООО Милака_Январь-Август.xlsx", "created": "2026-09-25"},
            {"file_id": "f2", "name": "doc02715420260929090414.pdf", "created": "2026-09-29"},
        ],
        CURRENT_KEY: [],
    }
    monkeypatch.setattr(meeting_protocols, "protocol_attached_files", lambda ref: files[ref])

    result = meeting_protocols.board_protocol_pair({"pair": True, "date": "2026-09-30"})

    rows = result["reconciliation"]
    assert [(row["protocol"], row["section"], row["item"]) for row in rows] == [
        ("прошлый ПСД_001_О_201", "поручение", "1"),
        ("прошлый ПСД_001_О_201", "поручение", "2"),
        ("текущий ПСД_001_О_226", "поручение", "1"),
        ("текущий ПСД_001_О_226", "вопрос повестки", "1"),
    ]
    assert "перенесено в текущий протокол" in rows[0]["ok"]
    assert "протокол проведён, статус «НаИсполнении»" in rows[0]["ok"]
    assert "не исполнено и не перенесено в протокол ПСД_001_О_226" in rows[1]["errors"]
    assert any("к протоколу приложено файлов: 2" in error for error in rows[0]["errors"])
    assert all("не отправлено" not in error for row in rows for error in row["errors"])
    assert "нет артефакта (отметка «Наличие артефакта» не стоит)" in rows[2]["errors"]
    assert rows[3]["errors"] == ["не указан ответственный", "нет приложенного материала"]
    package = {item["item"]: item["files"] for item in result["previous"]["package"]["items"]}
    assert package["опу"] == ["08_2026_БДР ООО Милака_Январь-Август.xlsx"]
    assert package["ддс"] == []
    assert [f["file_id"] for f in result["previous"]["package"]["unrecognized"]] == ["f2"]
    assert result["gaps"] == []
    assert "сверено строк: 4" in result["summary"]
    assert "файлов у ПСД_001_О_201: 2" in result["summary"]


def test_package_table_lists_responsible_and_documents_in_order() -> None:
    previous = {
        "number": "ПСД_001_О_201",
        "files": [
            {"file_id": "b", "name": "2026_БДР_Алмаз_Январь-Август.xlsx", "created": "2026-09-25 16:54",
             "uploaded_by": "Петрова А.А."},
            {"file_id": "a", "name": "08_2026_БДР ООО Милака_Январь-Август.xlsx", "created": "2026-09-25 08:54",
             "uploaded_by": "Лазарева М.В."},
            {"file_id": "c", "name": "doc02715420260929090414.pdf", "created": "2026-09-29 11:59",
             "uploaded_by": "Лазарева М.В."},
        ],
    }
    agenda = [{"question": "Презентация «Анализ по Коммерческой службе»", "responsible": "Торотадзе Д.Ш."}]

    rows = meeting_protocols.package_table([(None, "текущий"), (previous, "прошлый")], agenda)

    by_item = {row["item"]: row for row in rows}
    opu = by_item["Финансы план/факт: ОПУ"]
    assert opu["n"] == 2 and opu["status"] == "есть"
    assert opu["responsible"] == "Лазарева М.В., Петрова А.А."
    assert [doc.split(" (")[0] for doc in opu["documents"]] == [
        "08_2026_БДР ООО Милака_Январь-Август.xlsx",
        "2026_БДР_Алмаз_Январь-Август.xlsx",
    ]
    assert "2026-09-25 08:54, Лазарева М.В., ПСД_001_О_201" in opu["documents"][0]
    sales = by_item["Продажи и клиенты"]
    assert sales["status"] == "нет" and sales["responsible"] == "Торотадзе Д.Ш."
    assert sales["responsible_source"] == "ответственный по вопросу повестки"
    assert by_item["Финансы: ДДС"]["responsible"] == ""
    unread = rows[-1]
    assert unread["status"] == "прочитать" and unread["documents"][0].startswith("doc02715420260929090414.pdf")
    assert [row["n"] for row in rows] == list(range(1, len(rows) + 1))


def test_package_hints_match_whole_short_words() -> None:
    package = meeting_protocols.package_by_files(
        [
            {"file_id": "a", "name": "2026 ПЛАН-ФАКТ МГС-август.xls", "created": ""},
            {"file_id": "b", "name": "Реестр ДЗ на 01.09.xlsx", "created": ""},
            {"file_id": "c", "name": "Отчёт ДДС август.xlsx", "created": ""},
            {"file_id": "d", "name": "Дзержинский филиал.pdf", "created": ""},
        ]
    )
    by_item = {item["item"]: item["files"] for item in package["items"]}
    assert by_item["опу"] == ["2026 ПЛАН-ФАКТ МГС-август.xls"]
    assert by_item["дз"] == ["Реестр ДЗ на 01.09.xlsx"]
    assert by_item["ддс"] == ["Отчёт ДДС август.xlsx"]
    assert [f["file_id"] for f in package["unrecognized"]] == ["d"]


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
    monkeypatch.setattr(meeting_protocols, "protocol_attached_files", lambda ref: [])
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


def test_read_protocol_form_decision_fields(monkeypatch) -> None:
    from app.services import meeting_protocol_write

    monkeypatch.setattr(meeting_protocol_write, "_prefetch_descriptions", lambda card, cache: None)
    monkeypatch.setattr(meeting_protocol_write, "_description_of", lambda entity, key, cache: "")
    card = {
        "Ref_Key": CURRENT_KEY,
        "Решения": [
            {"LineNumber": "4", "ТекстРешения": "Перенести проект до следующего СД до 30.09.26\n",
             "ДатаНачала": "2026-08-27T00:00:00", "ДатаОкончания": "0001-01-01T00:00:00",
             "ДатаИсполнения": "0001-01-01T00:00:00", "РезультатРешения": "", "Отправлено": False,
             "НаличиеАртефакта": True, "Отменено": False},
        ],
        "ПовесткаСовещания": [
            {"LineNumber": "1", "Вопрос": "Доклад", "Файл_Base64Data": "", "ОтметкаОНаличииПриложений": "Да"},
        ],
    }
    form = meeting_protocol_write.read_protocol_form(CURRENT_KEY, card=card)["form"]
    decision = form["decisions"][0]
    assert decision["item"] == "4"
    assert decision["due"] == "" and decision["due_in_text"] == "2026-09-30"
    assert decision["since"] == "2026-08-27"
    assert decision["has_artifact"] is True
    assert form["agenda"][0]["has_file"] is True
