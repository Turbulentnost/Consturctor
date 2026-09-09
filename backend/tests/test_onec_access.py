"""Unit tests for 1C OData actor access checks."""

from __future__ import annotations

import pytest

from datetime import datetime

from app.services.onec_access import (
    OnecAccessDenied,
    OnecAccessProfile,
    _membership_expired,
    enforce_actor_access,
    filter_odata_result,
    odata_entity_candidates,
    odata_guid_to_sql_hex,
    sql_hex_to_odata_guid,
)
from app.services.onec_tools import OnecToolError, invoke_onec


def test_odata_entity_candidates_map_documents_and_tabular_parts() -> None:
    assert odata_entity_candidates("Document_ТД_ВходящаяКорреспонденция") == [
        "Документ.ТД_ВходящаяКорреспонденция",
        "Документ.ТД",
    ]
    assert odata_entity_candidates(
        "Document_ТД_ВходящаяКорреспонденция_Состав(guid'11111111-1111-1111-1111-111111111111')"
    ) == [
        "Документ.ТД_ВходящаяКорреспонденция_Состав",
        "Документ.ТД_ВходящаяКорреспонденция",
    ]
    assert odata_entity_candidates("Catalog_Контрагенты") == ["Справочник.Контрагенты"]
    assert odata_entity_candidates("InformationRegister_СведенияОФайлах") == [
        "РегистрСведений.СведенияОФайлах"
    ]


def test_empty_1c_sql_date_is_not_expired_membership() -> None:
    now = datetime(2026, 9, 8, 12, 0, 0)
    assert _membership_expired(datetime(2001, 1, 1), now) is False
    assert _membership_expired(datetime(1, 1, 1), now) is False
    assert _membership_expired(datetime(5999, 1, 1), now) is False
    assert _membership_expired(datetime(2020, 1, 1), now) is True
    assert _membership_expired(datetime(2027, 1, 1), now) is False


def test_guid_roundtrip_matches_erp_pm_binary() -> None:
    odata = "e98a8e40-6250-11e7-812d-001e67112509"
    sql_hex = odata_guid_to_sql_hex(odata)
    assert sql_hex == "812D001E6711250911E76250E98A8E40"
    assert sql_hex_to_odata_guid(sql_hex) == odata


def test_enforce_denies_missing_actor() -> None:
    with pytest.raises(OnecAccessDenied, match="нет текущего пользователя"):
        enforce_actor_access(action="read", entity="Document_X", user_id="", fio="")


