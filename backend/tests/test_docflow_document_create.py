from __future__ import annotations

from typing import Any

import pytest

from app.services import docflow_document_create as dc

ORG = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"
CONTRACTOR = "33333333-3333-3333-3333-333333333333"
CREATED = "44444444-4444-4444-4444-444444444444"
PARTNER = "12121212-1212-1212-1212-121212121212"


class FakeClient:
    def __init__(self) -> None:
        self.catalogs: dict[str, list[dict[str, Any]]] = {
            dc.ORGS: [{"Ref_Key": ORG, "Description": "НПО Турбулентность-ДОН"}],
            dc.USERS: [
                {"Ref_Key": USER, "Description": "Жалыбин Максим Дмитриевич"},
                {"Ref_Key": "55555555-5555-5555-5555-555555555555", "Description": "Жалыбина Анна"},
            ],
            dc.CONTRACTORS: [{"Ref_Key": CONTRACTOR, "Description": "ООО Ромашка", "Партнер_Key": PARTNER}],
            dc.PARTNERS: [{"Ref_Key": PARTNER, "Description": "Ромашка"}],
        }
        self.sample: dict[str, Any] = {
            "ТемаСлужебнойЗаписки": "x",
            "ТемаСлужебнойЗаписки_Type": "Edm.String",
            "ДокументОснование": "",
            "ДокументОснование_Type": "StandardODATA.Undefined",
        }
        self.posted: list[dict[str, Any]] = []
        self.files: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.stored: dict[str, dict[str, Any]] = {}
        self.delete_fails = False

    def get(self, entity: str, *, filt: str = "", top: int = 20, ref_key: str = "") -> list[dict[str, Any]]:
        if ref_key:
            if ref_key in self.stored:
                return [self.stored[ref_key]]
            return [row for row in self.catalogs.get(entity, []) if row["Ref_Key"] == ref_key]
        if entity.startswith("Document_"):
            return [self.sample]
        rows = self.catalogs.get(entity, [])
        if "substringof('" in filt:
            needle = filt.split("substringof('", 1)[1].split("'", 1)[0].casefold()
            rows = [row for row in rows if needle in row["Description"].casefold()]
        return rows[:top]

    def post(self, entity: str, body: dict[str, Any]) -> dict[str, Any]:
        if entity.startswith("Catalog_") and entity.endswith("ПрисоединенныеФайлы"):
            self.files.append(body)
            key = f"f{len(self.files):07d}-0000-0000-0000-000000000000"
            self.stored[key] = {**body, "Ref_Key": key}
            return self.stored[key]
        self.posted.append(body)
        row = {**body, "Ref_Key": CREATED, "Number": "ИСХ-0001"}
        self.stored[CREATED] = row
        return row

    def patch(self, entity: str, ref_key: str, body: dict[str, Any]) -> None:
        self.stored.setdefault(ref_key, {}).update(body)

    def delete(self, entity: str, ref_key: str) -> None:
        if self.delete_fails:
            raise RuntimeError("delete forbidden")
        self.deleted.append(ref_key)
        self.stored.pop(ref_key, None)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(dc, "_client", lambda kind, args: client)
    monkeypatch.setattr(dc, "_PROBES_PATH", tmp_path / "probes.json")
    return client


def _outgoing_values() -> dict[str, Any]:
    return {
        "Организация_Key": "Турбулентность",
        "ТемаСлужебнойЗаписки": "Ответ на запрос",
        "Контрагент_Key": "Ромашка",
        "Направление": "Коммерческий директор",
    }


def test_build_body_resolves_refs_and_composites(fake: FakeClient) -> None:
    body = dc.build_body(
        "outgoing",
        _outgoing_values(),
        client=fake,
        actor_fio="Жалыбин Максим Дмитриевич",
        sample=fake.sample,
    )
    assert body["Posted"] is False
    assert body["Организация_Key"] == ORG
    assert body["Контрагент_Key"] == CONTRACTOR
    assert body["Партнер_Key"] == PARTNER
    assert body["Ответственный_Key"] == USER
    assert body["Направление"] == "КоммерческийДиректор"
    assert body["Статус"] == "Подготовлен"
    assert body["ТемаСлужебнойЗаписки_Type"] == "Edm.String"
    assert body["ДокументОснование_Type"] == "StandardODATA.Undefined"
    assert body["ДокументОснование"] == ""


def test_build_body_requires_fields(fake: FakeClient) -> None:
    with pytest.raises(dc.DocumentCreateError, match="Тема"):
        dc.build_body("outgoing", {"Организация_Key": ORG}, client=fake, actor_fio="Жалыбин", sample={})


