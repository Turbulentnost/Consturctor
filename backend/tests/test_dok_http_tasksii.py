"""TasksII/User: тело POST — внутренний формат 1С, не JSON."""

from __future__ import annotations

import json

from app.tools.onec.v8_internal_format import structure_to_internal


def test_tasksii_posts_internal_structure_not_json(monkeypatch) -> None:
    from app.tools.onec import dok_http

    posted: list[str] = []

    class Response:
        status_code = 200
        reason_phrase = "OK"
        text = json.dumps(
            [{"Исполнитель": "Ильченко Екатерина Александровна", "Description": "Согласовать"}],
            ensure_ascii=False,
        )

        def json(self):
            return json.loads(self.text)

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> bool:
            return False

        def post(self, _url, content=None, headers=None):
            posted.append(content.decode("utf-8"))
            assert headers["Content-Type"].startswith("text/plain")
            return Response()

        def get(self, *_args, **_kwargs):
            raise AssertionError("GET не нужен, когда POST уже вернул строки")

    monkeypatch.setattr(dok_http, "dok_http_base_url", lambda: "http://dok/hs/dterp")
    monkeypatch.setattr(dok_http.httpx, "Client", Client)
    dok_http.set_request_auth("user", "secret")
    try:
        rows = dok_http.fetch_user_document_executions(
            "11111111-1111-1111-1111-111111111111",
            user_fio="Ильченко Екатерина Александровна",
        )
    finally:
        dok_http.clear_request_auth()

    assert posted[0] == structure_to_internal(
        {"Пользователь": "11111111-1111-1111-1111-111111111111"}
    )
    assert "UserRef" not in posted[0]
    assert rows[0]["Description"] == "Согласовать"


def test_tasksii_reads_internal_table(monkeypatch) -> None:
    from app.tools.onec import dok_http

    class Response:
        status_code = 200
        reason_phrase = "OK"
        text = '{"#",table}'

        def json(self):
            raise json.JSONDecodeError("not json", self.text, 0)

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> bool:
            return False

        def post(self, _url, content=None, headers=None):
            return Response()

        def get(self, *_args, **_kwargs):
            raise AssertionError("таблица уже разобрана")

    monkeypatch.setattr(dok_http, "dok_http_base_url", lambda: "http://dok/hs/dterp")
    monkeypatch.setattr(dok_http.httpx, "Client", Client)
    monkeypatch.setattr(
        dok_http,
        "from_internal_string",
        lambda _text: [{"name": "Задача"}],
    )
    dok_http.set_request_auth("user", "secret")
    try:
        rows = dok_http.fetch_user_document_executions("Ильченко Екатерина Александровна")
    finally:
        dok_http.clear_request_auth()
    assert rows == [{"name": "Задача"}]