def test_enforce_denies_entity_without_view_right(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = OnecAccessProfile(
        user_ref="37b39620-df12-11f0-9767-6cb31113810e",
        fio="Иванов",
        viewable=frozenset({"Документ.ЗаказКлиента"}),
        writable=frozenset(),
    )
    monkeypatch.setattr("app.services.onec_access.access_check_enabled", lambda: True)
    monkeypatch.setattr("app.services.onec_access.load_access_profile", lambda **_k: profile)
    with pytest.raises(OnecAccessDenied, match="нет права чтения"):
        enforce_actor_access(
            action="read",
            entity="Document_ТД_ВходящаяКорреспонденция",
            fio="Иванов",
        )
    assert (
        enforce_actor_access(action="read", entity="Document_ЗаказКлиента", fio="Иванов")
        is profile
    )


def test_enforce_write_and_sql_need_stronger_rights(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = OnecAccessProfile(
        user_ref="37b39620-df12-11f0-9767-6cb31113810e",
        fio="Иванов",
        viewable=frozenset({"Документ.ЗаказКлиента"}),
        writable=frozenset({"Документ.ЗаказКлиента"}),
    )
    monkeypatch.setattr("app.services.onec_access.access_check_enabled", lambda: True)
    monkeypatch.setattr("app.services.onec_access.load_access_profile", lambda **_k: profile)
    with pytest.raises(OnecAccessDenied, match="SQL"):
        enforce_actor_access(action="sql", entity="", fio="Иванов")
    assert (
        enforce_actor_access(action="write", entity="Document_ЗаказКлиента", fio="Иванов")
        is profile
    )
    admin = OnecAccessProfile(user_ref="x", fio="Админ", privileged=True)
    monkeypatch.setattr("app.services.onec_access.load_access_profile", lambda **_k: admin)
    assert enforce_actor_access(action="sql", entity="", fio="Админ").privileged


def test_filter_odata_result_hides_foreign_org_rows() -> None:
    allowed = "11111111-1111-1111-1111-111111111111"
    profile = OnecAccessProfile(
        user_ref="u",
        fio="Иванов",
        viewable=frozenset({"Документ.X"}),
        allowed_values=frozenset({allowed}),
        rls_restricted=True,
    )
    payload = {
        "entity": "Document_X",
        "value": [
            {"Ref_Key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "Организация_Key": allowed},
            {
                "Ref_Key": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "Организация_Key": "22222222-2222-2222-2222-222222222222",
            },
        ],
        "count": 2,
        "summary": "raw",
    }
    filtered = filter_odata_result(payload, profile, "Document_X")
    assert filtered["count"] == 1
    assert filtered["value"][0]["Организация_Key"] == allowed


def test_filter_protocol_denies_unrelated_employee() -> None:
    profile = OnecAccessProfile(
        user_ref="463c0539-07e3-11f1-979e-6cb31113810c",
        fio="Комарькова Анастасия Эдуардовна",
        viewable=frozenset({"Документ.ТД_Протокол"}),
        department_key="2094af18-de06-11ef-95fc-6cb31113810e",
        person_ref="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    row = {
        "Ref_Key": "8003225f-ab4c-11f1-987b-6cb31113810c",
        "Number": "СПГ_076_О_169",
        "Ответственный_Key": "d74eb491-063e-11e3-8c56-001e67112509",
        "Подразделение_Key": "bd7b5184-9f9c-11e4-80da-001e67112509",
        "ПрисутствующиеНаСовещании": [
            {"Участник_Key": "8d854bac-857f-11eb-856f-ac1f6b05524d"},
        ],
    }
    payload = {
        "path": "Document_ТД_Протокол(guid'8003225f-ab4c-11f1-987b-6cb31113810c')",
        "value": [row],
    }
    with pytest.raises(OnecAccessDenied, match="область данных"):
        filter_odata_result(payload, profile, "Document_ТД_Протокол")


def test_filter_protocol_keeps_attendee_and_same_department() -> None:
    attendee = "8d854bac-857f-11eb-856f-ac1f6b05524d"
    dept = "bd7b5184-9f9c-11e4-80da-001e67112509"
    row = {
        "Ref_Key": "8003225f-ab4c-11f1-987b-6cb31113810c",
        "Ответственный_Key": "d74eb491-063e-11e3-8c56-001e67112509",
        "Подразделение_Key": dept,
        "ПрисутствующиеНаСовещании": [{"Участник_Key": attendee}],
    }
    as_attendee = OnecAccessProfile(user_ref="u", fio="Шеин", person_ref=attendee)
    as_dept = OnecAccessProfile(user_ref="u", fio="Сотрудник", department_key=dept)
    kept = filter_odata_result({"value": [row]}, as_attendee, "Document_ТД_Протокол")
    assert kept["count"] == 1
    kept = filter_odata_result({"value": [row]}, as_dept, "Document_ТД_Протокол")
    assert kept["count"] == 1


def test_filter_odata_result_denies_keyed_foreign_row() -> None:
    profile = OnecAccessProfile(
        user_ref="u",
        fio="Иванов",
        allowed_values=frozenset({"11111111-1111-1111-1111-111111111111"}),
        rls_restricted=True,
    )
    payload = {
        "path": "Document_X(guid'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')",
        "value": [
            {
                "Ref_Key": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "Организация_Key": "22222222-2222-2222-2222-222222222222",
            }
        ],
    }
    with pytest.raises(OnecAccessDenied, match="область данных"):
        filter_odata_result(payload, profile, "Document_X")


def test_invoke_onec_stub_skips_access_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: False)
    monkeypatch.setattr("app.services.onec_tools._erp_sql_ready", lambda: False)
    result = invoke_onec(
        "onec.odata_get",
        {"entity": "Document_ТД_ВходящаяКорреспонденция", "top": 1},
    )
    assert result.get("source") == "stub"


def test_invoke_onec_real_get_denies_without_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(_args: dict) -> dict:
        return {"source": "odata", "value": [{"Ref_Key": "1"}]}

    monkeypatch.setattr("app.services.onec_tools.odata_configured", lambda: True)
    monkeypatch.setattr("app.services.onec_tools._erp_sql_ready", lambda: False)
    monkeypatch.setattr("app.services.docflow_tasks.docflow_configured", lambda: False)
    monkeypatch.setattr(
        "app.services.onec_tools.REAL_HANDLERS",
        {"onec.odata_get": fake_get},
    )
    with pytest.raises(OnecToolError, match="Доступ запрещен"):
        invoke_onec("onec.odata_get", {"entity": "Document_ЗаказКлиента"})
