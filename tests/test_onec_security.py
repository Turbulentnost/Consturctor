from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from platform_tool_onec.security import (
    validate_odata_entity,
    validate_odata_path,
    validate_sql_query,
)


@pytest.fixture
def onec_client(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_tool_onec.main")
    importlib.reload(module)
    return TestClient(module.app)


def test_sql_allowlist_rejects_unknown_table() -> None:
    with pytest.raises(ValueError, match="SQL table not allowed"):
        validate_sql_query("SELECT * FROM dbo.secret_table")


def test_sql_allowlist_accepts_v8users() -> None:
    sql = validate_sql_query("SELECT TOP 1 id FROM dbo.v8users")
    assert "v8users" in sql


def test_odata_allowlist_rejects_unknown_entity() -> None:
    with pytest.raises(ValueError, match="OData entity not allowed"):
        validate_odata_entity("Catalog_UnknownEntity")


def test_odata_allowlist_accepts_outgoing_doc() -> None:
    entity = validate_odata_entity("Document_ТД_ИсходящаяКорреспонденция")
    assert entity == "Document_ТД_ИсходящаяКорреспонденция"


def test_odata_path_preserves_query_and_validates_entity() -> None:
    path = validate_odata_path(
        "Document_ТД_ВходящаяКорреспонденция(guid'00000000-0000-0000-0000-000000000001')?$format=json&$top=3"
    )
    assert path.startswith("Document_ТД_ВходящаяКорреспонденция(guid'")
    assert "$format=json" in path
    assert "$top=3" in path


def test_onec_stub_odata_get_without_real_url(onec_client: TestClient) -> None:
    response = onec_client.post(
        "/api/v1/tools/onec.odata_get/invoke",
        json={
            "payload": {
                "entity": "Document_ТД_ИсходящаяКорреспонденция",
                "top": 2,
            }
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["source"] == "stub"
    assert data["data"]["count"] == 2
    assert data["data"]["entity"] == "Document_ТД_ИсходящаяКорреспонденция"


def test_onec_stub_odata_get_rejects_unknown_entity(onec_client: TestClient) -> None:
    response = onec_client.post(
        "/api/v1/tools/onec.odata_get/invoke",
        json={"payload": {"entity": "Catalog_UnknownEntity", "top": 1}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "not allowed" in (data.get("error") or "").lower()


def test_onec_stub_sql_rejects_write(onec_client: TestClient) -> None:
    response = onec_client.post(
        "/api/v1/tools/onec.sql_query/invoke",
        json={"payload": {"sql": "DELETE FROM dbo.v8users"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False


def test_onec_stub_sql_accepts_select(onec_client: TestClient) -> None:
    response = onec_client.post(
        "/api/v1/tools/onec.sql_query/invoke",
        json={"payload": {"sql": "SELECT TOP 1 id FROM dbo.v8users"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["source"] == "stub"
