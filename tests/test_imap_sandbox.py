from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _reload_imap_module(monkeypatch: pytest.MonkeyPatch, **env: str) -> object:
    monkeypatch.setenv("USE_STUBS", env.pop("USE_STUBS", "true"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("IMAP_USERNAME", "IMAP_PASSWORD", "IMAP_HOST"):
        if key not in env:
            monkeypatch.delenv(key, raising=False)
    module = importlib.import_module("platform_tool_imap.main")
    importlib.reload(module)
    return module


@pytest.fixture
def imap_client_no_credentials(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    module = _reload_imap_module(monkeypatch)
    return TestClient(module.app)


def test_imap_search_without_credentials_returns_error(
    imap_client_no_credentials: TestClient,
) -> None:
    response = imap_client_no_credentials.post(
        "/api/v1/tools/imap.search/invoke",
        json={"payload": {"query": "ii", "user": "ii", "limit": 3}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "IMAP not configured" in body["error"]


def test_imap_search_with_credentials_uses_real_imap(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_imap_module(
        monkeypatch,
        IMAP_HOST="imap.yandex.ru",
        IMAP_USERNAME="mailbox@turbo-don.ru",
        IMAP_PASSWORD="secret",
    )
    client = TestClient(module.app)

    mock_client = MagicMock()
    mock_client.search.return_value = [42, 43]
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch.object(module, "_connect", return_value=mock_client):
        response = client.post(
            "/api/v1/tools/imap.search/invoke",
            json={"payload": {"query": "ii", "user": "ii", "limit": 3}},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["source"] == "imap"
    assert body["data"]["uids"] == [42, 43]
    mock_client.select_folder.assert_called_once_with("INBOX")
    mock_client.search.assert_called_once()
    mock_client.logout.assert_called_once()


def test_imap_stub_delegates_to_real_when_credentials_set(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_imap_module(
        monkeypatch,
        USE_STUBS="true",
        IMAP_HOST="imap.yandex.ru",
        IMAP_USERNAME="mailbox@turbo-don.ru",
        IMAP_PASSWORD="secret",
    )
    client = TestClient(module.app)

    expected = {
        "summary": "found=1",
        "query": "ii",
        "user": "ii",
        "uids": [100],
        "source": "imap",
        "host": "imap.yandex.ru",
        "mailbox": "INBOX",
    }

    with patch.object(module, "_search", return_value=expected) as search_mock:
        response = client.post(
            "/api/v1/tools/imap.search/invoke",
            json={"payload": {"query": "ii", "user": "ii", "limit": 3}},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"] == expected
    search_mock.assert_called_once()


def test_imap_fetch_message_without_credentials_returns_error(
    imap_client_no_credentials: TestClient,
) -> None:
    response = imap_client_no_credentials.post(
        "/api/v1/tools/imap.fetch_message/invoke",
        json={"payload": {"uid": 9011, "user": "ii"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "IMAP not configured" in body["error"]
