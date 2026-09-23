"""Создание задачи в ДО: заготовка процесса по документу → заполнение → запуск."""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree as ET

import pytest

from app.services.docflow_create import handle_docflow_create
from app.services.docflow_tasks import DocflowError
from app.tools.onec import dok_create
from app.tools.onec.dok_soap import DokConfig, envelope

DM = "http://www.1c.ru/dm"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ME = {"name": "Мангасарян Давид Карленович", "id": "user-me", "type": "DMUser"}
COLLEAGUE = {"name": "Жалыбин Максим Дмитриевич", "id": "user-2", "type": "DMUser"}


def _new_process(process_type: str) -> ET.Element:
    return ET.fromstring(
        f'<m:object xmlns:m="{DM}" xmlns:xsi="{XSI}" xsi:type="m:{process_type}">'
        "<m:name>Исполнить Протокол ДР__062_О_427</m:name>"
        "<m:objectID><m:id></m:id><m:type>{0}</m:type></m:objectID>".format(process_type)
        + "<m:author><m:name>Мангасарян Давид Карленович</m:name>"
        "<m:objectID><m:id>user-me</m:id><m:type>DMUser</m:type></m:objectID></m:author>"
        "<m:importance><m:name>Обычная</m:name><m:objectID><m:id>imp</m:id>"
        "<m:type>DMBusinessProcessImportance</m:type></m:objectID></m:importance>"
        '<m:target xsi:type="m:DMInternalDocument"><m:name>Протокол ДР__062_О_427</m:name>'
        "<m:objectID><m:id>doc-1</m:id><m:type>DMInternalDocument</m:type></m:objectID></m:target>"
        "<m:description>из шаблона</m:description>"
        "<m:state><m:name>Активен</m:name><m:objectID><m:id>st</m:id>"
        "<m:type>DMBusinessProcessState</m:type></m:objectID></m:state>"
        "</m:object>"
    )


def _names(node: ET.Element) -> list[str]:
    return [child.tag.split("}")[-1] for child in node]


def test_performance_fields_follow_schema_order() -> None:
    node = _new_process("DMBusinessProcessPerformance")
    dok_create.fill_process(
        node,
        "DMBusinessProcessPerformance",
        title="Подготовить сводку по дашбордам",
        description="Сводка к пятнице",
        due=datetime(2026, 9, 25, 23, 59, 59),
        priority="high",
        performers=[{"user": COLLEAGUE, "due": None, "note": "черновик в понедельник"}, {"user": ME}],
        verifier=ME,
    )
    names = _names(node)
    assert names.index("description") < names.index("dueDate") < names.index("state")
    assert names.index("state") < names.index("verifier") < names.index("performers")
    assert node.findtext(f"{{{DM}}}dueDate") == "2026-09-25T23:59:59"
    assert node.findtext(f"{{{DM}}}name") == "Подготовить сводку по дашбордам"
    performers = node.findall(f"{{{DM}}}performers")
    assert [p.findtext(f"{{{DM}}}user/{{{DM}}}name") for p in performers] == [COLLEAGUE["name"], ME["name"]]
    assert [p.findtext(f"{{{DM}}}responsible") for p in performers] == ["true", "false"]
    first = _names(performers[0])
    # Порядок как в живом процессе ДО: personal* → responsible → user → срок.
    assert first[0] == "personalDueDate"
    assert first.index("personalTaskName") < first.index("responsible") < first.index("user")
    assert first.index("user") < first.index("dueDate")
    assert performers[0].findtext(f"{{{DM}}}personalDueDate") == "2026-09-25T23:59:59"
    assert performers[0].findtext(f"{{{DM}}}dueDate") == "2026-09-25T23:59:59"
    assert node.findtext(f"{{{DM}}}importance/{{{DM}}}objectID/{{{DM}}}id") == "Высокая"
    assert node.findtext(f"{{{DM}}}importance/{{{DM}}}name") == "Высокая важность"


def test_parse_due_keeps_time_and_defaults_to_end_of_day() -> None:
    assert dok_create.parse_due("2026-09-25T14:30") == datetime(2026, 9, 25, 14, 30)
    assert dok_create.parse_due("2026-09-25") == datetime(2026, 9, 25, 23, 59, 59)
    with pytest.raises(ValueError):
        dok_create.parse_due("2026-09-25T25:00")


