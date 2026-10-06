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


def _capture_task_action(monkeypatch, outcome: dict[str, object]) -> list[dict[str, object]]:
    sent: list[dict[str, object]] = []

    def fake(task_id: str, button: int, **kwargs: object) -> dict[str, object]:
        sent.append({"task_id": task_id, "button": button, **kwargs})
        return outcome

    monkeypatch.setattr("app.services.docflow_task_action.post_task_action", fake)
    monkeypatch.setattr("app.services.docflow_task_action.drop_task_from_inbox_cache", lambda *ids: sent.append({"dropped": ids}))
    return sent


def test_close_action_posts_task_action(monkeypatch) -> None:
    def fail_patch(*_args, **_kwargs) -> str:
        raise AssertionError("закрытие не должно переносить срок процесса")

    monkeypatch.setattr("app.tools.onec.dok_http.patch_task_deadline", fail_patch)
    sent = _capture_task_action(
        monkeypatch,
        {"ok": True, "closed": True, "needs_form": False, "summary": "Задача выполнена"},
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
    assert result["closed"] is True
    assert result["summary"] == "Задача выполнена"
    assert sent[0]["task_id"] == "1d3729cc-b5b3-11f1-9889-6cb31113810c"
    assert sent[0]["button"] == 1
    assert sent[0]["auth"] == ("Мангасарян Давид Карленович", "secret")
    assert sent[1]["dropped"] == ("1d3729cc-b5b3-11f1-9889-6cb31113810c",)


def test_close_sends_clicked_task_only(monkeypatch) -> None:
    """Соседние задачи документа не ищутся и не закрываются: это делает 1С."""
    sent = _capture_task_action(
        monkeypatch,
        {"ok": True, "closed": True, "needs_form": False, "summary": "Исполнено"},
    )
    result = handle_docflow_task_action(
        {
            "action": "execute",
            "task_id": "stale",
            "step": "Исполнить",
            "fio": "Мангасарян Давид Карленович",
            "erp_password": "secret",
        }
    )
    assert [row["task_id"] for row in sent if "task_id" in row] == ["stale"]
    assert result["task_id"] == "stale"
    assert result["closed"] is True


def test_unpublished_task_action_does_not_close(monkeypatch) -> None:
    from app.tools.onec.dok_http import TaskActionNotPublished

    def missing(*_args, **_kwargs) -> dict[str, object]:
        raise TaskActionNotPublished("нет метода")

    monkeypatch.setattr("app.services.docflow_task_action.post_task_action", missing)
    monkeypatch.setattr(
        "app.tools.onec.dok_soap.mark_task_executed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("SOAP-отметка запрещена")),
    )
    result = handle_docflow_task_action(
        {
            "action": "execute",
            "task_id": "1d3729cc-b5b3-11f1-9889-6cb31113810c",
            "step": "Исполнить",
            "fio": "Мангасарян Давид Карленович",
            "erp_password": "secret",
        }
    )
    assert result["ok"] is False
    assert result["closed"] is False
    assert result["needs_form"] is True
    assert "карточке 1С" in result["summary"]


def test_onec_refusal_is_shown_as_is(monkeypatch) -> None:
    sent = _capture_task_action(
        monkeypatch,
        {"ok": False, "closed": False, "needs_form": False, "summary": "Задача не закрыта: нет цены"},
    )
    result = handle_docflow_task_action(
        {
            "action": "execute",
            "task_id": "t",
            "step": "Исполнить",
            "fio": "Мангасарян Давид Карленович",
            "erp_password": "x",
        }
    )
    assert result["ok"] is False
    assert result["closed"] is False
    assert result["summary"] == "Задача не закрыта: нет цены"
    assert "dropped" not in sent[-1]


def test_post_task_action_body_and_unpublished(monkeypatch) -> None:
    from app.tools.onec.dok_http import TaskActionNotPublished, parse_task_action_response, post_task_action

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode("utf-8")
        if request.url.path.endswith("/missing"):
            return httpx.Response(404, text="not found")
        return httpx.Response(200, json={"ok": False, "closed": False, "summary": "нет цены"})

    monkeypatch.setattr(
        "app.tools.onec.dok_http.dok_http_base_url",
        lambda: "http://192.168.2.229:81/doc/hs/dterp",
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        "app.tools.onec.dok_http.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    outcome = post_task_action(
        "1d3729cc-b5b3-11f1-9889-6cb31113810c",
        2,
        comment="замечание",
        actual_performer="Иванов Иван Иванович",
        auth=("user", "secret"),
    )
    assert outcome["summary"] == "нет цены"
    assert outcome["closed"] is False
    assert captured["url"] == "http://192.168.2.229:81/doc/hs/dterp/TaskAction"
    assert '"button": 2' in str(captured["body"]) or '"button":2' in str(captured["body"])
    assert "Иванов Иван Иванович" in str(captured["body"])
    parsed = parse_task_action_response({"Успех": "да", "Закрыта": False, "Описание": "как есть"})
    assert parsed["ok"] is True
    assert parsed["closed"] is False
    assert parsed["summary"] == "как есть"

    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    monkeypatch.setattr(
        "app.tools.onec.dok_http.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(missing), **kwargs),
    )
    try:
        post_task_action("task", 1, auth=("user", "secret"))
    except TaskActionNotPublished:
        pass
    else:
        raise AssertionError("404 должен означать, что TaskAction не опубликован")


def test_drop_task_from_inbox_cache_keeps_other_rows(tmp_path, monkeypatch) -> None:
    from app.tools.onec import dok_soap

    dok_soap._inbox_cache.clear()
    monkeypatch.setattr(dok_soap, "_cache_dir", lambda: tmp_path)
    payload = {"kind": "open_dump", "count": 2, "rows": [{"id": "gone"}, {"id": "stay"}]}
    key = "dump|http://192.168.2.229/doc|1|user|fp"
    dok_soap._store_cache(key, payload)
    dok_soap.drop_task_from_inbox_cache("gone")
    stored = dok_soap._inbox_cache[key][1]
    assert [row["id"] for row in stored["rows"]] == ["stay"]
    assert stored["count"] == 1
    disk = list(tmp_path.glob("*.json"))
    assert len(disk) == 1
    saved = disk[0].read_text(encoding="utf-8")
    assert "gone" not in saved
    assert "stay" in saved