def test_build_body_unknown_ref_is_error(fake: FakeClient) -> None:
    values = {**_outgoing_values(), "Контрагент_Key": "Несуществующий"}
    with pytest.raises(dc.DocumentCreateError, match="не найдено"):
        dc.build_body("outgoing", values, client=fake, actor_fio="Жалыбин Максим Дмитриевич", sample={})


def test_partner_required_when_contractor_has_none(fake: FakeClient) -> None:
    fake.catalogs[dc.CONTRACTORS][0]["Партнер_Key"] = dc.EMPTY_GUID
    with pytest.raises(dc.DocumentCreateError, match="Партнёр"):
        dc.build_body("outgoing", _outgoing_values(), client=fake, actor_fio="Жалыбин Максим Дмитриевич", sample={})


def test_enum_rejects_foreign_value(fake: FakeClient) -> None:
    values = {**_outgoing_values(), "Направление": "Директор мира"}
    with pytest.raises(dc.DocumentCreateError, match="не из списка"):
        dc.build_body("outgoing", values, client=fake, actor_fio="Жалыбин Максим Дмитриевич", sample={})


def test_payment_gets_default_breakdown_row(fake: FakeClient) -> None:
    fake.catalogs.update(
        {
            "Catalog_Валюты": [{"Ref_Key": "66666666-6666-6666-6666-666666666666", "Description": "руб."}],
            "Catalog_СтатьиДвиженияДенежныхСредств": [
                {"Ref_Key": "77777777-7777-7777-7777-777777777777", "Description": "Оплата поставщикам"}
            ],
            "Catalog_ТД_ЦФО": [{"Ref_Key": "88888888-8888-8888-8888-888888888888", "Description": "ЦФО 1"}],
            dc.DEPARTMENTS: [{"Ref_Key": "99999999-9999-9999-9999-999999999999", "Description": "ОГК"}],
        }
    )
    body = dc.build_body(
        "payment",
        {
            "Организация_Key": ORG,
            "ХозяйственнаяОперация": "ОплатаПоставщику",
            "СуммаДокумента": "12 500,50",
            "ЖелательнаяДатаПлатежа": "2026-03-01",
            "СтатьяДвиженияДенежныхСредств_Key": "Оплата",
            "ТД_ЦФО_Key": "ЦФО 1",
            "Подразделение_Key": "ОГК",
            "НазначениеПлатежа": "Оплата по счёту 1",
        },
        client=fake,
        actor_fio="Жалыбин Максим Дмитриевич",
        sample={},
    )
    assert body["СуммаДокумента"] == 12500.5
    assert body["ЖелательнаяДатаПлатежа"] == "2026-03-01T00:00:00"
    assert body["ДатаПлатежа"] == "2026-03-01T00:00:00"
    assert body["ФормаОплатыБезналичная"] is True
    assert body["КтоЗаявил_Key"] == USER
    row = body["РасшифровкаПлатежа"][0]
    assert row["Сумма"] == 12500.5
    assert row["СтатьяДвиженияДенежныхСредств_Key"] == "77777777-7777-7777-7777-777777777777"


def test_probe_creates_reads_and_deletes(fake: FakeClient) -> None:
    result = dc.run_probe("outgoing", {}, actor_fio="Жалыбин Максим Дмитриевич")
    assert result["ok"] is True
    assert result["files"] is True
    assert dc.PROBE_MARK in fake.posted[0]["ТемаСлужебнойЗаписки"]
    assert fake.files[0]["ВладелецФайла_Key"] == CREATED
    file_key = "f0000001-0000-0000-0000-000000000000"
    assert fake.deleted == [file_key, CREATED]
    assert dc.probe_passed("outgoing", files=True)


def test_old_probe_without_files_is_rerun_for_files(fake: FakeClient) -> None:
    dc._remember_probe("outgoing", {"ok": True, "entity": "x"})
    assert dc.probe_passed("outgoing")
    assert not dc.probe_passed("outgoing", files=True)


def test_create_attaches_files(fake: FakeClient) -> None:
    import base64

    files = [{"name": "счёт.pdf", "base64": base64.b64encode(b"%PDF-1").decode()}]
    result = dc.create_document(
        "outgoing", {"values": _outgoing_values(), "files": files}, actor_fio="Жалыбин Максим Дмитриевич"
    )
    assert result["attached"] == ["счёт.pdf"]
    assert result["failed"] == []
    real_file = fake.files[-1]
    assert real_file["ВладелецФайла_Key"] == CREATED
    assert real_file["Description"] == "счёт"
    assert real_file["Расширение"] == "pdf"
    assert "Файлов прикреплено: 1" in result["summary"]


