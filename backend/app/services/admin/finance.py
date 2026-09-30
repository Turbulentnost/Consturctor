from __future__ import annotations

import csv
import hashlib
import io
import mimetypes
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.finance import FinanceImport, FinanceSalaryEntry
from app.models.org import OrgPerson, OrgPosition
from app.models.position_kpi import PositionKpiMetric, PositionKpiProfile
from app.services.admin.salary_extraction import (
    SalaryExtractionError,
    extract_salary_document,
)
from app.services.position_kpi.connect import upsert_generated_catalog
from app.services.position_kpi.daily import get_or_compute_position_kpi, resolve_profile
from app.services.position_kpi.extract import extract_position_kpis
from app.services.workflows.document import DocumentError, load_attachment_bytes

IMPORT_KINDS = {"salary", "material_incentive"}
MAX_FILE_BYTES = 25 * 1024 * 1024
_RUSSIAN_NAME_RE = re.compile(r"^[А-Яа-яЁё][А-Яа-яЁё\s.'-]*$")


class FinanceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _is_russian_name(value: str) -> bool:
    return bool(_RUSSIAN_NAME_RE.fullmatch(value.strip()))


def list_employees(
    db: Session,
    *,
    search: str = "",
    department: str = "",
    limit: int = 500,
    login_fios: list[str] | None = None,
) -> dict[str, Any]:
    stmt = select(OrgPerson).where(OrgPerson.is_active.is_(True)).order_by(OrgPerson.fio)
    needle = search.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            OrgPerson.fio.ilike(like) | OrgPerson.position.ilike(like)
        )
    if department.strip():
        stmt = stmt.where(OrgPerson.department == department.strip())
    if login_fios is None:
        people = list(db.scalars(stmt.limit(max(1, min(limit, 2000)))).all())
        ordered_people: list[OrgPerson | None] = people
        ordered_fios = [person.fio for person in people]
    else:
        keys = [" ".join(fio.lower().replace("ё", "е").split()) for fio in login_fios]
        people = list(
            db.scalars(
                select(OrgPerson).where(
                    OrgPerson.is_active.is_(True),
                    OrgPerson.fio_key.in_(keys),
                )
            ).all()
        )
        people_by_key = {person.fio_key: person for person in people}
        ordered_people = [people_by_key.get(key) for key in keys]
        ordered_fios = login_fios
    rows = []
    for fio, person in zip(ordered_fios, ordered_people, strict=True):
        if not _is_russian_name(fio):
            continue
        if department.strip() and (person is None or person.department != department.strip()):
            continue
        salary = None
        if person is not None and person.position_id:
            salary = db.scalar(
                select(FinanceSalaryEntry)
                .where(
                    FinanceSalaryEntry.position_id == person.position_id,
                    FinanceSalaryEntry.is_current.is_(True),
                    FinanceSalaryEntry.effective_from <= date.today(),
                )
                .order_by(FinanceSalaryEntry.effective_from.desc())
                .limit(1)
            )
        rows.append(
            {
                "id": person.id if person is not None else "",
                "fio": fio,
                "position": person.position if person is not None else "",
                "position_id": (person.position_id or "") if person is not None else "",
                "department": person.department if person is not None else "",
                "salary": str(salary.amount) if salary else "",
                "currency": salary.currency if salary else "RUB",
                "salary_effective_from": salary.effective_from.isoformat() if salary else "",
            }
        )
    departments = sorted({row["department"] for row in rows if row["department"]})
    return {"rows": rows, "departments": departments, "total": len(rows)}


def list_positions(db: Session, *, limit: int = 2000) -> dict[str, Any]:
    positions = db.scalars(
        select(OrgPosition)
        .where(OrgPosition.is_active.is_(True))
        .order_by(OrgPosition.name)
        .limit(max(1, min(limit, 5000)))
    ).all()
    rows = [{"id": position.id, "name": position.name} for position in positions]
    return {"rows": rows, "total": len(rows)}


