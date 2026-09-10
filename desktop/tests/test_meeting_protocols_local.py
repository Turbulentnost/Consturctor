"""Tests for local onec.meeting_protocols (desktop OData proxy)."""

from __future__ import annotations

from unittest.mock import patch

from app.tools.host import invoke_tool
from app.tools.meeting_protocols_local import build_protocol_filter
from app.tools.server_tools import LOCAL_BACKEND_TOOL_NAMES, SERVER_TOOL_NAMES


def test_meeting_protocols_not_proxied_to_server() -> None:
    assert "onec.meeting_protocols" in LOCAL_BACKEND_TOOL_NAMES
    assert "onec.meeting_protocols" not in SERVER_TOOL_NAMES


def test_sd_filter_uses_psd_prefix() -> None:
    filt = build_protocol_filter(
        {"meeting_kind": "sd", "date_from": "2026-09-01", "date_to": "2026-09-30"},
        kind="sd",
    )
    assert "startswith(Number,'ПСД')" in filt
    assert "DeletionMark eq false" in filt


def test_invoke_meeting_protocols_via_odata_get() -> None:
    payload = {
        "ok": True,
        "result": {
            "value": [
                {
                    "Ref_Key": "00000000-0000-0000-0000-000000000001",
                    "Number": "ПСД_001_О_225",
                    "Date": "2026-09-10T12:00:00",
                    "Posted": False,
                    "Статус": "Подготовлен",
                }
            ],
            "summary": "1 row",
        },
    }

    with patch("app.tools.runtime_api.request", return_value=payload) as mock_request:
        result = invoke_tool(
            "onec.meeting_protocols",
            {"meeting_kind": "sd", "date_from": "2026-09-01", "date_to": "2026-09-30"},
        )

    mock_request.assert_called_once()
    call_args = mock_request.call_args
    assert call_args[0][1] == "/api/v1/tools/onec.odata_get/invoke"
    body = call_args[1]["json"]["arguments"]
    assert body["entity"] == "Document_ТД_Протокол"
    assert "path" in body
    assert "Document_ТД_Протокол" in body["path"]
    assert "startswith" in body["path"] and "Number" in body["path"]
    assert "$expand=ТемаСовещания" in body["path"]

    assert result["count"] == 1
    assert result["protocols"][0]["number"] == "ПСД_001_О_225"
    assert result["meeting_kind"] == "sd"
