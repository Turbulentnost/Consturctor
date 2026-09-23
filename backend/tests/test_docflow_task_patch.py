"""TaskPatch: закрытие задачи документооборота телом Структура(СрокИсполнения, КонецДня)."""

from __future__ import annotations

from datetime import datetime

import httpx

from app.services.docflow_task_action import handle_docflow_task_action
from app.tools.onec.dok_http import end_of_day, internal_due_structure, patch_task_deadline


def test_internal_due_structure_is_end_of_day() -> None:
    body = internal_due_structure(end_of_day(datetime(2026, 9, 22, 14, 32, 26)))
    assert "4238019d-7e49-4fc9-91db-b6b951d5cf8e" in body
    assert '{"S","СрокИсполнения"}' in body
    assert '{"D",20260922235959}' in body


def test_patch_task_deadline_posts_uid_and_plain_body(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = request.content.decode("utf-8")
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(
        "app.tools.onec.dok_http.dok_http_base_url",
        lambda: "http://192.168.2.229:81/doc/hs/dterp",
    )
    monkeypatch.setattr(
        "app.tools.onec.dok_http._resolve_auth",
        lambda: ("user", "secret"),
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        "app.tools.onec.dok_http.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    text = patch_task_deadline("1d3729cc-b5b3-11f1-9889-6cb31113810c", datetime(2026, 9, 22, 10, 0, 0))
    assert text == "ok"
    assert captured["url"] == (
        "http://192.168.2.229:81/doc/hs/dterp/TaskPatch?UID=1d3729cc-b5b3-11f1-9889-6cb31113810c"
    )
    assert captured["content_type"] == "text/plain;charset=UTF-8"
    assert '{"D",20260922235959}' in str(captured["body"])
    assert captured["auth"]


def test_close_action_marks_task_executed(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fail_patch(*_args, **_kwargs) -> str:
        raise AssertionError("закрытие не должно переносить срок процесса")

    monkeypatch.setattr("app.tools.onec.dok_http.patch_task_deadline", fail_patch)
    monkeypatch.setattr(
        "app.services.docflow_task_action.mark_task_executed",
        lambda _config, task_id, *, timeout, **kwargs: seen.update(
            performed=task_id, result="execute", mark=kwargs.get("mark")
        ),
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.load_config",
        lambda **kwargs: seen.update(user=kwargs.get("username")) or type("Cfg", (), {"timeout": 5})(),
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.retrieve_task_card",
        lambda _config, task_id, *, timeout: {"id": task_id, "executed": False},
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.retrieve_tasks",
        lambda _config, ids, **_kwargs: [
            {"executed": True, "execution_mark": "ExecutedPositive", "id": ids[0]}
        ],
    )
    result = handle_docflow_task_action(
        {
            "action": "close",
            "task_id": "1d3729cc-b5b3-11f1-9889-6cb31113810c",
            "fio": "Мангасарян Давид Карленович",
            "erp_password": "secret",
        }
    )
    assert result["task_id"] == "1d3729cc-b5b3-11f1-9889-6cb31113810c"
    assert result["summary"] == "Задача выполнена в документообороте."
    assert seen["performed"] == "1d3729cc-b5b3-11f1-9889-6cb31113810c"
    assert seen["result"] == "execute"
    assert seen["mark"] == "ExecutedPositive"
    assert seen["user"] == "Мангасарян Давид Карленович"


def test_close_action_switches_to_live_task_after_rework(monkeypatch) -> None:
    """Доработка создаёт новую задачу: закрывать надо её, а не старый УИД."""
    stale = "1d3729cc-b5b3-11f1-9889-6cb31113810c"
    live = "7c2f1a44-b5c0-11f1-9889-6cb31113810c"
    performed: list[str] = []

    monkeypatch.setattr(
        "app.services.docflow_task_action.load_config",
        lambda **_kwargs: type("Cfg", (), {"timeout": 5})(),
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.retrieve_task_card",
        lambda _config, task_id, *, timeout: {
            "id": task_id,
            "executed": True,
            "execution_mark": "ExecutedNeutral",
            "performer": "Мангасарян Давид Карленович",
            "description": "Подключить документооборот",
            "target_id": "96396617-b5b0-11f1-9889-6cb31113810c",
            "target_type": "DMInternalDocument",
        },
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.open_tasks_for_target",
        lambda _config, target_id, target_type, *, timeout: [
            {
                "id": live,
                "executed": False,
                "performer": "Мангасарян Давид Карленович",
                "description": "Подключить документооборот",
            },
            {
                "id": "other-task",
                "executed": False,
                "performer": "Иванов Иван Иванович",
                "description": "Ознакомиться",
            },
        ],
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.mark_task_executed",
        lambda _config, task_id, *, timeout, **_kwargs: performed.append(task_id),
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.retrieve_tasks",
        lambda _config, ids, **_kwargs: [
            {"executed": True, "execution_mark": "ExecutedPositive", "id": ids[0]}
        ],
    )

    result = handle_docflow_task_action(
        {
            "action": "close",
            "task_id": stale,
            "fio": "Мангасарян Давид Карленович",
            "erp_password": "secret",
        }
    )
    assert performed == [live]
    assert result["task_id"] == live
    assert result["closed_task_ids"] == [live]


def _executed_card_monkeypatch(monkeypatch, live_rows: list[dict[str, object]], performed: list[str]) -> None:
    monkeypatch.setattr(
        "app.services.docflow_task_action.load_config",
        lambda **_kwargs: type("Cfg", (), {"timeout": 5})(),
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.retrieve_task_card",
        lambda _config, task_id, *, timeout: {
            "id": task_id,
            "executed": True,
            "performer": "Мангасарян Давид Карленович",
            "description": "Проверить все дашборды",
            "step": "Исполнить",
            "target_id": "d3d4d9a4-b5b3-11f1-9889-6cb31113810c",
            "target_type": "DMInternalDocument",
        },
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.open_tasks_for_target",
        lambda _config, target_id, target_type, *, timeout: live_rows,
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.mark_task_executed",
        lambda _config, task_id, *, timeout, **_kwargs: performed.append(task_id),
    )


def test_repeat_close_never_touches_other_tasks_of_document(monkeypatch) -> None:
    """Повторное нажатие по уже исполненной задаче не закрывает соседние задачи протокола."""
    performed: list[str] = []
    _executed_card_monkeypatch(
        monkeypatch,
        [
            {"id": "mine-other", "performer": "Мангасарян Давид Карленович",
             "description": "Убрать дашборды по должностям", "step": "Исполнить"},
            {"id": "colleague", "performer": "Комарькова Анастасия Эдуардовна",
             "description": "Проверить все дашборды", "step": "Исполнить"},
            {"id": "author-check", "performer": "Соломичева Светлана Викторовна",
             "description": "Проверить все дашборды", "step": "Проверить исполнение"},
            {"id": "acquaint", "performer": "Мангасарян Давид Карленович",
             "description": "Проверить все дашборды", "step": "Ознакомиться с результатом рассмотрения"},
        ],
        performed,
    )
    result = handle_docflow_task_action(
        {"action": "close", "task_id": "stale", "fio": "Мангасарян Давид Карленович", "erp_password": "x"}
    )
    assert performed == []
    assert result["already_executed"] is True


def test_close_refuses_task_of_another_performer(monkeypatch) -> None:
    import pytest

    from app.services.docflow_tasks import DocflowError

    performed: list[str] = []
    _executed_card_monkeypatch(monkeypatch, [], performed)
    with pytest.raises(DocflowError, match="не вам"):
        handle_docflow_task_action(
            {"action": "close", "task_id": "t", "fio": "Комарькова Анастасия Эдуардовна", "erp_password": "x"}
        )
    assert performed == []
