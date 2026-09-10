"""Local ERP OData snapshot is searched before live 1C metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.services import odata_local_catalog, onec_tools
from app.services.odata_local_catalog import entity_search_score, extra_entity_names
from app.services.onec_tools import OnecToolError, invoke_onec

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "odata_document_structures_mini.json"


@pytest.fixture
def mini_snapshot(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "odata_local_catalog_path", FIXTURE)
    odata_local_catalog.reset_local_catalog_cache()
    onec_tools.reset_catalog_cache()
    yield FIXTURE
    odata_local_catalog.reset_local_catalog_cache()
    onec_tools.reset_catalog_cache()


def test_search_score_matches_russian_phrase() -> None:
    assert entity_search_score("служебная записка", "Document_ТД_СлужебнаяЗаписка") >= 40
    assert entity_search_score("поручен", "Document_ТД_Поручения") >= 40
    assert entity_search_score("неттакойсущности", "Document_ТД_Поручения") == 0


def test_catalog_uses_local_snapshot_with_structure(mini_snapshot: Path) -> None:
    result = invoke_onec("onec.odata_catalog", {"search": "служебная записка", "limit": 10})
    assert result["source"] == "local"
    assert result["live_fallback"] is False
    names = [item["name"] for item in result["entities"]]
    assert "Document_ТД_СлужебнаяЗаписка" in names
    entity = next(item for item in result["entities"] if item["name"] == "Document_ТД_СлужебнаяЗаписка")
    assert "Тема" in entity["field_names"]
    assert "Участники" in entity["tabular_names"]
    assert entity["tabular"]["Участники"]["entity"] == "Document_ТД_СлужебнаяЗаписка_Участники"


def test_catalog_does_not_hit_live_1c_when_snapshot_matches(
    mini_snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*, force: bool = False):
        raise AssertionError("live 1C catalog must not be loaded")

    monkeypatch.setattr(onec_tools, "_load_odata_catalog", boom)
    result = invoke_onec("onec.odata_catalog", {"search": "поручен"})
    assert result["source"] == "local"
    assert "Document_ТД_Поручения" in result["documents"]


def test_catalog_falls_back_to_live_when_snapshot_misses(
    mini_snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_live(*, force: bool = False):
        assert force is True
        return [
            {
                "name": "Catalog_Контрагенты",
                "kind": "catalog",
                "prefix": "Catalog",
            }
        ]

    monkeypatch.setattr(onec_tools, "odata_configured", lambda: True)
    monkeypatch.setattr(onec_tools, "_load_odata_catalog", fake_live)
    monkeypatch.setattr(
        onec_tools,
        "REAL_HANDLERS",
        {**onec_tools.REAL_HANDLERS, "onec.odata_catalog": onec_tools._odata_catalog},
    )
    result = onec_tools._odata_catalog({"search": "контрагенты", "limit": 10})
    assert result["source"] == "odata"
    assert result["live_fallback"] is True
    assert result["local_missed"] is True
    assert result["catalogs"] == ["Catalog_Контрагенты"]


def test_catalog_keeps_local_result_when_live_fallback_fails(
    mini_snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_live(*, force: bool = False):
        raise OnecToolError("1C OData is down")

    monkeypatch.setattr(onec_tools, "_load_odata_catalog", fail_live)
    result = onec_tools._odata_catalog({"search": "неттакойсущностиxyz"})
    assert result["source"] == "local"
    assert result["live_error"] is True
    assert result["total_matched"] == 0


def test_extra_names_include_tabular_parts(mini_snapshot: Path) -> None:
    names = extra_entity_names()
    assert "Document_ТД_СлужебнаяЗаписка" in names
    assert "Document_ТД_СлужебнаяЗаписка_Участники" in names


def test_real_snapshot_finds_common_erp_documents() -> None:
    odata_local_catalog.reset_local_catalog_cache()
    onec_tools.reset_catalog_cache()
    result = invoke_onec("onec.odata_catalog", {"search": "служебная записка", "limit": 15})
    assert result["source"] == "local"
    assert result.get("snapshot_documents", 0) >= 700
    names = [item["name"] for item in result["entities"]]
    assert "Document_ТД_СлужебнаяЗаписка" in names
    protocol = invoke_onec("onec.odata_catalog", {"entity": "Document_ТД_Протокол", "limit": 5})
    assert protocol["source"] == "local"
    assert "Document_ТД_Протокол" in protocol["documents"]
    entity = next(item for item in protocol["entities"] if item["name"] == "Document_ТД_Протокол")
    assert entity["field_names"]
