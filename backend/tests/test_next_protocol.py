"""action=next: protocol of the next meeting built from the previous one."""

from __future__ import annotations

import pytest

from app.services import meeting_protocol_write as mpw

SOURCE = "11111111-2222-3333-4444-555555555555"

PREVIOUS = {
    "ref_key": SOURCE,
    "number": "ПСД_001_О_012",
    "form": {
        "topic": "Совет директоров по ГК",
        "theme_key": "b2e6e94a-6885-11f1-9822-6cb31113810e",
        "date": "2026-09-10",
        "time_start": "10:00",
        "time_end": "12:00",
        "room": "Переговорная 1",
        "room_key": "",
        "next_meeting_date": "2026-10-08",
        "leader": "Петров Пётр Петрович",
        "responsible": "Сидорова Анна Ивановна",
        "meeting_type": "Отчетное",
        "access": "Общий",
        "department": "",
        "project": "",
        "participants": ["Петров Пётр Петрович", "Иванов Иван Иванович"],
        "agenda": [{"question": "Бюджет на 2027 год", "responsible": "Иванов Иван Иванович"}],
        "decisions": [{"text": "Утвердить бюджет", "due": "2026-09-30"}],
        "tasks": [
            {
                "text": "Подготовить ОПУ за квартал",
                "executor": "Иванов Иван Иванович",
                "due": "2026-10-01",
                "priority": "Высокий",
                "note": "",
                "item": "1",
            },
            {"text": "", "executor": "Пустая строка"},
        ],
        "comment": "",
    },
}


def test_copies_header_participants_agenda_and_leaves_tasks_to_the_register() -> None:
    args = mpw.next_protocol_args(PREVIOUS, {"action": "next", "source_ref_key": SOURCE})

    assert args["date"] == "2026-10-08"
    assert args["topic"] == "Совет директоров по ГК"
    assert args["leader"] == "Петров Пётр Петрович"
    assert args["responsible"] == "Сидорова Анна Ивановна"
    assert args["participants"] == ["Петров Пётр Петрович", "Иванов Иван Иванович"]
    # Открытые задачи темы форма 1С берёт из регистра; копия стала бы второй задачей на контроле.
    assert "tasks" not in args
    assert args["agenda"][-1] == {
        "question": "Контроль исполнения поручений протокола ПСД_001_О_012",
        "responsible": "Сидорова Анна Ивановна",
    }
    assert "decisions" not in args
    assert args["report_period_from"] == "2026-09-10"
    assert args["report_period_to"] == "2026-10-08"
    assert args["comment"] == "Подготовлен на основе протокола ПСД_001_О_012 от 2026-09-10"
    assert "source_ref_key" not in args and "action" not in args


def test_explicit_arguments_override_the_copy() -> None:
    args = mpw.next_protocol_args(
        PREVIOUS,
        {"date": "2026-10-15", "time_start": "14:00", "comment": "Перенос по просьбе председателя"},
    )

    assert args["date"] == "2026-10-15"
    assert args["time_start"] == "14:00"
    assert args["report_period_to"] == "2026-10-15"
    assert args["comment"] == (
        "Подготовлен на основе протокола ПСД_001_О_012 от 2026-09-10\nПеренос по просьбе председателя"
    )


def test_needs_a_date_when_previous_has_no_next_meeting() -> None:
    previous = {**PREVIOUS, "form": {**PREVIOUS["form"], "next_meeting_date": ""}}
    with pytest.raises(mpw.ProtocolWriteError, match="дата следующего совещания"):
        mpw.next_protocol_args(previous, {})


def test_next_action_reads_source_and_creates_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    real_handle = mpw.handle_protocol_write

    def fake_handle(args: dict, **kwargs: object) -> dict:
        if args.get("action") != "create":
            return real_handle(args, **kwargs)
        seen["args"] = args
        return {"summary": "Создан протокол ПСД_001_О_013 в 1С", "number": "ПСД_001_О_013", "ref_key": "x"}

    monkeypatch.setattr(mpw, "read_protocol_form", lambda ref: {**PREVIOUS, "ref_key": ref})
    monkeypatch.setattr(mpw, "handle_protocol_write", fake_handle)

    result = fake_handle({"action": "next", "source_ref_key": SOURCE})

    assert seen["args"]["date"] == "2026-10-08"
    assert result["source_number"] == "ПСД_001_О_012"
    assert "tasks" not in seen["args"]
    assert result["control_tasks"] == 1
    assert "на основе ПСД_001_О_012" in result["summary"]


def test_next_action_requires_source_guid() -> None:
    with pytest.raises(mpw.ProtocolWriteError, match="source_ref_key"):
        mpw.handle_protocol_write({"action": "next", "source_ref_key": "ПСД_001_О_012"})
