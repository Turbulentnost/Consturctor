from __future__ import annotations

import pytest

from app.services import docflow_document_create as dc
from app.services import docflow_service_requests as sr


class _Client:
    def __init__(self) -> None:
        self.catalogs: dict[str, list[dict]] = {}

    def get(self, entity: str, *, filt: str = "", top: int = 20, ref_key: str = "") -> list[dict]:
        del filt, top
        rows = self.catalogs.get(entity, [])
        if ref_key:
            return [row for row in rows if row.get("Ref_Key") == ref_key]
        return rows

EMPTY = sr.EMPTY_GUID
ROOT = "11111111-1111-1111-1111-111111111111"
FOLDER = "22222222-2222-2222-2222-222222222222"
LEAF = "33333333-3333-3333-3333-333333333333"
TOP = "44444444-4444-4444-4444-444444444444"
AHO_LEAF = "55555555-5555-5555-5555-555555555555"
ORG = "66666666-6666-6666-6666-666666666666"
DEPT = "77777777-7777-7777-7777-777777777777"
BUILDING = "88888888-8888-8888-8888-888888888888"
USER = "99999999-9999-9999-9999-999999999999"


def _tree() -> list[dict]:
    return [
        {"Ref_Key": ROOT, "Description": "Отдел IT", "Parent_Key": EMPTY, "IsFolder": True, "Подразделение_Key": EMPTY},
        {
            "Ref_Key": FOLDER,
            "Description": "Рабочее место",
            "Parent_Key": ROOT,
            "IsFolder": True,
            "Подразделение_Key": sr.IT_DEPARTMENT,
        },
        {
            "Ref_Key": LEAF,
            "Description": "Новое",
            "Parent_Key": FOLDER,
            "IsFolder": False,
            "Подразделение_Key": sr.IT_DEPARTMENT,
        },
        {
            "Ref_Key": TOP,
            "Description": "ВКС",
            "Parent_Key": EMPTY,
            "IsFolder": False,
            "Подразделение_Key": sr.IT_DEPARTMENT,
        },
        {
            "Ref_Key": AHO_LEAF,
            "Description": "Уборка",
            "Parent_Key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "IsFolder": False,
            "Подразделение_Key": EMPTY,
        },
        {
            "Ref_Key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "Description": "Разнорабочий (Эксплутационная служба)",
            "Parent_Key": EMPTY,
            "IsFolder": True,
            "Подразделение_Key": EMPTY,
        },
    ]


def test_leaves_follow_the_service_root_and_top_level_department() -> None:
    it = sr.leaves_for("service_it", _tree())
    assert {item["value"] for item in it} == {LEAF, TOP}
    assert next(item["label"] for item in it if item["value"] == LEAF) == "Рабочее место → Новое"
    aho = sr.leaves_for("service_aho", _tree())
    assert aho == [{"value": AHO_LEAF, "label": "Уборка"}]


@pytest.fixture
def fake_client() -> _Client:
    return _Client()


def test_aho_request_takes_executor_from_fallback(fake_client: _Client) -> None:
    kind = AHO_LEAF
    fake_client.catalogs[sr.KIND_CATALOG] = [{"Ref_Key": kind, "Description": "Уборка", "Подразделение_Key": EMPTY}]
    fake_client.catalogs[dc.USERS] = [{"Ref_Key": USER, "Description": "Жалыбин Максим Дмитриевич"}]
    body = dc.build_body(
        "service_aho",
        {
            "ВидЗаявки_Key": kind,
            "Организация_Key": ORG,
            "Подразделение_Key": DEPT,
            "Здание_Key": BUILDING,
            "ТелефонОбратнойСвязи": "101",
        },
        client=fake_client,
        actor_fio="Жалыбин Максим Дмитриевич",
        sample={},
    )
    assert body["Статус"] == "Подготовлен"
    assert body["Posted"] is False
    assert body["ПодразделениеИсполнитель_Key"] == sr.AHO_DEPARTMENT
    assert body["Ответственный_Key"] == USER


def test_nomenclature_market_and_pr_are_their_own_journals() -> None:
    nomenclature = sr.service_spec("service_nomenclature")
    market = sr.service_spec("service_market")
    pr = sr.service_spec("service_pr")
    assert nomenclature["entity"] == "Document_ТД_ЗаявкаНаСозданиеНоменклатуры"
    assert nomenclature["all_documents"] is True
    assert market["entity"] == "Document_ТД_ЗаявкаОПотребностиРынка"
    assert pr["entity"] == "Document_ТД_ЗаявкаВСекторРекламыИPR"
    assert dc.KINDS["service_nomenclature"]["entity"] == nomenclature["entity"]
    assert dc.KINDS["service_market"]["defaults"]["Статус"] == "ПоставленаВПлан"
    assert dc.FILE_CATALOGS["service_pr"].endswith("ИPRПрисоединенныеФайлы")
    row = sr._row_view(
        {
            "Ref_Key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "Number": "1",
            "Статус": "ПоставленаВПлан",
            "Наименование": "Датчик",
            "Категория": {"Description": "КИП"},
            "Партнер": {"Description": "Завод"},
        },
        technical=False,
        form_kind="service_market",
    )
    assert row["text"] == "Датчик"
    assert row["kind"] == "КИП"
    assert row["organization"] == "Завод"
    assert row["status"] == "Поставлена в план"
    assert row["document_type"] == "Заявка о потребности рынка"


def test_it_request_takes_executor_from_the_kind(fake_client: _Client) -> None:
    fake_client.catalogs[sr.KIND_CATALOG] = [
        {"Ref_Key": LEAF, "Description": "Новое", "Подразделение_Key": sr.IT_DEPARTMENT}
    ]
    fake_client.catalogs[dc.USERS] = [{"Ref_Key": USER, "Description": "Жалыбин Максим Дмитриевич"}]
    body = dc.build_body(
        "service_it",
        {
            "ВидЗаявки_Key": LEAF,
            "Организация_Key": ORG,
            "Подразделение_Key": DEPT,
            "Содержание": "Замена картриджа",
            "ТелефонОбратнойСвязи": "101",
        },
        client=fake_client,
        actor_fio="Жалыбин Максим Дмитриевич",
        sample={},
    )
    assert body["ПодразделениеИсполнитель_Key"] == sr.IT_DEPARTMENT
