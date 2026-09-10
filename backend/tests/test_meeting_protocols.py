"""Unit tests for Document_ТД_Протокол OData list search (RK / SD)."""

from __future__ import annotations

import pytest

from app.services.meeting_protocols import (
    PROTOCOL_ENTITY,
    build_protocol_filter,
    list_meeting_protocols,
    normalize_protocol_row,
    stub_meeting_protocols,
)


def test_build_protocol_filter_rk_review() -> None:
    filt = build_protocol_filter({"meeting_kind": "rk"}, kind="rk")
    assert "DeletionMark eq false" in filt
    assert "startswith(Number,'РК')" in filt
    assert "Posted eq false" in filt
    assert "Статус eq 'Подготовлен'" in filt


def test_build_protocol_filter_sd_prefixes() -> None:
    filt = build_protocol_filter({"meeting_kind": "sd", "review_only": False}, kind="sd")
    assert "startswith(Number,'ПСД')" in filt
    assert "startswith(Number,'СПГ')" in filt
    assert "startswith(Number,'СД')" in filt
    assert "Статус ne 'Закрыт'" in filt


def test_build_protocol_filter_number_and_dates() -> None:
    filt = build_protocol_filter(
        {
            "meeting_kind": "rk",
            "number": "РК__001_О_037",
            "date_from": "2026-09-01",
            "date_to": "2026-09-10",
            "review_only": False,
            "include_closed": True,
        },
        kind="rk",
    )
    assert "Number eq 'РК__001_О_037'" in filt
    assert "Date ge datetime'2026-09-01T00:00:00'" in filt
    assert "Date le datetime'2026-09-10T23:59:59'" in filt
    assert "startswith" not in filt


def test_normalize_protocol_row_needs_review() -> None:
    row = {
        "Ref_Key": "8003225f-ab4c-11f1-987b-6cb31113810c",
        "Number": "СПГ_076_О_169",
        "Date": "2026-09-08T09:13:49",
        "Posted": False,
        "Статус": "Подготовлен",
        "ТемаСовещания": {"Description": "Совет директоров по ГК"},
        "ВидСовещания": "Отчетное",
    }
    item = normalize_protocol_row(row, kind="sd")
    assert item["number"] == "СПГ_076_О_169"
    assert item["needs_review"] is True
    assert item["meeting_topic"] == "Совет директоров по ГК"


def test_build_protocol_list_path_has_expand() -> None:
    from app.services.meeting_protocols import build_protocol_list_path

    path = build_protocol_list_path(
        odata_filter="DeletionMark eq false",
        limit=10,
    )
    assert path.startswith("Document_ТД_Протокол?")
    assert "$expand=ТемаСовещания" in path


def test_list_meeting_protocols_odata(monkeypatch) -> None:
    sample = {
        "Ref_Key": "e72f4680-aa87-11f1-987a-6cb31113810e",
        "Number": "РК__001_О_037",
        "Date": "2026-09-08T09:46:25",
        "Posted": True,
        "Статус": "НаИсполнении",
        "ТемаСовещания": "Заседание РК",
    }

    def fake_fetch(args: dict) -> dict:
        assert args["entity"] == PROTOCOL_ENTITY
        path = str(args.get("path") or "")
        assert "startswith" in path and "Number" in path
        return {"value": [sample], "path": path or PROTOCOL_ENTITY, "summary": "ok"}

    monkeypatch.setattr("app.services.onec_tools._fetch_odata_list", fake_fetch)
    result = list_meeting_protocols({"meeting_kind": "rk", "date": "2026-09-08"})
    assert result["source"] == "odata"
    assert result["count"] == 1
    assert result["protocols"][0]["number"] == "РК__001_О_037"
    assert result["protocols"][0]["meeting_kind"] == "rk"


def test_list_meeting_protocols_odata_error(monkeypatch) -> None:
    from app.services.onec_tools import OnecToolError

    def boom(_args: dict) -> dict:
        raise OnecToolError("HTTP 403")

    monkeypatch.setattr("app.services.onec_tools._fetch_odata_list", boom)
    result = list_meeting_protocols({"meeting_kind": "sd"})
    assert result["protocols"] == []
    assert "403" in result["error"]


def test_stub_meeting_protocols() -> None:
    result = stub_meeting_protocols({"meeting_kind": "rk", "date": "2026-09-08"})
    assert result["source"] == "stub"
    assert result["protocols"] == []


def test_normalize_kind_invalid() -> None:
    from app.services.meeting_protocols import _normalize_kind

    with pytest.raises(ValueError, match="meeting_kind"):
        _normalize_kind("unknown")


def test_build_protocol_filter_sd_includes_psd() -> None:
    filt = build_protocol_filter(
        {"meeting_kind": "sd", "date_from": "2026-09-01", "date_to": "2026-09-30"},
        kind="sd",
    )
    assert "startswith(Number,'ПСД')" in filt
    assert "Date ge datetime'2026-09-01T00:00:00'" in filt


def test_list_meeting_protocols_sd_september_live() -> None:
    from app.services.onec_tools import odata_configured

    if not odata_configured():
        pytest.skip("OData not configured")
    result = list_meeting_protocols(
        {"meeting_kind": "sd", "date_from": "2026-09-01", "date_to": "2026-09-30"}
    )
    assert result.get("error") is None, result
    assert result["count"] >= 1
    numbers = [str(item.get("number") or "") for item in result.get("protocols") or []]
    assert any(num.startswith("ПСД") for num in numbers), numbers
