from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.external_order import (
    ExternalOrder,
    ExternalOrderAudit,
    ExternalOrderBaseline,
    ExternalOrderCheck,
    ExternalOrderDecision,
    ExternalOrderDiff,
    ExternalOrderDocument,
    ExternalOrderFinding,
    ExternalOrderGap,
    ExternalOrderLine,
    ExternalOrderNotice,
    ExternalOrderRisk,
    ExternalOrderTask,
)
from app.services.external_order_matrix import evaluate_matrix, review_checklist
from app.services.external_order_strategy import link_strategy
from app.services.external_orders import (
    ExternalOrderError,
    accept_plan,
    add_baseline,
    add_decision,
    approve_order_file,
    close_conditions,
    confirm_check,
    create_order,
    delete_order_file,
    import_onec_order,
    import_tkp_order,
    is_zhalybin,
    link_onec,
    make_plan,
    patch_order,
    propose,
    publish_order_plan,
    resolve_role,
    transition,
    upload_order_file,
)


def _db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            ExternalOrder.__table__,
            ExternalOrderCheck.__table__,
            ExternalOrderDiff.__table__,
            ExternalOrderRisk.__table__,
            ExternalOrderDecision.__table__,
            ExternalOrderFinding.__table__,
            ExternalOrderDocument.__table__,
            ExternalOrderAudit.__table__,
            ExternalOrderGap.__table__,
            ExternalOrderBaseline.__table__,
            ExternalOrderTask.__table__,
            ExternalOrderLine.__table__,
            ExternalOrderNotice.__table__,
        ],
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _create(db):
    return create_order(
        db,
        role="ks",
        fio="Ильченко Екатерина Александровна",
        fields={"customer": "Заказчик", "product": "Расходомер"},
    )


def test_final_tkp_blocked_without_committee_protocol():
    db = _db()
    order = _create(db)
    try:
        transition(db, order["id"], role="ks", fio="Ильченко", target="tkp_issued")
    except ExternalOrderError as exc:
        assert exc.status == 409
        assert "протокола" in exc.detail
    else:
        raise AssertionError("ТКП выпустилось без протокола")


def test_tkp_after_committee_protocol():
    db = _db()
    order = _create(db)
    add_decision(
        db,
        order["id"],
        role="committee",
        fio="Секретарь",
        fields={"decision": "confirmed", "protocol": "ПР-1", "base_version": "БВ-1"},
    )
    issued = transition(db, order["id"], role="ks", fio="Ильченко", target="tkp_issued")
    assert issued["status"] == "tkp_issued"


def test_ks_cannot_confirm_legal_checklist():
    db = _db()
    order = _create(db)
    legal = next(item for item in order["checks"] if item["owner_role"] == "legal")
    try:
        confirm_check(db, order["id"], legal["id"], role="ks", fio="Ильченко", evidence="согласовано")
    except ExternalOrderError as exc:
        assert exc.status == 403
        assert "чужой" in exc.detail
    else:
        raise AssertionError("КС подтвердила юридический пункт")


def test_onec_link_sets_payment_and_blocks_partial_close(monkeypatch):
    def fake_read(ref_key: str) -> dict:
        return {
            "order_key": ref_key,
            "order_number": "ЗК-1",
            "order_date": "2026-10-01",
            "amount": "1000.00",
            "paid": "250.00",
            "payment_percent": "25",
            "counterparty_key": "c1",
            "counterparty": "ООО Ромашка",
            "inn": "7700000000",
            "contract_key": "d1",
            "contract": "Д-1",
        }

    monkeypatch.setattr("app.services.external_order_onec.read_order", fake_read)
    monkeypatch.setattr("app.services.external_order_onec.tkp_key_for_order", lambda _key: "")
    db = _db()
    order = _create(db)
    linked = link_onec(db, order["id"], role="ks", fio="Ильченко", ref_key="11111111-1111-1111-1111-111111111111")
    assert linked["customer"] == "ООО Ромашка"
    assert linked["payment_percent"] == 25
    assert "ЗК-1" in linked["payment_note"]
    try:
        transition(db, order["id"], role="rp", fio="РП", target="closed")
    except ExternalOrderError as exc:
        assert exc.status == 409
        assert "100%" in exc.detail
    else:
        raise AssertionError("частичная оплата из 1С закрыла заказ")


