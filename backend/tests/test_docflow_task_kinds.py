"""Тип задачи ДО по шагу процесса и действия, которые к нему допустимы."""

from __future__ import annotations

import pytest

from app.services.docflow_task_action import handle_docflow_task_action
from app.services.docflow_tasks import DocflowError
from app.tools.onec.docflow_task_kinds import (
    action_button,
    docflow_task_kind,
    resolve_action,
    web_client_task_url,
)


@pytest.mark.parametrize(
    ("step", "name", "kind"),
    [
        ("Исполнить", "Исполнить задачу №7", "execute"),
        ("Проверить исполнение", "", "check"),
        ("Ознакомиться", 'Ознакомиться "Приказ НП00-000336"', "acquaint"),
        ("Ознакомиться с результатом согласования", "", "acquaint_result"),
        ("Ознакомиться с результатом рассмотрения", "", "acquaint_result"),
        ("", 'Ознакомиться: перенос срока по задаче "Исполнить задачу №7"', "acquaint_result"),
        ("Согласовать", "Согласовать перенос срока по задаче", "approve"),
        ("Утвердить", "", "confirm"),
        ("Рассмотреть", "", "consider"),
        ("Рассмотреть вопрос", "", "question"),
        ("Обработать резолюцию", "", "resolution"),
        ("", "", "other"),
    ],
)
def test_docflow_task_kind_by_step(step: str, name: str, kind: str) -> None:
    assert docflow_task_kind(step, name) == kind


def test_resolve_action_matches_kind() -> None:
    assert resolve_action("close", "acquaint") == "acquaint"
    assert resolve_action("close", "execute") == "execute"
    assert resolve_action("reject", "approve") == "decline"
    assert resolve_action("decline", "acquaint") == ""
    assert resolve_action("return", "execute") == ""
    assert resolve_action("acquaint", "other") == "acquaint"
    assert resolve_action("decline", "other") == ""


def test_action_button_matches_route_point() -> None:
    assert action_button("approve", "approve") == 1
    assert action_button("approve", "approve_remarks") == 2
    assert action_button("approve", "decline") == 3
    assert action_button("confirm", "confirm") == 1
    assert action_button("confirm", "decline") == 2
    assert action_button("execute", "execute") == 1
    assert action_button("check", "accept") == 1
    assert action_button("check", "return") == 2


def test_web_client_task_url_reorders_uuid() -> None:
    url = web_client_task_url("192.168.2.229", 81, "/doc", "1d3729cc-b5b3-11f1-9889-6cb31113810c")
    assert url.startswith("http://192.168.2.229:81/doc/#e1cib/data/")
    assert url.endswith("?ref=98896cb31113810c11f1b5b31d3729cc")


def _http_monkeypatch(monkeypatch, sent: list[dict[str, object]]) -> None:
    def fake(task_id: str, button: int, **kwargs: object) -> dict[str, object]:
        sent.append({"id": task_id, "button": button, "comment": kwargs.get("comment") or ""})
        return {"ok": True, "closed": True, "needs_form": False, "summary": "Ознакомлен"}

    monkeypatch.setattr("app.services.docflow_task_action.post_task_action", fake)
    monkeypatch.setattr("app.services.docflow_task_action.drop_task_from_inbox_cache", lambda *_ids: None)


def _args(action: str, **extra: object) -> dict[str, object]:
    return {"action": action, "task_id": "t-1", "fio": "Мангасарян Давид Каренович", "erp_password": "x", **extra}


def test_acquaint_task_posts_button_one(monkeypatch) -> None:
    sent: list[dict[str, object]] = []
    _http_monkeypatch(monkeypatch, sent)
    result = handle_docflow_task_action(_args("acquaint", step="Ознакомиться с результатом рассмотрения"))
    assert sent == [{"id": "t-1", "button": 1, "comment": ""}]
    assert result["summary"] == "Ознакомлен"
    assert result["kind"] == "acquaint_result"
    assert result["closed"] is True


def test_decline_approval_posts_button_three_with_comment(monkeypatch) -> None:
    sent: list[dict[str, object]] = []
    _http_monkeypatch(monkeypatch, sent)
    handle_docflow_task_action(_args("decline", step="Согласовать", comment="Нет обоснования"))
    assert sent == [{"id": "t-1", "button": 3, "comment": "Нет обоснования"}]


def test_negative_action_requires_comment(monkeypatch) -> None:
    sent: list[dict[str, object]] = []
    _http_monkeypatch(monkeypatch, sent)
    with pytest.raises(DocflowError, match="комментарий"):
        handle_docflow_task_action(_args("return", step="Проверить исполнение"))
    assert sent == []


def test_action_not_matching_task_kind_is_refused(monkeypatch) -> None:
    sent: list[dict[str, object]] = []
    _http_monkeypatch(monkeypatch, sent)
    with pytest.raises(DocflowError, match="недоступно"):
        handle_docflow_task_action(_args("decline", step="Ознакомиться", comment="x"))
    assert sent == []
