"""Тесты подсказки отдела/плательщика для входящей корреспонденции."""

from __future__ import annotations

from app.services.erp_incoming import build_create_body
from app.services.incoming_suggest import (
    LEADERSHIP_DEPARTMENT_CODES,
    RESERVE_DEPARTMENT_CODE,
    detect_organization,
    handle_incoming_suggest,
    suggest_incoming_route,
)
from app.services.onec_tools import ONEC_TOOLS


def test_legal_letter_suggests_legal_department_and_ks_payer() -> None:
    result = suggest_incoming_route(
        subject="Претензия по договору поставки № 42",
        body="Направляем претензию. Дело передано в арбитражный суд.",
        sender_email="lawyer@example.ru",
    )
    assert result["department"]["code"] == "00-000044"
    assert result["direction"] == "КС"
    assert result["payer"]["code"] == "ТурбулентностьДОНКС"
    assert result["confidence"] > 0.3


def test_tkp_request_routes_to_orkk_with_production_payer() -> None:
    result = suggest_incoming_route(
        subject="Просим выслать ТКП",
        body="Прошу рассмотреть возможность поставки расходомеров, нужна цена и наличие.",
        sender_email="zakupki@zavod.ru",
    )
    assert result["department"]["code"] == "00-000042"
    assert result["source"].startswith("det_sales")
    assert result["direction"] == "ПР"
    assert result["payer"]["code"] == "ТурбулентностьДОНПроизводство1"


def test_grand_dealer_letter_detects_almaz_org_and_payer() -> None:
    result = suggest_incoming_route(
        subject="Запрос цены на счетчик Гранд SPI",
        body="Прошу сообщить стоимость счетчиков гранд spi.",
        sender_email="dealer@example.ru",
    )
    assert result["department"]["code"] == "00-000155"
    assert result["organization"]["code"] == "АЛ"
    assert result["payer"]["code"] == "АЛМАЗ"


def test_no_match_falls_back_to_reserve_department() -> None:
    result = suggest_incoming_route(subject="Здравствуйте", body="", sender_email="")
    assert result["department"]["code"] == RESERVE_DEPARTMENT_CODE
    assert result["source"] == "reserve"
    assert result["payer"]["code"] == "ТурбулентностьДОНКС"


def test_suggestions_only_contain_onec_mapped_departments() -> None:
    from app.services.erp_incoming import _load_json_map

    keys = _load_json_map("odata_department_keys.json")
    for subject in (
        "Претензия и иск",
        "ТКП на оборудование",
        "Акт сверки взаиморасчетов",
        "Поверка счетчиков и сертификация",
        "Здравствуйте",
    ):
        result = suggest_incoming_route(subject=subject, body="", sender_email="")
        for candidate in result["candidates"]:
            assert candidate["code"] in keys, candidate
            assert candidate["code"] not in LEADERSHIP_DEPARTMENT_CODES


def test_detect_organization_keywords() -> None:
    assert detect_organization("нужны счетчики гранд spi") == "АЛ"
    assert detect_organization("вопрос по метрогазсервис") == "МГ"
    assert detect_organization("обычное письмо") == "НП"


def test_handle_incoming_suggest_args_mapping() -> None:
    result = handle_incoming_suggest(
        {
            "subject": "Претензия",
            "body": "арбитражный суд, исполнительный лист",
            "sender_email": "a@b.ru",
        }
    )
    assert result["department"]["code"] == "00-000044"
    assert result["payer_options"]


def test_suggest_tool_registered() -> None:
    assert "onec.incoming_suggest" in ONEC_TOOLS


def test_build_create_body_payer_override_by_code_and_name() -> None:
    base = {
        "department_id": "00-000066",
        "theme": "Письмо",
        "partner": "ООО Пример",
    }
    body = build_create_body({**base, "payer_direction": "АЛМАЗ"})
    assert body["ПлательщикНаправление"] == "АЛМАЗ"
    assert body["ПлательщикНаправление_Type"] == "Edm.String"

    body = build_create_body({**base, "payer_direction": "ООО «Алмаз»"})
    assert body["ПлательщикНаправление"] == "АЛМАЗ"

    # Мусорное значение игнорируется — плательщик по организации (НП default).
    body = build_create_body({**base, "payer_direction": "не существует"})
    assert body["ПлательщикНаправление"] == "ТурбулентностьДОНПроизводство1"