def employee_salaries(db: Session, person_id: str) -> dict[str, Any]:
    person = _person(db, person_id)
    if not person.position_id:
        return {
            "employee": {"id": person.id, "fio": person.fio, "position": person.position},
            "rows": [],
        }
    rows = db.scalars(
        select(FinanceSalaryEntry)
        .where(FinanceSalaryEntry.position_id == person.position_id)
        .order_by(
            FinanceSalaryEntry.effective_from.desc(),
            FinanceSalaryEntry.revision.desc(),
        )
    ).all()
    return {
        "employee": {"id": person.id, "fio": person.fio, "position": person.position},
        "rows": [
            {
                "id": row.id,
                "amount": str(row.amount),
                "currency": row.currency,
                "effective_from": row.effective_from.isoformat(),
                "revision": row.revision,
                "is_current": row.is_current,
                "import_id": row.import_id,
                "replaced_entry_id": row.replaced_entry_id or "",
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ],
    }


def employee_kpi(
    db: Session,
    person_id: str,
    *,
    period_from: date | None = None,
    period_to: date | None = None,
) -> dict[str, Any]:
    person = _person(db, person_id)
    if not person.position:
        raise FinanceError("У сотрудника не указана должность", 404)
    as_of = period_to or date.today()
    result = get_or_compute_position_kpi(
        db,
        person.position,
        as_of=as_of,
        date_from=period_from,
        date_to=period_to,
        subject=person.fio,
        allow_stale=True,
    )
    if result.get("tiles"):
        return result
    profile = resolve_profile(db, person.position, as_of=as_of)
    if profile is None:
        return result
    metrics = db.scalars(
        select(PositionKpiMetric)
        .where(PositionKpiMetric.profile_id == profile.id)
        .order_by(PositionKpiMetric.sort_order, PositionKpiMetric.code)
    ).all()
    return {
        **result,
        "tiles": [
            {
                "code": metric.code,
                "name": metric.name,
                "weight": metric.weight,
                "unit": metric.unit,
                "plan": metric.plan_value,
                "score": None,
                "contrib": None,
                "fact": None,
                "evidence": "Методика KPI; фактические данные ещё не подключены",
            }
            for metric in metrics
        ],
    }


def create_import(
    db: Session,
    *,
    kind: str,
    filename: str,
    raw: bytes,
    user_id: str,
    user_fio: str,
) -> dict[str, Any]:
    import_kind = kind.strip().lower()
    if import_kind not in IMPORT_KINDS:
        raise FinanceError("Неизвестный тип импорта")
    if not raw:
        raise FinanceError("Файл пустой")
    if len(raw) > MAX_FILE_BYTES:
        raise FinanceError("Файл больше 25 МБ")
    import_id = str(uuid.uuid4())
    safe_name = Path(filename or "file").name
    folder = settings.finance_storage_dir / import_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_name
    path.write_bytes(raw)
    row = FinanceImport(
        id=import_id,
        kind=import_kind,
        status="parsing",
        original_name=safe_name,
        storage_path=str(path),
        media_type=mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        created_by=user_id,
        created_by_fio=user_fio,
        draft_json={},
        validation_json={},
    )
    db.add(row)
    db.flush()
    try:
        draft = (
            _parse_salary(db, safe_name, raw)
            if import_kind == "salary"
            else _parse_material(db, safe_name, raw)
        )
        validation = validate_draft(db, import_kind, draft)
        row.draft_json = draft
        row.validation_json = validation
        row.rows_total = _draft_count(import_kind, draft)
        row.rows_valid = max(0, row.rows_total - len(validation["errors"]))
        row.status = "review"
    except Exception as exc:  # noqa: BLE001
        row.status = "error"
        row.error_text = str(exc)
    db.commit()
    db.refresh(row)
    return serialize_import(row)


def list_imports(
    db: Session, *, kind: str = "", status: str = "", limit: int = 200
) -> dict[str, Any]:
    stmt = select(FinanceImport).order_by(FinanceImport.created_at.desc())
    if kind.strip():
        stmt = stmt.where(FinanceImport.kind == kind.strip())
    if status.strip():
        stmt = stmt.where(FinanceImport.status == status.strip())
    rows = db.scalars(stmt.limit(max(1, min(limit, 1000)))).all()
    return {"rows": [serialize_import(row, include_draft=False) for row in rows], "total": len(rows)}


def get_import(db: Session, import_id: str) -> FinanceImport:
    row = db.get(FinanceImport, import_id)
    if row is None:
        raise FinanceError("Импорт не найден", 404)
    return row


def update_import_draft(
    db: Session, import_id: str, draft: dict[str, Any]
) -> dict[str, Any]:
    row = get_import(db, import_id)
    if row.status == "confirmed":
        raise FinanceError("Подтверждённый импорт нельзя изменить", 409)
    validation = validate_draft(db, row.kind, draft)
    row.draft_json = draft
    row.validation_json = validation
    row.rows_total = _draft_count(row.kind, draft)
    row.rows_valid = max(0, row.rows_total - len(validation["errors"]))
    row.status = "review"
    db.commit()
    db.refresh(row)
    return serialize_import(row)


def confirm_import(db: Session, import_id: str) -> dict[str, Any]:
    row = get_import(db, import_id)
    if row.status == "confirmed":
        return serialize_import(row)
    validation = validate_draft(db, row.kind, row.draft_json or {})
    row.validation_json = validation
    if validation["errors"]:
        db.commit()
        raise FinanceError("Исправьте ошибки перед подтверждением", 409)
    if row.kind == "salary":
        _confirm_salaries(db, row)
    else:
        _confirm_material(db, row)
    row.status = "confirmed"
    row.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return serialize_import(row)


def serialize_import(row: FinanceImport, *, include_draft: bool = True) -> dict[str, Any]:
    result = {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "filename": row.original_name,
        "media_type": row.media_type,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "created_by": row.created_by,
        "created_by_fio": row.created_by_fio,
        "validation": row.validation_json or {},
        "error": row.error_text,
        "rows_total": row.rows_total,
        "rows_valid": row.rows_valid,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "confirmed_at": _iso(row.confirmed_at),
    }
    if include_draft:
        result["draft"] = row.draft_json or {}
    return result


def validate_draft(db: Session, kind: str, draft: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if kind == "salary":
        for index, item in enumerate(draft.get("rows") or []):
            position_id = str(item.get("position_id") or "")
            if not position_id or db.get(OrgPosition, position_id) is None:
                errors.append(
                    {
                        "row": index,
                        "field": "position_id",
                        "message": "Выберите должность",
                    }
                )
            try:
                if Decimal(str(item.get("amount") or "0").replace(" ", "").replace(",", ".")) <= 0:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                errors.append({"row": index, "field": "amount", "message": "Некорректный оклад"})
            try:
                date.fromisoformat(str(item.get("effective_from") or ""))
            except ValueError:
                errors.append({"row": index, "field": "effective_from", "message": "Укажите дату"})
    else:
        try:
            date.fromisoformat(str(draft.get("effective_from") or ""))
        except ValueError:
            errors.append({"field": "effective_from", "message": "Укажите дату вступления"})
        for index, profile in enumerate(draft.get("profiles") or []):
            if not str(profile.get("position_name") or "").strip():
                errors.append({"row": index, "field": "position_name", "message": "Укажите должность"})
            metrics = profile.get("metrics") if isinstance(profile.get("metrics"), list) else []
            total = sum(int(metric.get("weight") or 0) for metric in metrics if isinstance(metric, dict))
            if not metrics:
                errors.append({"row": index, "field": "metrics", "message": "Добавьте KPI"})
            elif total != 100:
                errors.append({"row": index, "field": "metrics", "message": f"Сумма весов KPI: {total}%"})
    return {"errors": errors, "warnings": warnings}


def _parse_salary(db: Session, name: str, raw: bytes) -> dict[str, Any]:
    try:
        extracted = extract_salary_document(name, raw)
    except SalaryExtractionError as exc:
        raise FinanceError(str(exc)) from exc
    positions = db.scalars(
        select(OrgPosition).where(OrgPosition.is_active.is_(True))
    ).all()
    by_name = {_position_key(position.name): position for position in positions}
    effective_from = str(extracted.get("effective_from") or "")
    rows = []
    for values in extracted.get("rows") or []:
        if not isinstance(values, dict):
            continue
        position_name = str(values.get("position_name") or values.get("position") or "").strip()
        position = by_name.get(_position_key(position_name))
        rows.append(
            {
                "row_id": str(uuid.uuid4()),
                "position_id": position.id if position else "",
                "position_name": position.name if position else position_name,
                "amount": str(values.get("amount") or "").replace("\u00a0", " ").strip(),
                "currency": str(values.get("currency") or "RUB").strip() or "RUB",
                "effective_from": str(values.get("effective_from") or effective_from),
            }
        )
    if not rows:
        rows.append(
            {
                "row_id": str(uuid.uuid4()),
                "position_id": "",
                "position_name": "",
                "amount": "",
                "currency": "RUB",
                "effective_from": effective_from,
            }
        )
    return {"rows": rows}


def _parse_material(db: Session, name: str, raw: bytes) -> dict[str, Any]:
    try:
        attachment = load_attachment_bytes(name, raw, ocr=True)
    except DocumentError as exc:
        raise FinanceError(str(exc)) from exc
    text = str(attachment.get("text") or "")
    effective = _find_date(text) or _find_date(name)
    positions = db.scalars(select(OrgPosition).where(OrgPosition.is_active.is_(True))).all()
    profiles = []
    folded = text.casefold().replace("ё", "е")
    for position in positions:
        if position.name.casefold().replace("ё", "е") not in folded:
            continue
        extracted = extract_position_kpis(text, position.name)
        profiles.append(
            {
                "position_id": position.id,
                "position_name": position.name,
                "bonus_base_pct": 100,
                "bonus_kind": "salary_times_crp_times_sum",
                "metrics": extracted.get("metrics") or [],
            }
        )
    if not profiles:
        profiles.append(
            {
                "position_id": "",
                "position_name": "",
                "bonus_base_pct": 100,
                "bonus_kind": "salary_times_crp_times_sum",
                "metrics": [],
            }
        )
    return {
        "effective_from": effective.isoformat() if effective else "",
        "source_title": Path(name).stem,
        "profiles": profiles,
    }


def _read_table(name: str, raw: bytes) -> list[dict[str, Any]]:
    suffix = Path(name).suffix.lower()
    matrix: list[list[Any]] = []
    if suffix in {".xlsx", ".xlsm"}:
        workbook = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        sheet = workbook.active
        matrix = [list(row) for row in sheet.iter_rows(values_only=True)]
    elif suffix in {".csv", ".txt", ".tsv"}:
        text = raw.decode("utf-8-sig", errors="replace")
        if suffix == ".tsv":
            dialect = csv.excel_tab
        else:
            try:
                dialect = csv.Sniffer().sniff(text[:2048], delimiters=";,\t|")
            except csv.Error:
                dialect = csv.excel
        matrix = [list(row) for row in csv.reader(io.StringIO(text), dialect)]
    else:
        attachment = load_attachment_bytes(name, raw, ocr=True)
        lines = [line for line in str(attachment.get("text") or "").splitlines() if line.strip()]
        matrix = [re.split(r"\t|;|\s{2,}", line.strip()) for line in lines]
    return _map_salary_matrix(matrix)


def _map_salary_matrix(matrix: list[list[Any]]) -> list[dict[str, Any]]:
    aliases = {
        "fio": ("фио", "сотрудник", "работник"),
        "position": ("должность",),
        "amount": ("оклад", "сумма", "размер"),
        "currency": ("валюта",),
        "effective_from": ("дата", "действует с"),
    }
    header_index = -1
    mapping: dict[str, int] = {}
    for idx, row in enumerate(matrix[:30]):
        normalized = [str(cell or "").casefold().replace("ё", "е").strip() for cell in row]
        candidate: dict[str, int] = {}
        for field, names in aliases.items():
            for col, value in enumerate(normalized):
                if any(name == value or name in value for name in names):
                    candidate[field] = col
                    break
        if "fio" in candidate and "amount" in candidate:
            header_index, mapping = idx, candidate
            break
    if header_index < 0:
        return []
    rows: list[dict[str, Any]] = []
    for row in matrix[header_index + 1 :]:
        item = {
            field: row[col] if col < len(row) and row[col] is not None else ""
            for field, col in mapping.items()
        }
        if not str(item.get("fio") or "").strip():
            continue
        raw_date = item.get("effective_from")
        if isinstance(raw_date, (date, datetime)):
            item["effective_from"] = raw_date.date().isoformat() if isinstance(raw_date, datetime) else raw_date.isoformat()
        rows.append(item)
    return rows


def _confirm_salaries(db: Session, import_row: FinanceImport) -> None:
    for item in import_row.draft_json.get("rows") or []:
        position = _position(db, str(item.get("position_id") or ""))
        effective_from = date.fromisoformat(str(item["effective_from"]))
        amount = Decimal(str(item["amount"]).replace(" ", "").replace(",", "."))
        previous = db.scalar(
            select(FinanceSalaryEntry)
            .where(
                FinanceSalaryEntry.position_id == position.id,
                FinanceSalaryEntry.effective_from == effective_from,
                FinanceSalaryEntry.is_current.is_(True),
            )
            .order_by(FinanceSalaryEntry.revision.desc())
            .limit(1)
        )
        revision = (previous.revision + 1) if previous else 1
        if previous:
            previous.is_current = False
        db.add(
            FinanceSalaryEntry(
                id=str(uuid.uuid4()),
                position_id=position.id,
                amount=amount,
                currency=str(item.get("currency") or "RUB")[:8],
                effective_from=effective_from,
                revision=revision,
                is_current=True,
                import_id=import_row.id,
                replaced_entry_id=previous.id if previous else None,
                position_snapshot=position.name,
            )
        )


def _confirm_material(db: Session, import_row: FinanceImport) -> None:
    effective_from = date.fromisoformat(str(import_row.draft_json["effective_from"]))
    for item in import_row.draft_json.get("profiles") or []:
        name = str(item.get("position_name") or "").strip()
        current = db.scalars(
            select(PositionKpiProfile).where(
                PositionKpiProfile.position_name == name,
                PositionKpiProfile.effective_from < effective_from,
                PositionKpiProfile.effective_to.is_(None),
            )
        ).all()
        for profile in current:
            profile.effective_to = effective_from - timedelta(days=1)
        catalog = dict(item)
        catalog.update(
            {
                "position_name": name,
                "effective_from": effective_from,
                "source_import_id": import_row.id,
                "source_title": str(import_row.draft_json.get("source_title") or import_row.original_name),
            }
        )
        upsert_generated_catalog(db, position=name, catalog=catalog, modules=[])


def _person(db: Session, person_id: str) -> OrgPerson:
    person = db.get(OrgPerson, person_id)
    if person is None or not person.is_active:
        raise FinanceError("Сотрудник не найден", 404)
    return person


def _position(db: Session, position_id: str) -> OrgPosition:
    position = db.get(OrgPosition, position_id)
    if position is None or not position.is_active:
        raise FinanceError("Должность не найдена", 404)
    return position


def _position_key(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _find_date(text: str) -> date | None:
    match = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)", text or "")
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def _draft_count(kind: str, draft: dict[str, Any]) -> int:
    return len(draft.get("rows") or []) if kind == "salary" else len(draft.get("profiles") or [])


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()
