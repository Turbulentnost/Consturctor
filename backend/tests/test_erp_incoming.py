from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.erp_incoming import (
    build_create_body,
    handle_incoming_correspondence,
    handle_incoming_correspondence_write,
    stub_incoming_correspondence_write,
)
from app.services.onec_tools import ONEC_TOOLS, ONEC_WRITE_TOOLS


def test_build_create_body_requires_department_and_theme() -> None:
    with pytest.raises(Exception):
        build_create_body({"theme": "Test"})
    body = build_create_body({"department_id": "00-000066", "theme": "Письмо клиента"})
    assert body["Кому"] == "00-000066"
    assert body["ТемаСлужебнойЗаписки"] == "Письмо клиента"
    assert body["ИсточникПоступления"] == "EMAIL"
    assert body["ПодразделениеИсполнитель_Key"]


def test_incoming_departments_list() -> None:
    result = handle_incoming_correspondence({"action": "departments"})
    assert result["count"] >= 1
    assert isinstance(result["departments"], list)


def test_incoming_write_create_calls_odata_post() -> None:
    posted: list[dict] = []

    def fake_post(args: dict):
        posted.append(args)
        return {
            "summary": "ok",
            "erp_document_id": "11111111-2222-3333-4444-555555555555",
            "data": {"Ref_Key": "11111111-2222-3333-4444-555555555555", "Number": "ВК-000099"},
        }

    with patch("app.services.erp_incoming._odata_post", side_effect=fake_post):
        with patch("app.services.erp_incoming._attach_msg_to_document", return_value=None):
            result = handle_incoming_correspondence_write(
                {
                    "action": "create",
                    "department_id": "00-000066",
                    "theme": "Тест OData",
                    "attach_msg": False,
                }
            )

    assert result["number"] == "ВК-000099"
    assert posted[0]["entity"]
    assert posted[0]["body"]["ТемаСлужебнойЗаписки"] == "Тест OData"


def test_stub_incoming_write() -> None:
    result = stub_incoming_correspondence_write(
        {"department_id": "00-000066", "theme": "Stub"}
    )
    assert result["source"] == "stub"
    assert result["body"]["Кому"] == "00-000066"


def test_onec_tools_register_incoming() -> None:
    assert "onec.incoming_correspondence" in ONEC_TOOLS
    assert "onec.incoming_correspondence_write" in ONEC_WRITE_TOOLS