def test_files_rejected_for_docflow_base(fake: FakeClient) -> None:
    import base64

    files = [{"name": "a.txt", "base64": base64.b64encode(b"x").decode()}]
    with pytest.raises(dc.DocumentCreateError, match="в самой 1С"):
        dc.create_document("incentive", {"values": {}, "files": files}, actor_fio="Жалыбин")


def test_broken_file_rejected(fake: FakeClient) -> None:
    with pytest.raises(dc.DocumentCreateError, match="повреждён"):
        dc._decode_files([{"name": "a.txt", "base64": "@@@"}])


def test_probe_reports_left_test_when_delete_fails(fake: FakeClient) -> None:
    fake.delete_fails = True
    result = dc.run_probe("outgoing", {}, actor_fio="Жалыбин Максим Дмитриевич")
    assert result["ok"] is False
    assert result["test_left"] == CREATED
    assert not dc.probe_passed("outgoing")


def test_create_runs_probe_first_and_refuses_on_failure(fake: FakeClient) -> None:
    fake.delete_fails = True
    with pytest.raises(dc.DocumentCreateError, match="Проба записи"):
        dc.create_document("outgoing", {"values": _outgoing_values()}, actor_fio="Жалыбин Максим Дмитриевич")
    assert len(fake.posted) == 1


def test_create_after_probe(fake: FakeClient) -> None:
    result = dc.create_document("outgoing", {"values": _outgoing_values()}, actor_fio="Жалыбин Максим Дмитриевич")
    assert result["ok"] is True
    assert result["ref_key"] == CREATED
    assert result["number"] == "ИСХ-0001"
    assert "e1cib/data/" in result["web_url"] or result["web_url"] == ""
    assert len(fake.posted) == 2
    assert dc.PROBE_MARK not in fake.posted[1]["ТемаСлужебнойЗаписки"]


def test_lookup_only_form_catalogs(fake: FakeClient) -> None:
    found = dc.handle_docflow_document_create(
        {"action": "lookup", "kind": "outgoing", "catalog": dc.CONTRACTORS, "query": "ром"}
    )
    assert found["items"] == [{"key": CONTRACTOR, "name": "ООО Ромашка"}]
    with pytest.raises(dc.DocumentCreateError, match="не используется"):
        dc.handle_docflow_document_create({"action": "lookup", "kind": "outgoing", "catalog": "Catalog_Склады"})


def test_incentive_properties_go_to_additional_props(fake: FakeClient) -> None:
    fake.catalogs[dc._PROPERTY_CATALOG] = [
        {"Ref_Key": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "Description": "Депремируемый сотрудник"},
        {"Ref_Key": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "Description": "Процент депремирования"},
        {"Ref_Key": "cccccccc-cccc-cccc-cccc-cccccccccccc", "Description": "Период зарплаты"},
        {"Ref_Key": "dddddddd-dddd-dddd-dddd-dddddddddddd", "Description": "Не выполненная задача"},
        {"Ref_Key": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", "Description": "Утверждающий руководитель"},
    ]
    body = dc.build_body(
        "incentive",
        {
            "Заголовок": "О депремировании",
            "employee": "Жалыбин Максим",
            "percent": "10",
            "salary_period": "Март 2026",
            "task": "Не сдан отчёт",
            "approver": "Жалыбин Максим",
            "Организация_Key": ORG,
        },
        client=fake,
        actor_fio="Жалыбин Максим Дмитриевич",
        sample={},
    )
    assert body["ВидДокумента_Key"] == "0c0b6059-d4e6-11e7-8267-ac1f6b05524d"
    assert "Posted" not in body
    props = {row["Свойство_Key"][:2]: row for row in body["ДополнительныеРеквизиты"]}
    assert props["aa"]["Значение"] == USER
    assert props["aa"]["Значение_Type"] == "StandardODATA.Catalog_Пользователи"
    assert props["bb"]["Значение"] == 10


def test_schema_lists_all_kinds(fake: FakeClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dc, "_incoming_options", lambda: {"departments": [{"value": "1", "label": "УД"}]})
    result = dc.schema()
    ids = {kind["id"] for kind in result["kinds"]}
    assert ids == set(dc.KINDS)
    incoming = next(kind for kind in result["kinds"] if kind["id"] == "incoming")
    department = next(f for f in incoming["fields"] if f["key"] == "department_id")
    assert department["options"] == [{"value": "1", "label": "УД"}]
    assert department["side"] == "left"
    partner = next(f for f in incoming["fields"] if f["key"] == "partner")
    assert partner["side"] == "right"
    assert incoming["files"] is True
    incentive = next(kind for kind in result["kinds"] if kind["id"] == "incentive")
    assert incentive["files"] is False
    assert result["existing_forms"] == {"assignments": "assignment", "protocols": "protocol"}