def test_rp_cannot_link_onec_order():
    db = _db()
    order = _create(db)
    try:
        link_onec(db, order["id"], role="rp", fio="РП", ref_key="11111111-1111-1111-1111-111111111111")
    except ExternalOrderError as exc:
        assert exc.status == 403
    else:
        raise AssertionError("РП привязал заказ 1С")


def test_close_blocked_without_full_payment():
    db = _db()
    order = _create(db)
    try:
        transition(db, order["id"], role="rp", fio="РП", target="closed")
    except ExternalOrderError as exc:
        assert exc.status == 409
        assert "100%" in exc.detail
    else:
        raise AssertionError("заказ закрылся без оплаты")


def test_sign_blocked_by_open_difference():
    db = _db()
    order = _create(db)
    try:
        transition(db, order["id"], role="ks", fio="Ильченко", target="contract_signed")
    except ExternalOrderError as exc:
        assert exc.status == 409
        assert "расхождение" in exc.detail
    else:
        raise AssertionError("договор подписан при открытом расхождении")


def test_rp_cannot_change_price():
    db = _db()
    order = _create(db)
    try:
        patch_order(
            db,
            order["id"],
            role="rp",
            fio="РП",
            fields={"sections": {"commercial": {"price": "100"}}},
        )
    except ExternalOrderError as exc:
        assert exc.status == 403
        assert "цену" in exc.detail
    else:
        raise AssertionError("РП изменил цену")


def test_only_zhalybin_can_switch_role():
    assert is_zhalybin("Жалыбин Максим Дмитриевич")
    assert not is_zhalybin("Жалыбин Пётр Иванович")
    switched = resolve_role(
        fio="Жалыбин Максим Дмитриевич",
        position="Инженер",
        department="",
        as_role="committee",
    )
    assert switched == "committee"
    ignored = resolve_role(
        fio="Ильченко Екатерина Александровна",
        position="Помощник Председателя совета директоров",
        department="",
        as_role="committee",
    )
    assert ignored != "committee"


def _docx(paragraphs: list[str]) -> str:
    import base64
    import io
    import zipfile

    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("word/document.xml", xml)
    return base64.b64encode(buffer.getvalue()).decode()


def test_ready_for_committee_blocked_by_open_check():
    db = _db()
    order = _create(db)
    try:
        transition(db, order["id"], role="development", fio="Развитие", target="ready_committee")
    except ExternalOrderError as exc:
        assert exc.status == 409
        assert "Комитету" in exc.detail
    else:
        raise AssertionError("переход прошёл при открытом пункте")


def test_finding_without_location_becomes_gap():
    db = _db()
    order = _create(db)
    body = propose(
        db,
        order["id"],
        fio="агент",
        findings=[{"field": "price", "value": "100", "source_ref": "договор.docx", "owner_role": "finance"}],
        diffs=[],
    )
    assert body["findings"] == []
    assert any(item["field"] == "price" for item in body["gaps"])


def test_approved_file_cannot_be_deleted_and_duplicate_is_rejected():
    db = _db()
    order = _create(db)
    payload = {"kind": "contract", "filename": "dogovor.docx", "content_base64": _docx(["Цена 100 руб."])}
    saved = upload_order_file(db, order["id"], role="ks", fio="Ильченко", fields=payload)
    document = saved["documents"][0]
    assert any(item["location"].startswith("абзац") for item in saved["findings"])
    approved = approve_order_file(db, order["id"], document["id"], role="ks", fio="Ильченко")
    try:
        delete_order_file(db, order["id"], document["id"], role="ks", fio="Ильченко")
    except ExternalOrderError as exc:
        assert exc.status == 409
        assert "Утвержд" in exc.detail
    else:
        raise AssertionError("утверждённый файл удалился")
    try:
        upload_order_file(db, order["id"], role="ks", fio="Ильченко", fields=payload)
    except ExternalOrderError as exc:
        assert exc.status == 409
    else:
        raise AssertionError("дубль файла принят")
    assert approved["documents"][0]["approved"] is True


