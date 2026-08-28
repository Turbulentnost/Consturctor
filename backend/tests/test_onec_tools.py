"""1C OData tool smoke tests."""

from __future__ import annotations

from app.services.onec_security import validate_odata_entity
from app.services.onec_tools import (
    OnecToolError,
    _names_from_metadata_xml,
    _names_from_service_document,
    invoke_onec,
    odata_configured,
)


def _is_onec_acl_error(exc: OnecToolError) -> bool:
    text = str(exc)
    return "401" in text or "Доступ запрещен" in text


def test_onec_odata_get_stub_or_real() -> None:
    try:
        result = invoke_onec(
            "onec.odata_get",
            {"entity": "Document_ТД_ВходящаяКорреспонденция", "top": 2},
        )
    except OnecToolError as exc:
        if odata_configured() and _is_onec_acl_error(exc):
            return
        raise
    assert "source" in result or "value" in result or "data" in result
    if not odata_configured():
        assert result.get("source") == "stub"
        assert result.get("count", 0) >= 1


def test_onec_odata_catalog_lists_kinds() -> None:
    result = invoke_onec("onec.odata_catalog", {"limit": 50})
    assert result.get("count", 0) >= 1
    assert "documents" in result
    assert "catalogs" in result
    assert "registers" in result
    assert isinstance(result.get("entities"), list)
    kinds = {item.get("kind") for item in result["entities"]}
    assert kinds & {"document", "catalog", "register"}
    if not odata_configured():
        assert result.get("source") == "stub"


def test_odata_get_accepts_catalog_entity() -> None:
    catalog = invoke_onec("onec.odata_catalog", {"kind": "document", "limit": 5})
    entities = catalog.get("entities") or []
    assert entities
    name = str(entities[0]["name"])
    try:
        result = invoke_onec("onec.odata_get", {"entity": name, "top": 1})
    except OnecToolError as exc:
        if odata_configured() and _is_onec_acl_error(exc):
            return
        raise
    assert "source" in result or "value" in result or "data" in result


def test_validate_register_without_hardcoded_allowlist() -> None:
    assert (
        validate_odata_entity("AccumulationRegister_Остатки", allowlist=None)
        == "AccumulationRegister_Остатки"
    )
    try:
        validate_odata_entity("AccumulationRegister_Остатки", allowlist={"Document_X"})
        raise AssertionError("expected allowlist rejection")
    except ValueError:
        pass
    assert (
        validate_odata_entity(
            "AccumulationRegister_Остатки",
            allowlist={"Document_X"},
            extra_allowed={"AccumulationRegister_Остатки"},
        )
        == "AccumulationRegister_Остатки"
    )


def test_parse_odata_service_document_and_metadata() -> None:
    names = _names_from_service_document(
        {
            "value": [
                {"name": "Document_Проект", "url": "Document_Проект"},
                {"name": "Catalog_Контрагенты"},
                {"name": "InformationRegister_КурсыВалют"},
            ]
        }
    )
    assert names == [
        "Document_Проект",
        "Catalog_Контрагенты",
        "InformationRegister_КурсыВалют",
    ]
    xml = (
        '<edmx:Edmx><EntityContainer>'
        '<EntitySet Name="Document_Проект" EntityType="StandardODATA.Document_Проект"/>'
        '<EntitySet Name="AccumulationRegister_Остатки" EntityType="X"/>'
        "</EntityContainer></edmx:Edmx>"
    )
    assert _names_from_metadata_xml(xml) == [
        "Document_Проект",
        "AccumulationRegister_Остатки",
    ]


def test_normalize_odata_keeps_meeting_fields() -> None:
    from app.services.onec_tools import _normalize_odata_rows

    payload = {
        "odata.metadata": "meta",
        "value": [
            {
                "Ref_Key": "ac01f5f5-9ad9-11f1-9866-6cb31113810e",
                "Number": "000013155",
                "Date": "2026-08-18T10:51:00",
                "Posted": True,
                "ТемаСлужебнойЗаписки": "cad8df76-73cc-11ea-8341-ac1f6b05524d",
                "ТемаСовещания": "Планерка по проекту",
                "Инициатор": "Иванов",
                "Длительность": 60,
                "ФорматСовещания": "очно",
            }
        ],
    }

    rows = _normalize_odata_rows(payload)

    assert len(rows) == 1
    row = rows[0]
    assert row["Number"] == "000013155"
    assert row["Subject"] == "Планерка по проекту"
    assert row["ТемаСлужебнойЗаписки"] == "cad8df76-73cc-11ea-8341-ac1f6b05524d"
    assert row["ТемаСовещания"] == "Планерка по проекту"
    assert row["Инициатор"] == "Иванов"
    assert row["Длительность"] == 60
    assert row["ФорматСовещания"] == "очно"