def test_performer_template_keeps_structure_and_drops_old_task() -> None:
    template = ET.fromstring(
        f'<m:performers xmlns:m="{DM}" xmlns:xsi="{XSI}" xsi:type="m:DMBusinessProcessPerformanceParticipant">'
        "<m:user><m:name>Старый</m:name><m:objectID><m:id>old</m:id><m:type>DMUser</m:type></m:objectID></m:user>"
        "<m:personalDueDate>2026-01-01T00:00:00</m:personalDueDate>"
        "<m:personalDescription/><m:personalTaskName>старая</m:personalTaskName>"
        "<m:task><m:name>старая задача</m:name></m:task>"
        "<m:responsible>false</m:responsible>"
        "<m:performanceOrder><m:name>Параллельно</m:name></m:performanceOrder>"
        "<m:passed>true</m:passed>"
        "<m:dueDateSpecificationOption><m:name>Точный срок</m:name></m:dueDateSpecificationOption>"
        "<m:dueDate>2019-05-13T23:59:59</m:dueDate>"
        "</m:performers>"
    )
    node = dok_create.performance_participant(
        COLLEAGUE, due=None, note="", task_name="Новая", responsible=True, template=template
    )
    names = _names(node)
    assert "task" not in names and "passed" not in names and "dueDate" not in names
    assert names.index("performanceOrder") < names.index("user") < names.index("dueDateSpecificationOption")
    assert node.findtext(f"{{{DM}}}user/{{{DM}}}name") == COLLEAGUE["name"]
    assert node.findtext(f"{{{DM}}}personalTaskName") == "Новая"
    assert node.find(f"{{{DM}}}personalDueDate").get(f"{{{XSI}}}nil") == "true"


def test_launch_request_wraps_process_with_type(monkeypatch) -> None:
    sent: list[str] = []

    def fake_execute(_config, request_xml: str, *, timeout: float) -> ET.Element:
        sent.append(request_xml)
        return ET.fromstring(
            f'<r xmlns:m="{DM}"><m:businessProcess><m:name>Исполнение</m:name>'
            "<m:objectID><m:id>bp-1</m:id><m:type>DMBusinessProcessPerformance</m:type></m:objectID>"
            "<m:started>true</m:started></m:businessProcess></r>"
        )

    monkeypatch.setattr(dok_create, "execute_dm", fake_execute)
    monkeypatch.setattr(dok_create, "_save_debug", lambda *_args: None)
    node = _new_process("DMBusinessProcessAcquaintance")
    dok_create.fill_process(
        node, "DMBusinessProcessAcquaintance", title="Ознакомиться", description="", due=None,
        performers=[{"user": COLLEAGUE}],
    )
    config = DokConfig(server="h", port=81, user="u", password="p", timeout=30.0, base_path="/doc")
    result = dok_create.launch_business_process(config, node, timeout=10.0)
    assert result == {"id": "bp-1", "type": "DMBusinessProcessPerformance", "name": "Исполнение", "started": "true"}
    request = sent[0]
    assert 'xsi:type="dm:DMLaunchBusinessProcessRequest"' in request
    assert "<dm:businessProcess" in request and 'xsi:type="dm:DMBusinessProcessAcquaintance"' in request
    assert ET.fromstring(envelope(request)) is not None


def test_soap_fault_text_keeps_whole_reason() -> None:
    from app.tools.onec.dok_soap import soap_fault_text

    reason = "Чтение объекта типа: X " * 60 + "Проверка свойства 'personalTaskName': не заполнено"
    text = f"<soap:Envelope><soap:Body><soap:Fault><faultstring>{reason}</faultstring></soap:Fault></soap:Body></soap:Envelope>"
    assert soap_fault_text(text).endswith("Проверка свойства 'personalTaskName': не заполнено")


def test_consideration_takes_exactly_one_performer() -> None:
    node = _new_process("DMBusinessProcessConsideration")
    with pytest.raises(ValueError):
        dok_create.fill_process(
            node, "DMBusinessProcessConsideration", title="Рассмотреть", description="", due=None,
            performers=[{"user": ME}, {"user": COLLEAGUE}],
        )


