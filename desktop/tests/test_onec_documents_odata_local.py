"""Tests for OData-backed 1C document tools on desktop."""

from __future__ import annotations

from unittest.mock import patch

from app.tools.host import invoke_tool
from app.tools.server_tools import LOCAL_BACKEND_TOOL_NAMES, SERVER_TOOL_NAMES


def test_onec_document_tools_use_odata_not_com_or_server() -> None:
    for name in (
        "onec.meeting_service_notes",
        "onec.search_documents",
        "onec.get_document_card",
    ):
        assert name in LOCAL_BACKEND_TOOL_NAMES
        assert name not in SERVER_TOOL_NAMES


def test_meeting_service_notes_filters_theme_client_side() -> None:
    payload = {
        "result": {
            "value": [
                {
                    "Ref_Key": "11111111-1111-1111-1111-111111111111",
                    "Number": "000012345",
                    "Date": "2026-09-10T10:00:00",
                    "ТемаСлужебнойЗаписки_Name": "Прочее",
                    "МенеджерКому_Name": "Ильченко Екатерина Александровна",
                },
                {
                    "Ref_Key": "22222222-2222-2222-2222-222222222222",
                    "Number": "000012346",
                    "Date": "2026-09-10T11:00:00",
                    "ТемаСлужебнойЗаписки_Name": "Организация совещаний (регл.)",
                    "ТемаСовещания": "Совет директоров по ГК",
                    "МенеджерКому_Name": "Ильченко Екатерина Александровна",
                },
            ]
        }
    }

    with patch("app.tools.onec_odata_invoke.fetch_odata_list", return_value=payload["result"]):
        result = invoke_tool(
            "onec.meeting_service_notes",
            {
                "date": "2026-09-10",
                "fio": "Ильченко Екатерина Александровна",
            },
        )

    assert result["count"] == 1
    assert result["source"] == "odata"
    assert result["notes"][0]["number"] == "000012346"
    assert "совещ" in result["notes"][0]["theme"].casefold()


def test_search_documents_by_query() -> None:
    payload = {
        "result": {
            "value": [
                {
                    "Ref_Key": "33333333-3333-3333-3333-333333333333",
                    "Number": "000099999",
                    "Date": "2026-09-01T00:00:00",
                    "ТемаСлужебнойЗаписки_Name": "Совет директоров по ГК",
                    "ТемаСовещания": "Заседание СД",
                }
            ]
        }
    }

    with patch("app.tools.onec_odata_invoke.fetch_odata_list", return_value=payload["result"]):
        result = invoke_tool(
            "onec.search_documents",
            {"query": "совет директоров по гк", "max_results": 5},
        )

    assert result["found"] is True
    assert result["count"] == 1
    assert result["source"] == "odata"
    assert "совет" in result["documents"][0]["title"].casefold()
