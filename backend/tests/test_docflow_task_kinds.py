"""Тип задачи ДО по шагу процесса и действия, которые к нему допустимы."""

from __future__ import annotations

import pytest

from app.services.docflow_task_action import handle_docflow_task_action
from app.services.docflow_tasks import DocflowError
from app.tools.onec.docflow_task_kinds import docflow_task_kind, resolve_action, web_client_task_url


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


def test_web_client_task_url_reorders_uuid() -> None:
    url = web_client_task_url("192.168.2.229", 81, "/doc", "1d3729cc-b5b3-11f1-9889-6cb31113810c")
    assert url.startswith("http://192.168.2.229:81/doc/#e1cib/data/")
    assert url.endswith("?ref=98896cb31113810c11f1b5b31d3729cc")


def _card_monkeypatch(monkeypatch, card: dict[str, object], sent: list[dict[str, object]]) -> None:
    monkeypatch.setattr(
        "app.services.docflow_task_action.load_config",
        lambda **_kwargs: type("Cfg", (), {"timeout": 5})(),
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.retrieve_task_card",
        lambda _config, task_id, *, timeout: {"id": task_id, "executed": False, **card},
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.mark_task_executed",
        lambda _config, task_id, *, timeout, comment="", mark="": sent.append(
            {"id": task_id, "mark": mark, "comment": comment}
        ),
    )
    monkeypatch.setattr(
        "app.services.docflow_task_action.retrieve_tasks",
        lambda _config, ids, **_kwargs: [{"id": ids[0], "executed": True, "execution_mark": "ExecutedPositive"}],
    )


def _args(action: str, **extra: object) -> dict[str, object]:
    return {"action": action, "task_id": "t-1", "fio": "Мангасарян Давид Каренович", "erp_password": "x", **extra}


def test_acquaint_task_is_completed_with_acquaint_mark(monkeypatch) -> None:
    sent: list[dict[str, object]] = []
    _card_monkeypatch(
        monkeypatch,
        {"step": "Ознакомиться с результатом рассмотрения", "performer": "Мангасарян Давид Каренович"},
        sent,
    )
    result = handle_docflow_task_action(_args("acquaint"))
    assert sent == [{"id": "t-1", "mark": "ExecutedPositive", "comment": ""}]
    assert result["summary"] == "Отмечено: ознакомлен в документообороте."
    assert result["kind"] == "acquaint_result"


def test_decline_approval_sends_negative_mark_with_comment(monkeypatch) -> None:
    sent: list[dict[str, object]] = []
    _card_monkeypatch(monkeypatch, {"step": "Согласовать", "performer": "Мангасарян Давид Каренович"}, sent)
    handle_docflow_task_action(_args("decline", comment="Нет обоснования"))
    assert sent == [{"id": "t-1", "mark": "ExecutedNegative", "comment": "Нет обоснования"}]


def test_negative_action_requires_comment(monkeypatch) -> None:
    sent: list[dict[str, object]] = []
    _card_monkeypatch(monkeypatch, {"step": "Проверить исполнение", "performer": "Мангасарян Давид Каренович"}, sent)
    with pytest.raises(DocflowError, match="комментарий"):
        handle_docflow_task_action(_args("return"))
    assert sent == []


def test_action_not_matching_task_kind_is_refused(monkeypatch) -> None:
    sent: list[dict[str, object]] = []
    _card_monkeypatch(monkeypatch, {"step": "Ознакомиться", "performer": "Мангасарян Давид Каренович"}, sent)
    with pytest.raises(DocflowError, match="недоступно"):
        handle_docflow_task_action(_args("decline", comment="x"))
    assert sent == []
