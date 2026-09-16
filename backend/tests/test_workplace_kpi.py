from __future__ import annotations

from app.core.jwt import create_access_token
from app.services import sessions


def test_workplace_kpi_requires_auth():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/v1/workplace/kpi")
    assert response.status_code == 401


def test_workplace_kpi_returns_reference_dashboard(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(sessions, "is_current_session", lambda *_a, **_k: True)

    token = create_access_token(
        user_id="user-kpi-1",
        fio="Иванов Иван Иванович",
        session_id="sess-kpi",
        client="orchestrator",
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/workplace/kpi",
        headers={"Authorization": f"Bearer {token}"},
        params={"from": "2024-08-12", "to": "2024-08-18"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["periodFrom"] == "2024-08-12"
    assert body["periodTo"] == "2024-08-18"
    assert "12" in body["periodLabel"] and "18" in body["periodLabel"]
    cards = {item["id"]: item for item in body["cards"]}
    assert cards["tasks"]["displayValue"] == "78%"
    assert cards["tasks"]["trend"] == "(+12%)"
    assert cards["sla"]["displayValue"] == "92%"
    assert cards["quality"]["displayValue"] == "4.7"
    assert cards["quality"]["ring"] is False
    agents = body["agents"]
    assert any(row["code"] == "RIG-01" for row in agents)
    assert body["problemZones"]
    assert body["problemZones"][0]["typeLabel"] == "Низкое SLA"
    assert body["problemZones"][0]["deviation"] == "-14%"
    employee = body["employeeKpi"]
    assert len(employee) == 4
    assert employee[0]["id"] == "tasks"
    assert employee[0]["displayValue"] == "78%"
    assert employee[2]["displayValue"] == "4.7"
    assert body["workloadCompare"]
    assert body["dynamics"]["series"]
