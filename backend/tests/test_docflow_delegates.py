"""Задачи сотрудника, за которого пользователь работает (замещение / помощник)."""

from __future__ import annotations

import pytest

from app.tools.onec import dok_soap
from app.tools.onec.docflow_inbox_map import map_inbox_row

ME = "Мангасарян Давид Каренович"
BOSS = "Ясыров Богдан Джумазаевич"


@pytest.fixture(autouse=True)
def _tmp_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(dok_soap, "_cache_dir", lambda: tmp_path)


def _dump() -> dict[str, object]:
    return {
        "rows": [
            {"id": "mine", "performer": ME, "author": "Соломичева Светлана Викторовна", "step": "Исполнить"},
            {"id": "boss", "performer": BOSS, "author": "Акинина Татьяна Владимировна", "step": "Ознакомиться",
             "name": 'Ознакомиться "Приказ АЛ00-000037"'},
            {"id": "other", "performer": "Иванов Иван Иванович", "author": "Петров Пётр Петрович", "step": "Ознакомиться"},
        ]
    }


def test_slice_adds_delegate_tasks() -> None:
    sliced = dok_soap.slice_dump_for_user(_dump(), ME, delegate_fios=[BOSS])
    roles = {row["id"]: row["role"] for row in sliced["rows"]}
    assert roles == {"mine": "executor", "boss": "delegate"}
    mapped = map_inbox_row(next(row for row in sliced["rows"] if row["id"] == "boss"), fio=ME)
    assert mapped["role"] == "delegate"
    assert mapped["on_behalf_of"] == BOSS
    assert mapped["performer"] == BOSS
    assert mapped["kind"] == "acquaint"


def test_parse_delegate_fios_accepts_text() -> None:
    assert dok_soap.parse_delegate_fios(f"{BOSS};\n{BOSS}, Иванов И.И.") == [BOSS, "Иванов И.И."]


def _probe(monkeypatch, rows: list[dict[str, object]]) -> dict[str, object]:
    monkeypatch.setattr(dok_soap, "find_user", lambda _config, name: {"id": "u1", "name": name, "type": "DMUser"})
    monkeypatch.setattr(dok_soap, "list_open_tasks", lambda *_args, **_kwargs: rows)
    return dok_soap.probe_by_user_delegates(object(), ME)


def test_probe_honoured_by_user_filter_finds_boss(monkeypatch) -> None:
    rows = [
        {"performer": ME, "author": "Соломичева Светлана Викторовна"},
        {"performer": BOSS, "author": "Акинина Татьяна Владимировна"},
        {"performer": "Никитаев Алексей Вячеславович", "author": ME},
    ]
    result = _probe(monkeypatch, rows)
    assert result["status"] == "ok"
    assert result["delegates"] == [BOSS]
    assert dok_soap.known_delegates(ME) == [BOSS]


def test_probe_detects_ignored_filter(monkeypatch) -> None:
    rows = [{"performer": f"Сотрудник {index} Тестович", "author": "Автор А.А."} for index in range(20)]
    result = _probe(monkeypatch, rows)
    assert result["status"] == "ignored"
    assert result["delegates"] == []


def test_probe_timeout_counts_as_ignored(monkeypatch) -> None:
    monkeypatch.setattr(dok_soap, "find_user", lambda _config, name: {"id": "u1", "name": name})

    def slow(*_args, **_kwargs):
        raise RuntimeError("timed out")

    monkeypatch.setattr(dok_soap, "list_open_tasks", slow)
    assert dok_soap.probe_by_user_delegates(object(), ME)["status"] == "ignored"


def test_action_allowed_on_delegate_task(monkeypatch) -> None:
    from app.services.docflow_task_action import handle_docflow_task_action

    sent: list[str] = []
    monkeypatch.setattr(
        "app.services.docflow_task_action.load_config",
        lambda **_kwargs: type("Cfg", (), {"timeout": 5})(),
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.retrieve_task_card",
        lambda _config, task_id, *, timeout: {"id": task_id, "executed": False, "performer": BOSS, "step": "Ознакомиться"},
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.mark_task_executed",
        lambda _config, task_id, **_kwargs: sent.append(task_id),
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.retrieve_tasks",
        lambda _config, ids, **_kwargs: [{"id": ids[0], "executed": True, "execution_mark": "ExecutedPositive"}],
    )
    args = {"action": "acquaint", "task_id": "t", "fio": ME, "erp_password": "x"}
    from app.services.docflow_tasks import DocflowError

    with pytest.raises(DocflowError, match="не вам"):
        handle_docflow_task_action(dict(args))
    handle_docflow_task_action({**args, "delegate_fios": [BOSS]})
    assert sent == ["t"]