def _service(monkeypatch, launched: list[ET.Element]) -> None:
    monkeypatch.setattr(
        "app.services.docflow_create.load_config",
        lambda **_kwargs: type("Cfg", (), {"timeout": 5})(),
    )
    monkeypatch.setattr(
        "app.services.docflow_create.find_user",
        lambda _config, fio: {"name": fio, "id": f"id:{fio}", "type": "DMUser"},
    )
    monkeypatch.setattr(
        "app.services.docflow_create.new_business_process",
        lambda _config, process_type, target, *, timeout: _new_process(process_type),
    )
    monkeypatch.setattr(
        "app.services.docflow_create.sample_performer",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("app.services.docflow_create.open_task_ids_by_step", lambda *_args, **_kwargs: [])

    def fake_launch(_config, node, *, timeout):
        launched.append(node)
        return {"id": "bp-9", "type": "x", "name": "n", "started": "true"}

    monkeypatch.setattr("app.services.docflow_create.launch_business_process", fake_launch)


def _launch_args(**extra) -> dict:
    base = {
        "action": "launch",
        "fio": ME["name"],
        "erp_password": "secret",
        "kind": "protocol",
        "process": "performance",
        "document": {"id": "doc-1", "type": "DMInternalDocument"},
        "title": "Подготовить сводку",
        "due": "2026-09-25",
        "performers": [{"fio": COLLEAGUE["name"]}],
        "confirm": True,
    }
    base.update(extra)
    return base


def test_launch_requires_explicit_confirm(monkeypatch) -> None:
    launched: list[ET.Element] = []
    _service(monkeypatch, launched)
    with pytest.raises(DocflowError, match="подтверждения"):
        handle_docflow_create(_launch_args(confirm=None))
    assert launched == []


def test_launch_rejects_process_not_used_for_document_kind(monkeypatch) -> None:
    launched: list[ET.Element] = []
    _service(monkeypatch, launched)
    with pytest.raises(DocflowError, match="не используется"):
        handle_docflow_create(_launch_args(kind="contract", process="acquaintance"))
    assert launched == []


def test_launch_performance_defaults_verifier_to_author(monkeypatch) -> None:
    launched: list[ET.Element] = []
    _service(monkeypatch, launched)
    result = handle_docflow_create(_launch_args())
    assert result["performers"] == [COLLEAGUE["name"]]
    node = launched[0]
    assert node.findtext(f"{{{DM}}}verifier/{{{DM}}}user/{{{DM}}}name") == ME["name"]
    assert node.findtext(f"{{{DM}}}performers/{{{DM}}}user/{{{DM}}}name") == COLLEAGUE["name"]
    # Единственного исполнителя ДО ответственным не принимает.
    assert node.findtext(f"{{{DM}}}performers/{{{DM}}}responsible") == "false"


def test_search_filters_by_author_and_query_locally(monkeypatch) -> None:
    def fake_execute(_config, request_xml: str, *, timeout: float) -> ET.Element:
        return ET.fromstring(
            f'<r xmlns:m="{DM}">'
            "<m:items><m:object><m:name>Протокол ДР__062_О_427</m:name>"
            "<m:objectID><m:id>d1</m:id><m:type>DMInternalDocument</m:type></m:objectID>"
            "<m:title>Совещание по дашбордам</m:title><m:regDate>2026-09-21T14:56:11</m:regDate>"
            f"<m:author><m:name>{ME['name']}</m:name></m:author></m:object></m:items>"
            "<m:items><m:object><m:name>Протокол ОД1_152</m:name>"
            "<m:objectID><m:id>d2</m:id><m:type>DMInternalDocument</m:type></m:objectID>"
            "<m:title>Совещание по дашбордам</m:title>"
            "<m:author><m:name>Донцова Анна Егоровна</m:name></m:author></m:object></m:items>"
            "<m:items><m:object><m:name>Протокол ДР__062_О_426</m:name>"
            "<m:objectID><m:id>d3</m:id><m:type>DMInternalDocument</m:type></m:objectID>"
            "<m:title>Бюджет</m:title>"
            f"<m:author><m:name>{ME['name']}</m:name></m:author></m:object></m:items>"
            "</r>"
        )

    monkeypatch.setattr(dok_create, "execute_dm", fake_execute)
    config = DokConfig(server="h", port=81, user="u", password="p", timeout=30.0, base_path="/doc")
    rows = dok_create.search_documents(
        config, "DMInternalDocument", document_type_id="t1", author=ME, query="дашборд", timeout=5.0
    )
    assert [row["id"] for row in rows] == ["d1"]
    assert rows[0]["reg_date"] == "2026-09-21"
