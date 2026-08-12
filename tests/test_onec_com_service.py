from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def onec_com_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("API_PORT", "7831")
    from platform_tool_onec_com.main import app

    return TestClient(app)


def test_onec_com_status_stub(onec_com_client: TestClient) -> None:
    response = onec_com_client.post(
        "/api/v1/tools/onec.com.status/invoke",
        json={"run_id": "00000000-0000-0000-0000-000000000001", "payload": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["source"] == "stub"


def test_onec_com_connect_stub(onec_com_client: TestClient) -> None:
    response = onec_com_client.post(
        "/api/v1/tools/onec.com.connect/invoke",
        json={"run_id": "00000000-0000-0000-0000-000000000001", "payload": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["session_id"]


def test_onec_com_query_tasks_stub(onec_com_client: TestClient) -> None:
    response = onec_com_client.post(
        "/api/v1/tools/onec.com.query_tasks/invoke",
        json={"run_id": "00000000-0000-0000-0000-000000000001", "payload": {"mine_only": True, "limit": 5}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["source"] == "stub"
    assert body["data"]["transport"] == "com-connector"
    assert body["data"]["count"] >= 1


def test_require_32bit_on_windows_real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_STUBS", "false")
    from platform_tool_onec_com import onec_com

    if onec_com.python_bitness() == 64:
        with pytest.raises(RuntimeError, match="32BIT"):
            onec_com.require_32bit_python()
