"""Файлы дела, извлечение, план, базовая версия и уведомления внешнего заказа.

Вывод без места в источнике не сохраняется. Утверждённый файл не удаляется.
Публикация плана не создаёт вторую копию задач.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.models.external_order import (
    ExternalOrder,
    ExternalOrderBaseline,
    ExternalOrderDocument,
    ExternalOrderGap,
    ExternalOrderLine,
    ExternalOrderNotice,
    ExternalOrderTask,
)

_ALLOWED = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".pdf": "application/pdf"}
_KINDS = {"tz", "tkp", "contract", "specification", "protocol", "condition", "acceptance", "other"}
_UPLOAD_ROLES = {"ks", "development", "rp", "legal", "kb", "finance", "omto", "production", "committee"}
_BLOCK_GATES = {"before_calc", "before_committee", "before_project", "before_production", "before_ship"}
_FIELDS = (
    ("subject", "предмет", "B02", "ks"),
    ("price", "цена", "B05", "finance"),
    ("vat", "ндс", "B06", "finance"),
    ("term", "срок", "B09", "rp"),
    ("payment", "оплат", "B13", "finance"),
    ("acceptance", "приемк", "B17", "production"),
    ("warranty", "гаранти", "B22", "legal"),
    ("sanctions", "санкц", "B24", "legal"),
)
_PLAN = (
    ("Уточнение требований", "stage", "ks"),
    ("Расчёт", "stage", "finance"),
    ("Договор", "milestone", "ks"),
    ("КД", "stage", "kb"),
    ("Закупки", "stage", "omto"),
    ("Изготовление", "stage", "production"),
    ("Испытания", "milestone", "production"),
    ("Приёмка", "milestone", "ks"),
    ("Отгрузка", "milestone", "omto"),
    ("Оплата и закрытие", "milestone", "finance"),
)
_REPEAT = ("kb", "omto", "finance", "production", "legal")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def check_seed(gate: str, route: str, order_type: str, text: str) -> dict:
    applies, reason = _applies(route, order_type, gate, text)
    days = 2 if route == "accelerated" else 5
    return {
        "status": "not_applicable" if not applies else "not_started",
        "evidence": reason if not applies else "",
        "blocking": gate in _BLOCK_GATES and applies,
        "due_at": None if not applies else datetime.now(timezone.utc) + timedelta(days=days),
    }


def retarget_checks(order: ExternalOrder) -> None:
    for item in order.checks:
        if item.status == "done":
            continue
        applies, reason = _applies(order.route, order.order_type, item.gate, item.text)
        if not applies:
            item.status = "not_applicable"
            item.evidence = reason
            item.blocking = False
        elif item.status == "not_applicable":
            item.status = "not_started"
            item.evidence = ""
            item.blocking = item.gate in _BLOCK_GATES
            if item.due_at is None:
                item.due_at = datetime.now(timezone.utc) + timedelta(days=5)


def _applies(route: str, order_type: str, gate: str, text: str) -> tuple[bool, str]:
    folded = (order_type or "").casefold().replace("ё", "е")
    if route == "simplified" and gate not in {"before_calc", "before_sign", "before_close"}:
        return False, "упрощённый маршрут"
    if route == "accelerated" and gate == "before_psi":
        return False, "ускоренный маршрут"
    if gate == "before_psi" and "без пси" in folded:
        return False, "тип заказа без ПСИ"
    lowered = text.casefold().replace("ё", "е")
    if ("смр" in lowered or "пнр" in lowered) and "смр" not in folded and "пнр" not in folded:
        return False, "в типе заказа нет СМР и ПНР"
    return True, ""


def open_gate(order: ExternalOrder, gates: set[str]) -> str | None:
    for item in order.checks:
        if item.gate not in gates or item.status in {"done", "not_applicable"}:
            continue
        return item.text
    return None


def add_gap(db: Session, order: ExternalOrder, *, field: str, owner_role: str, detail: str, hours: int = 48) -> None:
    db.add(
        ExternalOrderGap(
            id=_new_id(),
            order_id=order.id,
            field=field[:128],
            owner_role=owner_role or "ks",
            due_at=datetime.now(timezone.utc) + timedelta(hours=hours),
            status="open",
            detail=detail,
        )
    )


def notify(db: Session, order: ExternalOrder, *, kind: str, role: str, title: str, body: str) -> None:
    owners = {}
    try:
        import json

        owners = json.loads(order.owners_json or "{}")
    except json.JSONDecodeError:
        owners = {}
    mail = str((owners or {}).get(f"{role}_email") or "").strip()
    db.add(
        ExternalOrderNotice(
            id=_new_id(),
            order_id=order.id,
            kind=kind,
            role=role,
            title=title[:256],
            body=body,
            mail_status=f"почта: {mail}" if mail else "карточка: у роли нет почтового адреса",
        )
    )


def store_file(
    db: Session,
    order: ExternalOrder,
    *,
    role: str,
    fio: str,
    kind: str,
    filename: str,
    content_b64: str,
) -> ExternalOrderDocument:
    from app.services.external_orders import ExternalOrderError, _audit

    if role not in _UPLOAD_ROLES:
        raise ExternalOrderError("Файл в дело кладёт участник маршрута", 403)
    if role == "committee" and kind != "protocol":
        raise ExternalOrderError("Комитет прикладывает только протокол", 403)
    suffix = Path(filename or "").suffix.casefold()
    if suffix not in _ALLOWED:
        raise ExternalOrderError("В дело принимаются DOCX, XLSX и PDF", 400)
    if kind not in _KINDS:
        raise ExternalOrderError("Неизвестный вид документа", 400)
    try:
        raw = base64.b64decode(content_b64 or "", validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ExternalOrderError("Файл не прочитан", 400) from exc
    if not raw or len(raw) > 12_000_000:
        raise ExternalOrderError("Файл пустой или больше 12 МБ", 400)
    digest = hashlib.sha256(raw).hexdigest()
    if any(item.sha256 == digest for item in order.documents):
        raise ExternalOrderError("Такой файл уже есть в деле", 409)
    same = [item for item in order.documents if item.kind == kind]
    version = f"v{len(same) + 1}"
    doc_id = _new_id()
    folder = BACKEND_ROOT / "storage" / "external_orders" / order.id
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", Path(filename).name)[:180] or f"file{suffix}"
    path = folder / f"{doc_id}_{safe}"
    path.write_bytes(raw)
    title = Path(filename).stem or kind
    doc = ExternalOrderDocument(
        id=doc_id,
        order_id=order.id,
        kind=kind,
        title=title,
        version=version,
        file_name=safe,
        stored_path=str(path),
        mime=_ALLOWED[suffix],
        sha256=digest,
        owner_role=role,
    )
    db.add(doc)
    db.flush()
    _extract(db, order, doc, raw, suffix)
    if kind == "specification" and _has_committee(order):
        _material_change(db, order, doc, fio)
    _audit(db, order, fio=fio, role=role, action="file", detail=f"{kind} {version}", after=safe)
    return doc


def approve_file(db: Session, order: ExternalOrder, document_id: str, *, role: str, fio: str) -> None:
    from app.services.external_orders import ExternalOrderError, _audit

    doc = _doc(order, document_id)
    if role not in {doc.owner_role, "ks"}:
        raise ExternalOrderError("Утверждает владелец файла или коммерческая служба", 403)
    before = "утверждён" if doc.approved else "не утверждён"
    doc.approved = True
    _audit(db, order, fio=fio, role=role, action="approve_file", detail=doc.title, before=before, after="утверждён")


def delete_file(db: Session, order: ExternalOrder, document_id: str, *, role: str, fio: str) -> None:
    from app.services.external_orders import ExternalOrderError, _audit

    if role not in _UPLOAD_ROLES:
        raise ExternalOrderError("Удалять файл может участник маршрута", 403)
    doc = _doc(order, document_id)
    if doc.approved:
        raise ExternalOrderError("Утверждённую версию удалять нельзя", 409)
    path = Path(doc.stored_path) if doc.stored_path else None
    _audit(
        db,
        order,
        fio=fio,
        role=role,
        action="delete_file",
        detail=doc.title,
        before=doc.version,
        after="",
    )
    if path and path.is_file():
        path.unlink()
    db.delete(doc)


def create_baseline(db: Session, order: ExternalOrder, *, role: str, fio: str, fields: dict) -> ExternalOrderBaseline:
    from app.services.external_orders import ExternalOrderError, _audit

    if role not in {"ks", "finance", "rp", "committee"}:
        raise ExternalOrderError("Базовую версию собирают КС, финансы, РП или Комитет", 403)
    required = ("composition", "cost", "mcr", "margin", "bdds", "deadlines")
    if any(not str(fields.get(key) or "").strip() for key in required):
        raise ExternalOrderError("Нужны состав, стоимость, МЦР, маржа, БДДС и сроки", 400)
    reason = str(fields.get("reason") or "").strip()
    if any(item.immutable for item in order.baselines) and not reason:
        raise ExternalOrderError("Новая базовая версия создаётся с основанием", 400)
    number = len(list(order.baselines)) + 1
    row = ExternalOrderBaseline(
        id=_new_id(),
        order_id=order.id,
        code=f"БВ-{number}",
        composition=str(fields.get("composition") or ""),
        cost=str(fields.get("cost") or ""),
        mcr=str(fields.get("mcr") or ""),
        margin=str(fields.get("margin") or ""),
        bdds=str(fields.get("bdds") or ""),
        deadlines=str(fields.get("deadlines") or ""),
        reason=reason,
        created_by=fio,
    )
    db.add(row)
    _audit(db, order, fio=fio, role=role, action="baseline", detail=row.code, after=reason)
    return row


def lock_baseline(order: ExternalOrder, baseline_id: str, code: str) -> ExternalOrderBaseline | None:
    if baseline_id:
        found = next((item for item in order.baselines if item.id == baseline_id), None)
        if found is None:
            return None
        found.immutable = True
        return found
    if not code:
        return None
    row = ExternalOrderBaseline(
        id=_new_id(),
        order_id=order.id,
        code=code,
        reason="зафиксировано протоколом",
        immutable=True,
    )
    return row


def build_plan(db: Session, order: ExternalOrder, *, role: str, fio: str) -> int:
    from app.services.external_orders import ExternalOrderError, _audit

    if role not in {"rp", "ks"}:
        raise ExternalOrderError("Проект плана собирает руководитель проекта или коммерческая служба", 403)
    if list(order.tasks):
        return len(list(order.tasks))
    previous = ""
    created = 0
    for title, kind, owner in _PLAN:
        if title == "Испытания" and not _applies(order.route, order.order_type, "before_psi", title)[0]:
            continue
        task_id = _new_id()
        db.add(
            ExternalOrderTask(
                id=task_id,
                order_id=order.id,
                title=title,
                kind=kind,
                owner_role=owner,
                depends_on=previous,
                critical=True,
                source_ref="шаблон обязательств",
            )
        )
        previous = task_id
        created += 1
    _audit(db, order, fio=fio, role=role, action="plan", detail=f"задач: {created}")
    return created


def approve_plan(db: Session, order: ExternalOrder, *, role: str, fio: str) -> None:
    from app.services.external_orders import ExternalOrderError, _audit

    if role != "rp":
        raise ExternalOrderError("Базовым план становится после утверждения руководителем проекта", 403)
    if not list(order.tasks):
        raise ExternalOrderError("Сначала соберите проект плана", 400)
    for task in order.tasks:
        task.approved = True
    _audit(db, order, fio=fio, role=role, action="plan_approved", detail="базовый план", after="утверждён")


def publish_plan(db: Session, order: ExternalOrder, *, role: str, fio: str) -> None:
    from app.services.external_orders import ExternalOrderError, _audit

    if role != "rp":
        raise ExternalOrderError("В TurboProject публикует руководитель проекта", 403)
    tasks = list(order.tasks)
    if not tasks or not all(task.approved for task in tasks):
        raise ExternalOrderError("Публикуется только утверждённый план", 400)
    if any(task.published for task in tasks):
        raise ExternalOrderError("План уже опубликован, повтор не создаёт копии задач", 409)
    for task in tasks:
        task.published = True
    _audit(db, order, fio=fio, role=role, action="plan_published", detail="без копий задач")


def _extract(db: Session, order: ExternalOrder, doc: ExternalOrderDocument, raw: bytes, suffix: str) -> None:
    from app.services.external_orders import _audit

    if suffix == ".docx":
        paragraphs = _docx_paragraphs(raw)
        found: set[str] = set()
        for index, line in enumerate(paragraphs, start=1):
            folded = line.casefold().replace("ё", "е")
            for field, token, code, owner in _FIELDS:
                if field in found or token not in folded:
                    continue
                found.add(field)
                _remember(db, order, doc, field=field, value=line, location=f"абзац {index}", code=code, owner=owner)
        for field, _token, _code, owner in _FIELDS:
            if field not in found and doc.kind in {"contract", "tz", "tkp"}:
                add_gap(db, order, field=field, owner_role=owner, detail=f"В {doc.title} нет места для «{field}»")
    elif suffix == ".xlsx" and doc.kind == "specification":
        rows = _xlsx_rows(raw)
        if not rows:
            add_gap(db, order, field="specification", owner_role="kb", detail="Строки спецификации не прочитаны")
            return
        previous = [line for line in order.lines if line.document_id != doc.id]
        changes = _compare(previous, rows)
        for name, qty, amount, change in changes:
            db.add(
                ExternalOrderLine(
                    id=_new_id(),
                    order_id=order.id,
                    document_id=doc.id,
                    name=name[:512],
                    qty=qty,
                    amount=amount,
                    change=change,
                )
            )
        _audit(db, order, fio="система", role="agent", action="spec_lines", detail=f"строк: {len(changes)}")
    elif suffix == ".pdf":
        add_gap(
            db,
            order,
            field="pdf_text",
            owner_role="ks",
            detail="Текст PDF не извлечён. Вывод сохраняется только со страницей источника.",
        )


def _remember(db: Session, order, doc, *, field: str, value: str, location: str, code: str, owner: str) -> None:
    from app.models.external_order import ExternalOrderFinding

    db.add(
        ExternalOrderFinding(
            id=_new_id(),
            order_id=order.id,
            field=field,
            value=value[:2000],
            source_ref=doc.title,
            location=location,
            document_id=doc.id,
            confidence="извлечено",
            status="draft",
            owner_role=owner,
            proposed_by="разбор файла",
        )
    )
    match = next((item for item in order.diffs if item.code == code), None)
    if match is None or match.status == "closed":
        return
    if doc.kind == "tkp":
        match.left_value = value[:2000]
    elif doc.kind in {"contract", "specification"}:
        match.right_value = value[:2000]
    match.note = location


def _compare(previous: list[ExternalOrderLine], rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str, str]]:
    old = {item.name.casefold(): item for item in previous}
    seen: set[str] = set()
    out: list[tuple[str, str, str, str]] = []
    for name, qty, amount in rows:
        key = name.casefold()
        seen.add(key)
        prior = old.get(key)
        if prior is None:
            change = "added"
        elif prior.qty != qty:
            change = "qty"
        elif prior.amount != amount:
            change = "amount"
        else:
            change = "same"
        out.append((name, qty, amount, change))
    for key, prior in old.items():
        if key not in seen:
            out.append((prior.name, prior.qty, prior.amount, "removed"))
    return out


def _material_change(db: Session, order: ExternalOrder, doc: ExternalOrderDocument, fio: str) -> None:
    from app.services.external_orders import _audit

    notify(
        db,
        order,
        kind="change",
        role="rp",
        title="Новая спецификация после решения Комитета",
        body=f"{doc.title} {doc.version}. Нужны повторные заключения.",
    )
    for owner in _REPEAT:
        add_gap(
            db,
            order,
            field=f"повтор {owner}",
            owner_role=owner,
            detail=f"Повторное заключение по {doc.version}",
            hours=4,
        )
    number = len(list(order.baselines)) + 1
    db.add(
        ExternalOrderBaseline(
            id=_new_id(),
            order_id=order.id,
            code=f"БВ-{number}",
            reason=f"новая спецификация {doc.version}",
            created_by=fio or "система",
        )
    )
    _audit(db, order, fio=fio or "система", role="ks", action="change", detail=doc.version, after="повторные заключения")


def _has_committee(order: ExternalOrder) -> bool:
    return any(item.decision in {"confirmed", "confirmed_conditions"} for item in order.decisions)


def _doc(order: ExternalOrder, document_id: str) -> ExternalOrderDocument:
    from app.services.external_orders import ExternalOrderError

    found = next((item for item in order.documents if item.id == document_id), None)
    if found is None:
        raise ExternalOrderError("Документ не найден", 404)
    return found


def _docx_paragraphs(raw: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = package.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile):
        return []
    root = ET.fromstring(xml)
    lines: list[str] = []
    for paragraph in root.iter(f"{_W}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{_W}t")).strip()
        if text:
            lines.append(text)
    return lines


def _xlsx_rows(raw: bytes) -> list[tuple[str, str, str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            shared = _shared_strings(package)
            sheet = package.read("xl/worksheets/sheet1.xml")
    except (KeyError, zipfile.BadZipFile):
        return []
    root = ET.fromstring(sheet)
    rows: list[tuple[str, str, str]] = []
    for row in root.iter(f"{_X}row"):
        cells: list[str] = []
        for cell in row.findall(f"{_X}c"):
            value = cell.find(f"{_X}v")
            text = value.text if value is not None and value.text else ""
            if cell.attrib.get("t") == "s" and text.isdigit():
                index = int(text)
                text = shared[index] if index < len(shared) else ""
            cells.append(text.strip())
        if not any(cells):
            continue
        name = cells[0] if cells else ""
        if not name or name.casefold() in {"наименование", "имя"}:
            continue
        qty = cells[1] if len(cells) > 1 else ""
        amount = cells[2] if len(cells) > 2 else ""
        rows.append((name, qty, amount))
    return rows


def _shared_strings(package: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in package.namelist():
        return []
    root = ET.fromstring(package.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(f"{_X}t")) for item in root.findall(f"{_X}si")]


def _new_id() -> str:
    from uuid import uuid4

    return uuid4().hex


def refresh_overdue(db: Session, order: ExternalOrder) -> None:
    now = datetime.now(timezone.utc)
    for item in order.checks:
        due = item.due_at
        if due is not None and due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due is None or due >= now:
            continue
        if item.status not in {"open", "not_started", "in_progress", "review"}:
            continue
        item.status = "overdue"
        notify(db, order, kind="overdue", role=item.owner_role, title="Просрочен пункт чек-листа", body=item.text)
