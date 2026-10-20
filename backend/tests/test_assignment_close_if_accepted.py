"""Auto-close of an AST00 assignment once the author accepted every Docflow task."""

from __future__ import annotations

import pytest

from app.services import erp_assignments as ea

REF = "11111111-2222-3333-4444-555555555555"
AUTHOR = "Ильченко Елена Александровна"
ACCEPTED = "принято проверяющим"


def _task(performer: str = "Тен Л.Л.", label: str = ACCEPTED, checker: str = "Ильченко Е.А.", history=None) -> dict:
    return {
        "performer": performer,
        "author": AUTHOR,
        "label": label,
        "accepted_by": checker if label == ACCEPTED else "",
        "history": history
        or [
            {"task_id": "e1", "step": "Исполнить", "performer": performer, "executed": True},
            {"task_id": "c1", "step": "Проверить исполнение", "performer": checker, "executed": True},
        ],
    }


def _card(status: str, tasks: list[dict], *, note: str = "", other: list[dict] | None = None) -> dict:
    item = {
        "number": "АСТ00-00112",
        "ref_key": REF,
        "status": status,
        "open": ea._status_open(status),
        "lines": [{"line": 1, "text": "Мероприятие", "executor": "Тен Л.Л."}],
        "docflow_tasks": tasks,
        "docflow_other_tasks": other or [],
    }
    card = {"assignment": item}
    if note:
        card["docflow_note"] = note
    return card


def _fake(monkeypatch, cards: list[dict]) -> list[dict]:
    calls: list[dict] = []
    seen: list[dict] = []

    def get(args):
        seen.append(args)
        return cards[min(len(seen) - 1, len(cards) - 1)]

    monkeypatch.setattr(ea, "_get_assignment", get)
    monkeypatch.setattr(ea, "_odata_patch", lambda args: calls.append(args) or {"updated": True})
    return calls


def test_closes_when_author_accepted_every_task(monkeypatch):
    tasks = [_task(), _task("Солдатенко О.Н.")]
    calls = _fake(monkeypatch, [_card("Создано", tasks), _card("Принято", tasks)])

    result = ea.handle_assignments_write(
        {"action": "close_if_accepted", "number": "АСТ00-00112", "session_login": "Иванов", "password": "x"}
    )

    assert result["closed"] is True
    assert calls == [{"entity": ea.ASSIGNMENT_ENTITY, "ref_key": REF, "body": {"Статус": "Принято"}}]


def test_keeps_open_when_a_task_waits(monkeypatch):
    calls = _fake(monkeypatch, [_card("ВРаботе", [_task(), _task("Солдатенко О.Н.", "исполнитель отчитался, ждёт проверки")])])

    result = ea.close_if_accepted({"number": "АСТ00-00112"})

    assert result["closed"] is False
    assert result["pending"] == ["задача у Солдатенко О.Н.: исполнитель отчитался, ждёт проверки"]
    assert calls == []


def test_keeps_open_when_someone_else_accepted(monkeypatch):
    calls = _fake(monkeypatch, [_card("Создано", [_task(checker="Петров П.П.")])])

    result = ea.close_if_accepted({"number": "АСТ00-00112"})

    assert result["closed"] is False
    assert result["pending"] == [f"задача у Тен Л.Л.: принял Петров П.П., а не автор {AUTHOR}"]
    assert calls == []


def test_keeps_open_while_another_task_is_open(monkeypatch):
    other = [{"name": "Ознакомиться", "step": "Ознакомиться", "performer": "Тищенко М.Н.", "executed": False}]
    calls = _fake(monkeypatch, [_card("Создано", [_task()], other=other)])

    result = ea.close_if_accepted({"number": "АСТ00-00112"})

    assert result["pending"] == ["открыта задача «Ознакомиться» у Тищенко М.Н."]
    assert calls == []


def test_no_tasks_is_not_closed(monkeypatch):
    calls = _fake(monkeypatch, [_card("Создано", [])])

    result = ea.close_if_accepted({"number": "АСТ00-00112"})

    assert result["closed"] is False
    assert "нет задач" in result["summary"]
    assert calls == []


def test_no_write_without_full_docflow_view(monkeypatch):
    calls = _fake(monkeypatch, [_card("Создано", [_task()], note="ДО недоступен")])

    assert ea.close_if_accepted({"number": "АСТ00-00112"})["closed"] is False
    assert calls == []


def test_already_closed_is_not_patched(monkeypatch):
    calls = _fake(monkeypatch, [_card("Принято", [_task()])])

    result = ea.close_if_accepted({"ref_key": REF})

    assert result["closed"] is True and result["already"] is True
    assert calls == []


@pytest.mark.parametrize("after", ["Создано", ""])
def test_reports_when_status_did_not_change(monkeypatch, after):
    _fake(monkeypatch, [_card("Создано", [_task()]), _card(after, [_task()])])

    assert ea.close_if_accepted({"number": "АСТ00-00112"})["closed"] is False