def test_condition_without_owner_document_is_rejected():
    db = _db()
    order = _create(db)
    decided = add_decision(
        db,
        order["id"],
        role="committee",
        fio="Секретарь",
        fields={"decision": "confirmed_conditions", "protocol": "ПР-2", "base_version": "БВ-1", "conditions": "закрыть цену"},
    )
    decision_id = decided["decisions"][0]["id"]
    try:
        close_conditions(db, order["id"], decision_id, role="committee", fio="Секретарь", document_id="")
    except ExternalOrderError as exc:
        assert exc.status == 409
        assert "владельца" in exc.detail
    else:
        raise AssertionError("условие закрылось без документа")
    uploaded = upload_order_file(
        db,
        order["id"],
        role="finance",
        fio="Финансы",
        fields={"kind": "condition", "filename": "zakl.docx", "content_base64": _docx(["Цена подтверждена"])},
    )
    document_id = next(item["id"] for item in uploaded["documents"] if item["kind"] == "condition")
    closed = close_conditions(
        db, order["id"], decision_id, role="committee", fio="Секретарь", document_id=document_id
    )
    assert closed["decisions"][0]["conditions_closed"] is True


def test_new_baseline_after_protocol_needs_reason_and_plan_is_not_copied():
    db = _db()
    order = _create(db)
    fields = {
        "composition": "насос",
        "cost": "100",
        "mcr": "80",
        "margin": "20",
        "bdds": "аванс 50",
        "deadlines": "120 дней",
    }
    first = add_baseline(db, order["id"], role="finance", fio="Финансы", fields=fields)
    baseline_id = first["baselines"][0]["id"]
    add_decision(
        db,
        order["id"],
        role="committee",
        fio="Секретарь",
        fields={"decision": "confirmed", "protocol": "ПР-3", "baseline_id": baseline_id},
    )
    try:
        add_baseline(db, order["id"], role="finance", fio="Финансы", fields=fields)
    except ExternalOrderError as exc:
        assert exc.status == 400
        assert "основан" in exc.detail
    else:
        raise AssertionError("версия без основания принята")
    planned = make_plan(db, order["id"], role="rp", fio="РП")
    count = len(planned["tasks"])
    again = make_plan(db, order["id"], role="rp", fio="РП")
    assert len(again["tasks"]) == count
    accept_plan(db, order["id"], role="rp", fio="РП")
    publish_order_plan(db, order["id"], role="rp", fio="РП")
    try:
        publish_order_plan(db, order["id"], role="rp", fio="РП")
    except ExternalOrderError as exc:
        assert exc.status == 409
        assert "копи" in exc.detail
    else:
        raise AssertionError("повторная публикация создала задачи")


def test_new_specification_after_decision_opens_repeat_conclusions():
    db = _db()
    order = _create(db)
    add_decision(
        db,
        order["id"],
        role="committee",
        fio="Секретарь",
        fields={"decision": "confirmed", "protocol": "ПР-4", "base_version": "БВ-9"},
    )
    changed = upload_order_file(
        db,
        order["id"],
        role="ks",
        fio="Ильченко",
        fields={"kind": "specification", "filename": "spec.docx", "content_base64": _docx(["Цена 200"])},
    )
    assert any(item["kind"] == "change" for item in changed["notices"])
    assert any(item["field"].startswith("повтор") for item in changed["gaps"])


def test_import_onec_puts_order_on_request_stage_once(monkeypatch):
    def fake_read(ref_key: str) -> dict:
        return {
            "order_key": ref_key,
            "order_number": "ЗК-9",
            "order_date": "2026-10-02",
            "amount": "500.00",
            "paid": "0.00",
            "payment_percent": "0",
            "counterparty_key": "c1",
            "counterparty": "ООО Ромашка",
            "inn": "7700000000",
            "contract_key": "",
            "contract": "",
        }

    monkeypatch.setattr("app.services.external_order_onec.read_order", fake_read)
    monkeypatch.setattr("app.services.external_order_onec.tkp_key_for_order", lambda _key: "")
    db = _db()
    key = "11111111-1111-1111-1111-111111111111"
    first = import_onec_order(db, role="it", fio="Жалыбин", ref_key=key)
    assert first["customer"] == "ООО Ромашка"
    assert first["stage_label"] == "Запрос"
    assert first["onec_number"] == "ЗК-9"
    second = import_onec_order(db, role="ks", fio="Ильченко", ref_key=key)
    assert second["id"] == first["id"]
    assert db.query(ExternalOrder).count() == 1


