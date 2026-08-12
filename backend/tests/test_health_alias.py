from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.health import router as health_router


def test_health_alias_paths(monkeypatch) -> None:
    async def _fake_platform_services():
        return []

    monkeypatch.setattr("app.api.v1.health._check_platform_services", _fake_platform_services)
    monkeypatch.setattr("app.api.v1.health.settings.auth_stub", True)

    app = FastAPI()
    app.include_router(health_router)
    client = TestClient(app)

    root = client.get("/health")
    assert root.status_code == 200
    assert root.json()["status"] in {"ok", "degraded"}

    alias = client.get("/api/v1/health")
    assert alias.status_code == 200
    assert alias.json()["status"] in {"ok", "degraded"}
