from types import SimpleNamespace

import pytest

from app.services import docflow_task_action as mod
from app.services.docflow_tasks import DocflowError

EXEC_ID = "11111111-1111-1111-1111-111111111111"
CHECK_ID = "22222222-2222-2222-2222-222222222222"
OTHER_CHECK = "33333333-3333-3333-3333-333333333333"
TARGET = "44444444-4444-4444-4444-444444444444"


def _setup(monkeypatch, *, open_rows, executed=False):
    pressed: list[tuple[str, int, str]] = []
    monkeypatch.setattr(mod, "load_config", lambda **_: SimpleNamespace(timeout=5))
    monkeypatch.setattr(
        mod,
        "retrieve_tasks",
        lambda *_a, **_k: [
            {
                "id": EXEC_ID,
                "name": "Исполнить задачу №2",
                "step": "Исполнить",
                "executed": executed,
                "target_id": TARGET,
                "target_type": "DMInternalDocument",
            }
        ],
    )
    monkeypatch.setattr(mod, "open_tasks_for_target", lambda *_a, **_k: open_rows)
    monkeypatch.setattr(mod, "drop_task_from_inbox_cache", lambda *_: None)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)

    def fake_mark(_config, task_id, *, timeout, comment="", mark="ExecutedPositive"):
        pressed.append((task_id, mark, comment))
        return {"id": task_id, "executed": True}

    monkeypatch.setattr(mod, "mark_task_executed", fake_mark)
    monkeypatch.setattr(
        mod, "post_task_action", lambda *_a, **_k: pytest.fail("TaskAction не опубликован в ДО")
    )
    return pressed


def test_closes_execute_then_accepts_matching_check(monkeypatch):
    pressed = _setup(
        monkeypatch,
        open_rows=[
            {"id": OTHER_CHECK, "name": "Проверить: ПОРУЧЕНИЕ. Задача №1", "step": "Проверить исполнение"},
            {"id": CHECK_ID, "name": "Проверить: ПОРУЧЕНИЕ. Задача №2", "step": "Проверить исполнение"},
        ],
    )
    out = mod.handle_docflow_task_action(
        {"action": "close_without_report", "task_id": EXEC_ID, "fio": "Ильченко", "password": "x", "comment": "сделано устно"}
    )
    assert [task for task, _b, _c in pressed] == [EXEC_ID, CHECK_ID]
    assert all("без отчёта исполнителя: сделано устно" in comment for *_x, comment in pressed)
    assert out["line_closed"] is True
    assert out["check_task_id"] == CHECK_ID


def test_already_executed_only_accepts_check(monkeypatch):
    pressed = _setup(
        monkeypatch,
        executed=True,
        open_rows=[{"id": CHECK_ID, "name": "Проверить: ПОРУЧЕНИЕ. Задача №2", "step": "Проверить исполнение"}],
    )
    out = mod.handle_docflow_task_action({"action": "close_without_report", "task_id": EXEC_ID, "fio": "И", "password": "x"})
    assert [task for task, *_ in pressed] == [CHECK_ID]
    assert out["line_closed"] is True


def test_no_check_yet_reports_partial(monkeypatch):
    pressed = _setup(monkeypatch, open_rows=[])
    out = mod.handle_docflow_task_action({"action": "close_without_report", "task_id": EXEC_ID, "fio": "И", "password": "x"})
    assert [task for task, *_ in pressed] == [EXEC_ID]
    assert out["closed"] is True and out["line_closed"] is False


def test_unnumbered_task_accepts_check_that_appeared_after_close(monkeypatch):
    pressed = _setup(monkeypatch, open_rows=[])
    monkeypatch.setattr(
        mod,
        "retrieve_tasks",
        lambda *_a, **_k: [
            {"id": EXEC_ID, "name": 'Исполнить "Поручения (ТД) АСТ00-00112"', "step": "Исполнить",
             "executed": False, "target_id": TARGET, "target_type": "DMInternalDocument"}
        ],
    )
    old = {"id": OTHER_CHECK, "name": 'Проверить исполнение "Поручения (ТД) АСТ00-00112"', "step": "Проверить исполнение"}
    new = {"id": CHECK_ID, "name": 'Проверить исполнение "Поручения (ТД) АСТ00-00112"', "step": "Проверить исполнение"}
    calls = iter([[old], [old, new]])
    monkeypatch.setattr(mod, "open_tasks_for_target", lambda *_a, **_k: next(calls))

    out = mod.handle_docflow_task_action({"action": "close_without_report", "task_id": EXEC_ID, "fio": "И", "password": "x"})

    assert [task for task, *_ in pressed] == [EXEC_ID, CHECK_ID]
    assert out["check_task_id"] == CHECK_ID


def test_not_executed_by_docflow_is_an_error(monkeypatch):
    _setup(monkeypatch, open_rows=[])
    monkeypatch.setattr(mod, "mark_task_executed", lambda *_a, **_k: {"id": EXEC_ID, "executed": False})
    with pytest.raises(DocflowError):
        mod.handle_docflow_task_action({"action": "close_without_report", "task_id": EXEC_ID, "fio": "И", "password": "x"})


def test_needs_session_password(monkeypatch):
    _setup(monkeypatch, open_rows=[])
    with pytest.raises(DocflowError):
        mod.handle_docflow_task_action({"action": "close_without_report", "task_id": EXEC_ID, "fio": "И"})