def test_import_tkp_reflects_path_and_does_not_duplicate(monkeypatch):
    def fake_trace(ref_key: str) -> dict:
        return {
            "tkp_key": ref_key,
            "tkp_number": "НП00-003564",
            "tkp_status": "Согласовано",
            "tkp_status_label": "Согласовано",
            "comment": "ГРС",
            "order_key": "aabb8097-84c3-11f1-9848-6cb31113810e",
            "order_number": "НП00-001686",
            "order_date": "2026-10-20",
            "order_status": "К обеспечению",
            "amount": "1.00",
            "paid": "0.00",
            "payment_percent": "0",
            "counterparty_key": "c1",
            "counterparty": "Заказчик пути",
            "inn": "0277014204",
            "contract_key": "d1",
            "contract": "Договор поставки",
            "contract_number": "МПГ00000000",
            "path": (
                '[{"id":"tkp","title":"ТКП","state":"done","detail":"НП00-003564 · Согласовано"},'
                '{"id":"shipment","title":"Отгрузка","state":"done","detail":"НП00-001686, Отгружено"},'
                '{"id":"payment","title":"Оплата","state":"current","detail":"0% по поступлениям заказа"}]'
            ),
            "suggested_stage": "payment",
            "suggested_status": "awaiting_payment",
        }

    monkeypatch.setattr("app.services.external_order_onec.trace_tkp", fake_trace)
    db = _db()
    key = "15496a03-7956-4a03-8e57-3192c20f1808"
    first = import_tkp_order(db, role="ks", fio="Ильченко", ref_key=key)
    assert first["customer"] == "Заказчик пути"
    assert first["stage"] == "payment"
    assert first["status"] == "awaiting_payment"
    assert "ТКП: НП00-003564" in first["path_label"]
    assert "Отгрузка: НП00-001686, Отгружено" in first["path_label"]
    second = import_tkp_order(db, role="it", fio="Жалыбин", ref_key=key)
    assert second["id"] == first["id"]
    assert db.query(ExternalOrder).count() == 1


def test_strategy_link_stores_turboproject_without_writing_tasks(monkeypatch):
    def fake_search(args):
        assert "Путь" in str(args.get("query") or "")
        return {
            "projects": [
                {
                    "file_id": "file-1",
                    "project_name": "ГРС Путь Ленина",
                    "owner": "РП",
                    "customer": "Заказчик",
                    "dates": {"start_date": "2026-09-01", "finish_date": "2026-12-01", "baseline_finish": "2026-11-15"},
                    "data_1c": {"nomer_proekta": "ПР-1", "status_proekta": "В работе"},
                }
            ]
        }

    monkeypatch.setattr("app.services.turboproject.search_projects", fake_search)
    db = _db()
    order = _create(db)
    row = db.get(ExternalOrder, order["id"])
    row.customer = "Заказчик"
    row.sections_json = '{"onec": {"deal_name": "Сделка / ГРС Путь Ленина", "order_number": "НП00-001000"}}'
    db.commit()
    linked = link_strategy(db, order["id"], role="rp", fio="РП")
    strategy = linked["sections"]["strategy"]
    assert strategy["file_id"] == "file-1"
    assert strategy["finish_date"] == "2026-12-01"
    assert "не записываются" in strategy["note"]


def test_matrix_marks_linked_turboproject_plan():
    matrix = evaluate_matrix(
        {
            "code": "ВЗ-0001",
            "sections": {"strategy": {"file_id": "file-1", "project_name": "ГРС Путь Ленина"}},
            "checks": [],
            "diffs": [],
            "documents": [],
            "findings": [],
            "risks": [],
            "decisions": [],
            "baselines": [],
            "tasks": [],
            "lines": [],
            "notices": [],
            "gaps": [],
            "audit": [],
            "blocks": [],
        }
    )
    row = next(item for item in matrix["rows"] if item["id"] == "FR-013")
    assert row["state"] == "done"


def test_matrix_and_checklist_review_use_the_case():
    db = _db()
    order = _create(db)
    matrix = evaluate_matrix(order)
    by_id = {row["id"]: row for row in matrix["rows"]}
    assert len(matrix["rows"]) == 50
    assert by_id["FR-001"]["state"] == "done"
    assert by_id["FR-013"]["state"] in {"out", "wait"}
    assert by_id["FR-009"]["state"] == "gap"
    review = review_checklist(order)
    assert any(item["verdict"] == "wait" for item in review["checks"])
    assert any(item["code"] == "B05" and item["verdict"] == "gap" for item in review["diffs"])
    assert "B05" in review["prompt"]


def test_rp_cannot_import_onec_order():
    db = _db()
    try:
        import_onec_order(db, role="rp", fio="РП", ref_key="11111111-1111-1111-1111-111111111111")
    except ExternalOrderError as exc:
        assert exc.status == 403
    else:
        raise AssertionError("РП загрузил заказ из 1С")
