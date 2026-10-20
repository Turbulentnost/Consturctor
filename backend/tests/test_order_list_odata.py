"""Список приказов не должен после страницы дочитывать связи и табличные части."""

from __future__ import annotations

import pytest

from app.services import onec_tools


def _rows_payload() -> dict:
    return {
        "data": {
            "value": [
                {"Ref_Key": "11111111-1111-1111-1111-111111111111", "Number": "1", "Date": "2026-10-01"},
                {"Ref_Key": "22222222-2222-2222-2222-222222222222", "Number": "2", "Date": "2026-09-01"},
            ]
        }
    }


def test_order_list_skips_navigation_and_tabular_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onec_tools, "_odata_get", lambda args: _rows_payload())

    def fail(*_args, **_kwargs):
        raise AssertionError("list must not follow navigation")

    monkeypatch.setattr(onec_tools, "_resolve_navigation_names", fail)
    monkeypatch.setattr(onec_tools, "_fetch_related_tabular_parts", fail)

    result = onec_tools._fetch_odata_list(
        {
            "entity": "Document_ТД_Приказ",
            "top": 2,
            "filter": "DeletionMark eq false",
            "odata_base_url": "http://odata.example/odata",
        }
    )
    assert result["count"] == 2


def test_resolve_navigation_false_skips_followups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        onec_tools,
        "_odata_get",
        lambda args: {
            "data": {
                "Ref_Key": "11111111-1111-1111-1111-111111111111",
                "Number": "1",
                "Содержание": "текст",
            }
        },
    )

    def fail(*_args, **_kwargs):
        raise AssertionError("resolve_navigation=false must not follow links")

    monkeypatch.setattr(onec_tools, "_resolve_navigation_names", fail)
    monkeypatch.setattr(onec_tools, "_fetch_related_tabular_parts", fail)

    result = onec_tools._fetch_odata_list(
        {
            "entity": "Document_ТД_Приказ",
            "ref_key": "11111111-1111-1111-1111-111111111111",
            "resolve_navigation": False,
            "odata_base_url": "http://odata.example/odata",
        }
    )
    assert result["count"] == 1
    assert result["value"][0]["Содержание"] == "текст"