def test_subject_prefers_memo_topic_over_meeting_title() -> None:
    from app.services.onec_tools import _catalog_entity_from_type, _normalize_odata_rows

    rows = _normalize_odata_rows(
        {
            "value": [
                {
                    "Ref_Key": "ac01f5f5-9ad9-11f1-9866-6cb31113810e",
                    "Number": "000013155",
                    "ТемаСлужебнойЗаписки": "Организация совещаний (регл.)",
                    "ТемаСовещания": "Тест, не создавайте совещание",
                }
            ]
        }
    )

    assert rows[0]["Subject"] == "Организация совещаний (регл.)"
    assert (
        _catalog_entity_from_type("StandardODATA.Catalog_ТД_ТемыСлужебныхЗаписок")
        == "Catalog_ТД_ТемыСлужебныхЗаписок"
    )


def test_normalize_odata_single_entity_without_value_array() -> None:
    from app.services.onec_tools import _entity_set_name, _normalize_odata_rows

    payload = {
        "Ref_Key": "ac01f5f5-9ad9-11f1-9866-6cb31113810e",
        "Number": "000013155",
        "Posted": True,
        "Тема": "Совещание",
    }

    rows = _normalize_odata_rows(payload)

    assert len(rows) == 1
    assert rows[0]["Subject"] == "Совещание"
    assert _entity_set_name("Document_ПланСовещания(guid'ac01f5f5-9ad9-11f1-9866-6cb31113810e')") == (
        "Document_ПланСовещания"
    )


def test_onec_unknown_tool() -> None:
    try:
        invoke_onec("onec.unknown", {})
        raise AssertionError("expected OnecToolError")
    except OnecToolError:
        pass


def test_meeting_service_notes_stub_without_odata(monkeypatch) -> None:
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: False)
    result = invoke_onec("onec.meeting_service_notes", {"date": "2026-08-19"})
    assert result["source"] == "stub"
    assert result["notes"] == []
    assert result["theme"] == "организация совещаний"


def test_meeting_service_notes_odata_handler(monkeypatch) -> None:
    from app.services import onec_tools as module

    theme_row = {
        "Ref_Key": "11111111-1111-1111-1111-111111111111",
        "Description": "организация совещаний",
    }
    note_row = {
        "Ref_Key": "22222222-2222-2222-2222-222222222222",
        "Number": "000013200",
        "Date": "2026-08-19T09:00:00",
        "ТемаСлужебнойЗаписки_Name": "организация совещаний",
        "ТемаСовещания": "Планерка ПСД",
        "МестоПроведенияСовещания_Name": "малый зал",
        "ЖелаемаяДатаПроведенияСовещания": "2026-08-19T00:00:00",
        "ДатаПроведенияСовещания": "2026-08-19T00:00:00",
        "ВремяНачалаСовещания": "2026-08-19T10:00:00",
        "ВремяОкончанияСовещания": "2026-08-19T11:00:00",
    }
    part_row = {"Участник_Name": "Жалыбин Максим Дмитриевич"}

    def fake_fetch(args: dict) -> dict:
        entity = str(args.get("entity") or "")
        if entity == "Catalog_ТД_ТемыСлужебныхЗаписок":
            return {"value": [theme_row], "path": entity}
        if entity == "Document_ТД_СлужебнаяЗаписка":
            return {"value": [note_row], "path": entity}
        if entity == "Document_ТД_СлужебнаяЗаписка_СписокУчастников":
            return {"value": [part_row], "path": entity}
        return {"value": [], "path": entity}

    monkeypatch.setattr(module, "_fetch_odata_list", fake_fetch)
    result = module._list_meeting_service_notes_odata({"date": "2026-08-19"})
    assert result["source"] == "odata"
    assert result["count"] == 1
    assert result["notes"][0]["number"] == "000013200"
    assert result["notes"][0]["meeting_topic"] == "Планерка ПСД"
    assert result["notes"][0]["participants"] == ["Жалыбин Максим Дмитриевич"]


def test_meeting_service_notes_odata_acl_error(monkeypatch) -> None:
    from app.services import onec_tools as module

    def boom(_args: dict) -> dict:
        raise OnecToolError("1C OData HTTP 401: Доступ запрещен")

    monkeypatch.setattr(module, "_meeting_theme_keys", lambda _args: [])
    monkeypatch.setattr(module, "_fetch_odata_list", boom)
    result = module._list_meeting_service_notes_odata({"date": "2026-08-19"})
    assert result["source"] == "odata"
    assert result["notes"] == []
    assert "401" in result["error"]
    assert result["entity"] == "Document_ТД_СлужебнаяЗаписка"


def test_meeting_theme_match() -> None:
    from app.services.onec_tools import _is_meeting_service_theme

    assert _is_meeting_service_theme("Организация совещаний")
    assert _is_meeting_service_theme("организац. совещаний")
    assert not _is_meeting_service_theme("командировка")
