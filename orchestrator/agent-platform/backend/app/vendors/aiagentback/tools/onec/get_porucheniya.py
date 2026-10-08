"""
Поручения и задачи протоколов из 1С:ERP (OData).

Читает документы, требующие контроля (без «Принято», «Закрыт»,
«Принято и закрыто», «Подготовлен»):
- Document_ТД_Поручения + все мероприятия ТЧ;
- Document_ТД_Протокол + незакрытые задачи InformationRegister_ТД_ЗадачиПротоколов
  (протокол без открытых задач в трекер не попадает).

Дата документа/срока на выборку не влияет. Фильтр по Руководителю — опционально.
Приоритет — по ближайшему сроку в рабочих днях:
Критический ≤3 р.д. (и просрочка), Высокий ≤5 р.д., Низкий — дальше.

CLI:
  python -m app.vendors.aiagentback.tools.onec.get_porucheniya
  python -m app.vendors.aiagentback.tools.onec.get_porucheniya --author-fio "..."
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import json
import re
import sys
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import requests

from app.vendors.aiagentback.core.logging import get_logger
from app.vendors.aiagentback.integrations.onec_odata import fetch_all
from app.vendors.aiagentback.tools.onec.connection import CONFIG, ODataConfig, create_session
from app.vendors.aiagentback.tools.onec.get_meetings import entity_url, odata_get_json
from app.vendors.aiagentback.tools.onec.lookup_person_department import load_departments_for_responsible_keys
from app.vendors.aiagentback.tools.onec.lookup_user_ref import (
    USER_CATALOG,
    is_empty_key,
    load_persons_for_keys,
    normalize_name,
    resolve_user_by_fio,
)
from app.vendors.aiagentback.services.porucheniya_artifact_mapping_context import (
    document_mapping_context_fingerprint,
)

logger = get_logger(__name__)

PORUCHENIYA_TABULAR = "Document_ТД_Поручения_Поручения"
PORUCHENIYA_DOCUMENT = "Document_ТД_Поручения"
PORUCHENIYA_ATTACHED_FILES = "Catalog_ТД_ПорученияПрисоединенныеФайлы"
PROTOCOL_TASKS_REGISTER = "InformationRegister_ТД_ЗадачиПротоколов"
PROTOCOL_DOCUMENT = "Document_ТД_Протокол"
PROTOCOL_ATTACHED_FILES = "Catalog_ТД_ПротоколПрисоединенныеФайлы"
TOPIC_CATALOG = "Catalog_ТД_ТемыСовещаний"
INCOMING_CORRESPONDENCE_DOCUMENT = "Document_ТД_ВходящаяКорреспонденция"
EMPTY_DATE = "0001-01-01T00:00:00"
GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Закрытые статусы документов (как в 1С и возможные варианты написания).
CLOSED_DOCUMENT_STATUSES = (
    "Закрыт",
    "Закрыто",
    "Принято и закрыто",
    "ПринятоИЗакрыто",
)
_CLOSED_STATUS_KEYS = frozenset(
    status.casefold().replace(" ", "") for status in CLOSED_DOCUMENT_STATUSES
)
# «Принято» / «Подготовлен» не являются технически закрытыми статусами 1С,
# однако по правилам Action Tracker не требуют контроля:
# «Принято» — документ уже принят; «Подготовлен» — черновик протокола без задач.
EXCLUDED_TASK_TRACKER_STATUSES = (*CLOSED_DOCUMENT_STATUSES, "Принято", "Подготовлен")
_EXCLUDED_TASK_TRACKER_STATUS_KEYS = frozenset(
    status.casefold().replace(" ", "") for status in EXCLUDED_TASK_TRACKER_STATUSES
)
# Пороги приоритета по сроку (рабочие дни пн–пт от сегодня до due).
PRIORITY_CRITICAL_BUSINESS_DAYS = 3
PRIORITY_HIGH_BUSINESS_DAYS = 5
POSTPONEMENT_APPLIED_RE = re.compile(
    r"Перенос\s+с\s+.+\s+на\s+",
    re.IGNORECASE,
)
POSTPONEMENT_TRANSFER_RE = re.compile(
    r"Перенос\s+с\s+([\d.]+)\s+на\s+([\d.]+)\s+(.+?)\(",
    re.IGNORECASE,
)
POSTPONEMENT_DATES_RE = re.compile(
    r"Перенос\s+с\s+([\d.]+)\s+на\s+([\d.]+)",
    re.IGNORECASE,
)


def format_postponement_request_display(
    *,
    from_date: str = "",
    to_date: str = "",
    approved_by: str = "",
) -> str:
    parts: list[str] = []
    if from_date or to_date:
        parts.append(f"с {from_date or '—'} на {to_date or '—'}")
    approver = approved_by.strip()
    if approver:
        parts.append(f"Согласовано: {approver}")
    return "; ".join(parts)


def extract_postponement_fields(
    *,
    note: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    """Извлекает перенос срока из Примечание/Комментарий задачи протокола."""
    chunks = [str(note or "").strip(), str(comment or "").strip()]
    transfer_text = next((chunk for chunk in chunks if chunk and "перенос" in chunk.lower()), "")
    if not transfer_text:
        return {}

    from_date = ""
    to_date = ""
    approved_by = ""
    transfer_match = POSTPONEMENT_TRANSFER_RE.search(transfer_text)
    if transfer_match:
        from_date = transfer_match.group(1).strip()
        to_date = transfer_match.group(2).strip()
        approved_by = transfer_match.group(3).strip()
    else:
        dates_match = POSTPONEMENT_DATES_RE.search(transfer_text)
        if dates_match:
            from_date = dates_match.group(1).strip()
            to_date = dates_match.group(2).strip()

    return {
        "postponement_from": from_date,
        "postponement_to": to_date,
        "postponement_approved_by": approved_by,
        "postponement_request": format_postponement_request_display(
            from_date=from_date,
            to_date=to_date,
            approved_by=approved_by,
        ),
        "postponement_basis": "",
        "postponement_approved": bool(POSTPONEMENT_APPLIED_RE.search(transfer_text)),
    }


def parse_input_date(value: str | date | None, *, default: date | None = None) -> date:
    if value is None:
        if default is None:
            raise ValueError("Дата не указана")
        return default
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    normalized = str(value).strip()
    if not normalized:
        if default is None:
            raise ValueError("Дата не указана")
        return default
    return date.fromisoformat(normalized[:10])


def parse_onec_datetime(value: str | None) -> datetime | None:
    if not value or value.startswith(EMPTY_DATE[:10]):
        return None
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def start_of_day(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(value: datetime) -> datetime:
    return value.replace(hour=23, minute=59, second=59, microsecond=0)


def format_odata_datetime(day: date, *, end: bool = False) -> str:
    if end:
        return f"datetime'{day.isoformat()}T23:59:59'"
    return f"datetime'{day.isoformat()}T00:00:00'"


def fio_matches(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return normalize_name(left) == normalize_name(right)


def resolve_manager_keys_for_fio(
    session: requests.Session,
    manager_fio: str,
    *,
    config: ODataConfig = CONFIG,
) -> set[str]:
    """Ключи 1С пользователя/физлица для фильтра по руководителю поручения."""
    user_ref, _, users = resolve_user_by_fio(session, manager_fio.strip(), config=config)
    keys = {user_ref}
    for user in users:
        person_key = user.get("ФизическоеЛицо_Key")
        if person_key and not is_empty_key(person_key):
            keys.add(person_key)
    return keys


def build_manager_filter(manager_keys: set[str]) -> str:
    parts = [
        f"Руководитель_Key eq guid'{key}'"
        for key in manager_keys
        if not is_empty_key(key)
    ]
    if not parts:
        raise ValueError("Не удалось определить ключ руководителя в 1С")
    if len(parts) == 1:
        return parts[0]
    return f"({' or '.join(parts)})"


# alias для тестов и обратной совместимости импортов
resolve_author_keys_for_fio = resolve_manager_keys_for_fio
build_author_filter = build_manager_filter


def entity_description(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return (row.get("Description") or "").strip()


def row_has_file(row: dict[str, Any]) -> bool:
    if (row.get("Файл_Base64Data") or "").strip():
        return True
    file_value = row.get("Файл")
    if isinstance(file_value, str) and file_value.strip() and not file_value.startswith(EMPTY_DATE[:10]):
        return True
    return False


def format_has_file(value: bool) -> str:
    return "Да" if value else "Нет"


def _guess_artifact_content_type(extension: str, filename: str) -> str:
    ext = extension.strip().lstrip(".").lower()
    if ext:
        guessed = mimetypes.guess_type(f"file.{ext}", strict=False)[0]
        if guessed:
            return guessed
    guessed = mimetypes.guess_type(filename or "", strict=False)[0]
    return guessed or "application/octet-stream"


def _normalize_artifact_filename(row: dict[str, Any]) -> str:
    description = str(row.get("Description") or "").strip()
    path = str(row.get("ПутьКФайлу") or "").strip().replace("/", "\\")
    extension = str(row.get("Расширение") or "").strip().lstrip(".")
    if path:
        filename = path.rsplit("\\", 1)[-1]
        if filename:
            return filename
    if description:
        if extension and not description.casefold().endswith(f".{extension.casefold()}"):
            return f"{description}.{extension}"
        return description
    if extension:
        return f"file.{extension}"
    ref_key = str(row.get("Ref_Key") or "").strip()
    return f"{ref_key}.bin" if ref_key else "file.bin"


def _artifact_row_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""


def _artifact_file_fingerprint(
    row: dict[str, Any],
    *,
    source_entity: str,
    file_id: str,
    filename: str,
) -> str:
    """Stable revision key without exposing file bytes in the dashboard payload."""
    encoded_content = _artifact_row_value(row, "ФайлХранилище_Base64Data")
    payload = {
        "source_entity": source_entity,
        "file_id": file_id,
        "filename": filename,
        "size": _artifact_row_value(row, "Размер"),
        "path": _artifact_row_value(row, "ПутьКФайлу"),
        "extension": _artifact_row_value(row, "Расширение"),
        "modified_at": _artifact_row_value(
            row,
            "ДатаМодификацииУниверсальная",
            "ДатаИзменения",
            "ДатаРедактирования",
            "ModifiedAt",
        ),
        "created_at": _artifact_row_value(row, "ДатаСоздания", "CreatedAt"),
        "author_key": _artifact_row_value(row, "Автор_Key", "АвторФайла_Key"),
        "modified_by_key": _artifact_row_value(row, "Изменил_Key", "ИзменилФайл_Key"),
        "content_hash": (
            hashlib.sha256(encoded_content.encode("ascii", "ignore")).hexdigest()
            if encoded_content
            else ""
        ),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _build_artifact_file_payload(row: dict[str, Any], *, source_entity: str) -> dict[str, Any]:
    file_id = str(row.get("Ref_Key") or "").strip()
    filename = _normalize_artifact_filename(row)
    description = str(row.get("Description") or "").strip()
    path = str(row.get("ПутьКФайлу") or "").strip().replace("/", "\\")
    extension = str(row.get("Расширение") or "").strip().lstrip(".")
    modified_at = _artifact_row_value(
        row,
        "ДатаМодификацииУниверсальная",
        "ДатаИзменения",
        "ДатаРедактирования",
        "ModifiedAt",
    )
    created_at = _artifact_row_value(row, "ДатаСоздания", "CreatedAt")
    author_key = _artifact_row_value(row, "Автор_Key", "АвторФайла_Key")
    modified_by_key = _artifact_row_value(row, "Изменил_Key", "ИзменилФайл_Key")
    return {
        "file_id": file_id,
        "label": description or filename,
        "filename": filename,
        "size": int(row.get("Размер") or 0) or None,
        "content_type": _guess_artifact_content_type(extension, filename),
        "onec_path": path,
        "source_entity": source_entity,
        "kind": "onec_file",
        "action": "platform_download",
        "download_url": f"/api/v1/porucheniya/artifacts/{file_id}/file" if file_id else "",
        "modified_at": modified_at or None,
        "created_at": created_at or None,
        "author": _artifact_row_value(row, "Автор", "АвторПредставление") or None,
        "author_key": author_key or None,
        "modified_by": _artifact_row_value(row, "Изменил", "ИзменилПредставление") or None,
        "modified_by_key": modified_by_key or None,
        "fingerprint": _artifact_file_fingerprint(
            row,
            source_entity=source_entity,
            file_id=file_id,
            filename=filename,
        ),
    }


def _attached_files_url(
    *,
    entity: str,
    filter_expr: str,
    fields: list[str],
    config: ODataConfig,
) -> str:
    return (
        f"{entity_url(config.url, entity)}"
        f"?$filter={quote(filter_expr, safe='')}"
        f"&$select={quote(','.join(fields), safe=',_')}"
        f"&$format=json"
    )


def load_attached_files_for_owner_keys(
    session: requests.Session,
    owner_keys: set[str],
    *,
    entity: str,
    include_content_hash: bool = False,
    config: ODataConfig = CONFIG,
) -> dict[str, list[dict[str, Any]]]:
    """Load attachment metadata without transferring file bytes by default."""
    keys = [key for key in owner_keys if not is_empty_key(key)]
    if not keys:
        return {}

    result: dict[str, list[dict[str, Any]]] = {}
    base_fields = [
        "Ref_Key",
        "Description",
        "ПутьКФайлу",
        "Размер",
        "Расширение",
        "ТипХраненияФайла",
        "ВладелецФайла_Key",
    ]
    if include_content_hash:
        base_fields.append("ФайлХранилище_Base64Data")
    metadata_fields = [
        "ДатаМодификацииУниверсальная",
        "ДатаСоздания",
        "Автор_Key",
        "Изменил_Key",
    ]
    chunk_size = 10
    for offset in range(0, len(keys), chunk_size):
        chunk = keys[offset : offset + chunk_size]
        owner_filter = " or ".join(f"ВладелецФайла_Key eq guid'{key}'" for key in chunk)
        # Помеченные на удаление вложения 1С физически вычищает из тома
        # («очищен как ненужный»), поэтому такие файлы не скачиваются и не
        # должны попадать в результаты/ссылки — иначе клик даёт 404.
        filter_expr = f"({owner_filter}) and DeletionMark eq false"
        try:
            rows = fetch_all(
                session,
                _attached_files_url(
                    entity=entity,
                    filter_expr=filter_expr,
                    fields=[*base_fields, *metadata_fields],
                    config=config,
                ),
                page=100,
                timeout=config.timeout,
            )
            rows = list(rows)
        except (requests.HTTPError, RuntimeError) as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code is None:
                match = re.match(r"HTTP\s+(\d+)", str(exc).strip())
                status_code = int(match.group(1)) if match else None
            if status_code not in {400, 404}:
                raise
            logger.warning(
                "onec_attached_files_metadata_not_available",
                entity=entity,
                status_code=status_code,
            )
            rows = list(
                fetch_all(
                    session,
                    _attached_files_url(
                        entity=entity,
                        filter_expr=filter_expr,
                        fields=base_fields,
                        config=config,
                    ),
                    page=100,
                    timeout=config.timeout,
                )
            )
        for row in rows:
            owner_key = row.get("ВладелецФайла_Key") or ""
            if not owner_key:
                continue
            result.setdefault(owner_key, []).append(
                _build_artifact_file_payload(row, source_entity=entity)
            )

    _resolve_artifact_actor_identities(session, result, config=config)
    return result


def _resolve_artifact_actor_identities(
    session: requests.Session,
    files_by_owner: dict[str, list[dict[str, Any]]],
    *,
    config: ODataConfig,
) -> None:
    """Fill in the author/modifier FIO and rebind their refs to ФизЛицо.

    1C returns only Автор_Key/Изменил_Key from the Пользователи catalog for a file,
    without the display name. Attachment→task scoping needs a person identity that
    lines up with a task's ОтветственноеЛицо (ФизЛица), so we resolve each user to
    its FIO and its ФизическоеЛицо_Key and store both back on the payload.
    """

    user_keys: set[str] = set()
    for payloads in files_by_owner.values():
        for payload in payloads:
            for key_field in ("author_key", "modified_by_key"):
                value = payload.get(key_field)
                if value and not is_empty_key(value):
                    user_keys.add(str(value))
    if not user_keys:
        return

    users = load_users_for_keys(session, user_keys, config=config)
    if not users:
        return

    for payloads in files_by_owner.values():
        for payload in payloads:
            for name_field, key_field in (
                ("author", "author_key"),
                ("modified_by", "modified_by_key"),
            ):
                user = users.get(str(payload.get(key_field) or ""))
                if not user:
                    continue
                fio = str(user.get("Description") or "").strip()
                if fio and not payload.get(name_field):
                    payload[name_field] = fio
                person_key = str(user.get("ФизическоеЛицо_Key") or "").strip()
                if person_key and not is_empty_key(person_key):
                    payload[key_field] = person_key


def person_description(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return (row.get("Description") or row.get("ФИО") or "").strip()


def user_description(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return (row.get("Description") or "").strip()


def load_users_for_keys(
    session: requests.Session,
    user_keys: set[str],
    *,
    config: ODataConfig = CONFIG,
) -> dict[str, dict[str, Any]]:
    keys = [key for key in user_keys if not is_empty_key(key)]
    if not keys:
        return {}

    result: dict[str, dict[str, Any]] = {}
    chunk_size = 15
    for offset in range(0, len(keys), chunk_size):
        chunk = keys[offset : offset + chunk_size]
        filter_expr = " or ".join(f"Ref_Key eq guid'{key}'" for key in chunk)
        url = (
            f"{entity_url(config.url, USER_CATALOG)}"
            f"?$filter={quote(filter_expr, safe='')}"
            f"&$select={quote('Ref_Key,Description,DeletionMark,ФизическоеЛицо_Key,Подразделение_Key', safe=',_')}"
            f"&$format=json"
        )
        for row in fetch_all(session, url, page=100, timeout=config.timeout):
            if row.get("Ref_Key") and not row.get("DeletionMark"):
                result[row["Ref_Key"]] = row
    return result


def load_documents_for_keys(
    session: requests.Session,
    document_keys: set[str],
    *,
    entity: str,
    config: ODataConfig = CONFIG,
    select_fields: str | None = None,
) -> dict[str, dict[str, Any]]:
    keys = [key for key in document_keys if not is_empty_key(key)]
    if not keys:
        return {}

    result: dict[str, dict[str, Any]] = {}
    chunk_size = 10
    for offset in range(0, len(keys), chunk_size):
        chunk = keys[offset : offset + chunk_size]
        filter_expr = " or ".join(f"Ref_Key eq guid'{key}'" for key in chunk)
        url = (
            f"{entity_url(config.url, entity)}"
            f"?$filter={quote(filter_expr, safe='')}"
        )
        if select_fields:
            url += f"&$select={quote(select_fields, safe=',_')}"
        url += "&$format=json"
        for row in fetch_all(session, url, page=50, timeout=config.timeout):
            if row.get("Ref_Key"):
                result[row["Ref_Key"]] = row
    return result


def looks_like_guid(value: str | None) -> bool:
    text = str(value or "").strip()
    return bool(text and GUID_RE.match(text))


def odata_entity_from_type(type_name: str | None) -> str:
    entity = str(type_name or "").strip().replace("StandardODATA.", "")
    if entity.startswith(("Document_", "Catalog_")):
        return entity
    return ""


def format_basis_document_label(entity: str, row: dict[str, Any]) -> str:
    number = str(row.get("Number") or "").strip()
    description = str(row.get("Description") or "").strip()
    if entity == INCOMING_CORRESPONDENCE_DOCUMENT and number:
        if number.casefold().startswith("вх."):
            return number
        return f"вх.{number}"
    return number or description


def resolve_basis_labels(
    session: requests.Session,
    parents: dict[str, dict[str, Any]] | list[dict[str, Any]],
    *,
    config: ODataConfig = CONFIG,
) -> dict[str, str]:
    """GUID Основание + Основание_Type → человекочитаемая метка (номер/вх.номер)."""
    parent_rows = parents.values() if isinstance(parents, dict) else parents
    keys_by_entity: dict[str, set[str]] = {}
    for parent in parent_rows:
        basis = str(parent.get("Основание") or "").strip()
        if not looks_like_guid(basis) or is_empty_key(basis):
            continue
        entity = odata_entity_from_type(parent.get("Основание_Type"))
        if not entity:
            continue
        keys_by_entity.setdefault(entity, set()).add(basis)

    labels: dict[str, str] = {}
    for entity, keys in keys_by_entity.items():
        try:
            rows = load_documents_for_keys(
                session,
                keys,
                entity=entity,
                config=config,
                select_fields="Ref_Key,Number",
            )
        except Exception as exc:  # noqa: BLE001 — резолв основания не должен валить весь dashboard
            # Основание останется пустым → в UI покажется номер поручения.
            logger.warning(
                "resolve_basis_labels_failed",
                entity=entity,
                keys=len(keys),
                error=str(exc),
            )
            continue
        for key, row in rows.items():
            label = format_basis_document_label(entity, row)
            if label:
                labels[key] = label
    return labels


def resolve_poruchenie_basis(
    parent: dict[str, Any],
    *,
    basis_labels: dict[str, str] | None = None,
) -> str:
    raw = str(parent.get("Основание") or "").strip()
    if not raw or is_empty_key(raw):
        return ""
    if looks_like_guid(raw):
        return (basis_labels or {}).get(raw, "")
    return raw


def _business_days_until(due: date, *, today: date) -> int:
    """Рабочие дни (пн–пт) от today до due. Сегодня → 0; просрочка → отрицательное."""
    if due == today:
        return 0
    step = 1 if due > today else -1
    days = 0
    current = today
    while current != due:
        current += timedelta(days=step)
        if current.weekday() < 5:
            days += step
    return days


def compute_priority(
    *,
    due_date: datetime | None,
    confirmed: bool = False,
    completed: bool = False,
    has_file: bool = False,
    manager: str = "",
    now: datetime,
) -> str:
    """Приоритет по ближайшему сроку задачи (рабочие дни).

    - Критический: просрочка или срок через 0–3 р.д.
    - Высокий: срок через 4–5 р.д.
    - Низкий: больше 5 р.д. (дальше недели по рабочим) или срока нет.

    Параметры confirmed/completed/has_file/manager сохранены для совместимости
    вызовов и больше не влияют на расчёт.
    """
    del confirmed, completed, has_file, manager
    if due_date is None:
        return "Низкий"

    days = _business_days_until(start_of_day(due_date).date(), today=start_of_day(now).date())
    if days <= PRIORITY_CRITICAL_BUSINESS_DAYS:
        return "Критический"
    if days <= PRIORITY_HIGH_BUSINESS_DAYS:
        return "Высокий"
    return "Низкий"


def normalize_poruchenie_task_row(
    row: dict[str, Any],
    *,
    users: dict[str, dict[str, Any]],
    persons: dict[str, dict[str, Any]],
    manager_fio: str,
    now: datetime,
    department: str = "",
) -> dict[str, Any]:
    due_date = parse_onec_datetime(row.get("СрокИсполнения"))
    overdue = due_date is not None and due_date < now
    responsible = persons.get(row.get("ОтветственноеЛицо_Key") or "", {})
    if not responsible:
        responsible = users.get(row.get("ОтветственноеЛицо_Key") or "", {})

    return {
        "item_type": "poruchenie_task",
        "line_number": row.get("LineNumber"),
        "activity": row.get("Мероприятие") or "",
        "responsible": person_description(responsible) or user_description(responsible),
        "responsible_key": str(row.get("ОтветственноеЛицо_Key") or "").strip() or None,
        "department": department,
        "due_date": row.get("СрокИсполнения"),
        "overdue": overdue,
        "has_file": "Нет",
        "priority": compute_priority(
            due_date=due_date,
            confirmed=overdue,
            completed=overdue,
            has_file=False,
            manager=manager_fio,
            now=now,
        ),
    }


def build_poruchenie_response_signal(
    parent: dict[str, Any],
    task_rows: list[dict[str, Any]],
    artifact_files: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Return a cautious document-level signal, never an execution confirmation.

    1C publishes attachments for the whole поручение rather than an individual
    activity. A file changed by a responsible user is useful review evidence,
    but cannot prove which activity it answers or that the activity is complete.
    """

    responsible_keys = {
        str(row.get("ОтветственноеЛицо_Key") or "").strip()
        for row in task_rows
        if not is_empty_key(row.get("ОтветственноеЛицо_Key"))
    }
    document_date = parse_onec_datetime(parent.get("Date"))
    response_files: list[dict[str, Any]] = []
    for artifact in artifact_files or []:
        actor_keys = {
            str(artifact.get("author_key") or "").strip(),
            str(artifact.get("modified_by_key") or "").strip(),
        }
        if not responsible_keys.intersection(actor_keys):
            continue
        changed_at = parse_onec_datetime(
            artifact.get("modified_at") or artifact.get("created_at")
        )
        if document_date is not None and changed_at is not None and changed_at < document_date:
            continue
        response_files.append(artifact)

    if not response_files:
        return {
            "response_signal_status": "not_detected",
            "response_signal": "Материалы от ответственного не обнаружены",
            "response_signal_reason": (
                "1С не публикует ответ или статус отдельного мероприятия; "
                "подходящих документных вложений не найдено."
            ),
            "response_materials_count": 0,
            "response_materials_updated_at": None,
        }

    timestamps = [
        parse_onec_datetime(artifact.get("modified_at") or artifact.get("created_at"))
        for artifact in response_files
    ]
    latest = max((value for value in timestamps if value is not None), default=None)
    count = len(response_files)
    return {
        "response_signal_status": "materials_from_responsible",
        "response_signal": "Есть материалы от ответственного",
        "response_signal_reason": (
            f"Найдено вложений: {count}. Это документный признак: 1С не связывает "
            "файл с конкретным мероприятием и не подтверждает его выполнение."
        ),
        "response_materials_count": count,
        "response_materials_updated_at": latest.isoformat(sep="T") if latest else None,
    }


def document_effective_due_date(
    parent: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> datetime | None:
    """Минимальный срок мероприятий; иначе СрокПолногоУстраненияНарушений документа."""
    due_dates: list[datetime] = []
    for task in tasks:
        parsed = parse_onec_datetime(task.get("due_date"))
        if parsed is not None:
            due_dates.append(parsed)
    if due_dates:
        return min(due_dates)
    return parse_onec_datetime(parent.get("СрокПолногоУстраненияНарушений"))


def document_is_overdue(
    *,
    status: str | None,
    due_date: datetime | None,
    as_of: date,
) -> bool:
    if is_closed_document_status(status):
        return False
    if due_date is None:
        return False
    return due_date.date() < as_of


def normalize_poruchenie_document(
    parent: dict[str, Any],
    *,
    users: dict[str, dict[str, Any]],
    tasks: list[dict[str, Any]],
    artifact_files: list[dict[str, Any]] | None = None,
    response_signal: dict[str, Any] | None = None,
    basis_labels: dict[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    manager = users.get(parent.get("Руководитель_Key") or "", {})
    secretary = users.get(parent.get("СекретарьРК_Key") or "", {})
    reporter = users.get(parent.get("КтоДоложитОЗавершенииМероприятий_Key") or "", {})
    raw_basis = str(parent.get("Основание") or "").strip()
    current = (now or datetime.now()).replace(microsecond=0)
    due_date = document_effective_due_date(parent, tasks)
    status = parent.get("Статус")

    return {
        "item_type": "poruchenie",
        "document_ref": parent.get("Ref_Key"),
        "document_number": parent.get("Number"),
        "document_date": parent.get("Date"),
        "source_revision": parent.get("DataVersion") or "",
        "mapping_context_fingerprint": document_mapping_context_fingerprint(
            {"document_ref": parent.get("Ref_Key"), "tasks": tasks}
        ),
        "subject": parent.get("ОЧем") or "",
        "status": status,
        "basis": resolve_poruchenie_basis(parent, basis_labels=basis_labels),
        "basis_ref": raw_basis if looks_like_guid(raw_basis) and not is_empty_key(raw_basis) else "",
        "basis_type": odata_entity_from_type(parent.get("Основание_Type")),
        "manager": user_description(manager),
        "secretary": user_description(secretary),
        "reviewer": user_description(secretary),
        "reporter": user_description(reporter),
        "artifact_files": artifact_files or [],
        **(response_signal or {}),
        "due_date": due_date.isoformat(sep="T") if due_date else None,
        "overdue": document_is_overdue(
            status=status,
            due_date=due_date,
            as_of=current.date(),
        ),
        "tasks_count": len(tasks),
        "tasks": tasks,
    }


def group_porucheniya_documents(
    parents: dict[str, dict[str, Any]],
    tabular_rows: list[dict[str, Any]],
    *,
    users: dict[str, dict[str, Any]],
    persons: dict[str, dict[str, Any]],
    departments_by_responsible: dict[str, str],
    now: datetime,
    artifact_files_by_document: dict[str, list[dict[str, Any]]] | None = None,
    basis_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows_by_document: dict[str, list[dict[str, Any]]] = {}
    for row in tabular_rows:
        document_ref = row.get("Ref_Key") or ""
        if document_ref:
            rows_by_document.setdefault(document_ref, []).append(row)

    documents: list[dict[str, Any]] = []
    sorted_refs = sorted(
        parents.keys(),
        key=lambda ref: parse_onec_datetime(parents[ref].get("Date")) or datetime.min,
        reverse=True,
    )
    for document_ref in sorted_refs:
        parent = parents[document_ref]
        manager_fio = user_description(users.get(parent.get("Руководитель_Key") or "", {}))
        document_rows = rows_by_document.get(document_ref, [])
        tasks: list[dict[str, Any]] = []
        for row in document_rows:
            responsible_key = row.get("ОтветственноеЛицо_Key") or ""
            tasks.append(
                normalize_poruchenie_task_row(
                    row,
                    users=users,
                    persons=persons,
                    manager_fio=manager_fio,
                    now=now,
                    department=departments_by_responsible.get(responsible_key, ""),
                )
            )
        artifact_files = (artifact_files_by_document or {}).get(document_ref, [])
        documents.append(
            normalize_poruchenie_document(
                parent,
                users=users,
                tasks=sort_items_by_due_date(tasks),
                artifact_files=artifact_files,
                response_signal=build_poruchenie_response_signal(
                    parent,
                    document_rows,
                    artifact_files,
                ),
                basis_labels=basis_labels,
                now=now,
            )
        )

    return documents


def sort_documents_by_latest_due_date(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(document: dict[str, Any]) -> datetime:
        latest = datetime.min
        for task in document.get("tasks") or []:
            parsed = parse_onec_datetime(task.get("due_date"))
            if parsed and parsed > latest:
                latest = parsed
        if latest != datetime.min:
            return latest
        return parse_onec_datetime(document.get("document_date")) or datetime.min

    return sorted(documents, key=sort_key, reverse=True)


def flatten_protocol_tasks(protocol_documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for document in protocol_documents:
        for task in document.get("tasks") or []:
            items.append(
                {
                    **task,
                    "protocol_ref": document.get("document_ref"),
                    "document_number": document.get("document_number"),
                    "document_date": document.get("document_date"),
                    "topic": document.get("topic"),
                    "subject": document.get("subject"),
                    "status": document.get("status"),
                    "manager": document.get("manager"),
                    "reviewer": document.get("reviewer"),
                }
            )
    return items


def flatten_all_tasks(
    porucheniya_documents: list[dict[str, Any]],
    protocol_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for document in porucheniya_documents:
        for task in document.get("tasks") or []:
            items.append(
                {
                    **task,
                    "document_ref": document.get("document_ref"),
                    "document_number": document.get("document_number"),
                    "document_date": document.get("document_date"),
                    "subject": document.get("subject"),
                    "manager": document.get("manager"),
                    "secretary": document.get("secretary"),
                }
            )
    items.extend(flatten_protocol_tasks(protocol_documents))
    return sort_items_by_due_date(items)


def filter_protocol_documents_by_manager_fio(
    documents: list[dict[str, Any]],
    manager_fio: str,
) -> list[dict[str, Any]]:
    normalized_manager = manager_fio.strip()
    return [
        document
        for document in documents
        if fio_matches(document.get("manager"), normalized_manager)
    ]


def filter_porucheniya_documents_by_manager_fio(
    documents: list[dict[str, Any]],
    manager_fio: str,
) -> list[dict[str, Any]]:
    normalized_manager = manager_fio.strip()
    return [
        document
        for document in documents
        if fio_matches(document.get("manager"), normalized_manager)
    ]


def filter_open_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Оставляет только документы, требующие контроля в Action Tracker."""
    return [
        document
        for document in documents
        if not is_excluded_task_tracker_status(document.get("status"))
    ]


# alias для обратной совместимости тестов
normalize_poruchenie_row = normalize_poruchenie_task_row


def fetch_limited_rows(
    session: requests.Session,
    config: ODataConfig,
    *,
    entity: str,
    odata_filter: str,
    limit: int,
    orderby: str | None = None,
    offset: int = 0,
    select_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    order = f"&$orderby={quote(orderby, safe=', ')}" if orderby else ""
    skip = f"&$skip={max(0, int(offset))}" if offset > 0 else ""
    selected = (
        f"&$select={quote(','.join(select_fields), safe=',_')}"
        if select_fields
        else ""
    )
    url = (
        f"{entity_url(config.url, entity)}"
        f"?$filter={quote(odata_filter, safe='')}"
        f"{order}{skip}{selected}&$top={limit}&$format=json"
    )
    data = odata_get_json(session, url, timeout=config.timeout)
    return data.get("value") or []


_PORUCHENIE_SUMMARY_FIELDS = [
    "Ref_Key",
    "Number",
    "Date",
    "DataVersion",
    "Статус",
    "ОЧем",
    "Руководитель_Key",
    "СекретарьРК_Key",
    "КтоДоложитОЗавершенииМероприятий_Key",
    "Основание",
    "Основание_Type",
    "СрокПолногоУстраненияНарушений",
]
_PROTOCOL_SUMMARY_FIELDS = [
    "Ref_Key",
    "Number",
    "Date",
    "DataVersion",
    "Статус",
    "ТемаСовещания_Key",
    "Руководитель_Key",
    "Ответственный_Key",
    "Подготовил_Key",
]


def _fetch_open_document_headers(
    session: requests.Session,
    config: ODataConfig,
    *,
    entity: str,
    manager_keys: set[str],
    fields: list[str],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    odata_filter = build_open_documents_filter()
    if manager_keys:
        odata_filter = f"{odata_filter} and {build_manager_filter(manager_keys)}"
    return fetch_limited_rows(
        session,
        config,
        entity=entity,
        odata_filter=odata_filter,
        limit=limit,
        offset=offset,
        orderby="Date desc",
        select_fields=fields,
    )


_DOCUMENT_COUNT_CAP = 2000
_DOCUMENT_COUNT_FIELDS = ["Ref_Key", "Статус"]


def _open_document_refs(
    session: requests.Session,
    config: ODataConfig,
    *,
    entity: str,
    manager_keys: set[str],
) -> list[str]:
    """Return refs of open (non-excluded) documents of one kind for tab badges.

    Fetches only Ref_Key/Статус so the badge counters stay cheap, and applies the
    same «Принято»/closed exclusion used when building the visible page.
    """

    rows = _fetch_open_document_headers(
        session,
        config,
        entity=entity,
        manager_keys=manager_keys,
        fields=_DOCUMENT_COUNT_FIELDS,
        limit=_DOCUMENT_COUNT_CAP,
        offset=0,
    )
    return [
        str(row.get("Ref_Key"))
        for row in rows
        if row.get("Ref_Key") and not is_excluded_task_tracker_status(row.get("Статус"))
    ]


def _count_poruchenie_activities(
    session: requests.Session,
    config: ODataConfig,
    document_refs: list[str],
) -> int:
    """Count poruchenie activities (one tabular row = one мероприятие)."""

    if not document_refs:
        return 0
    try:
        rows = fetch_tabular_rows_for_document_keys(session, config, set(document_refs))
        return len(rows)
    except Exception:  # noqa: BLE001
        logger.warning("porucheniya_summary_activity_count_failed")
        return 0


def protocol_register_row_is_open(row: dict[str, Any]) -> bool:
    """True, если задача протокола ещё требует контроля (не подтверждена)."""
    return not bool(row.get("Подтверждена"))


def filter_protocol_refs_with_open_tasks(
    protocol_refs: list[str],
    register_rows: list[dict[str, Any]],
) -> tuple[list[str], int]:
    """Оставляет протоколы с ≥1 неподтверждённой задачей; считает такие задачи.

    Порядок refs сохраняется. Подтверждённые-only и пустые протоколы отбрасываются —
    иначе бейдж «Протоколы» раздувается черновиками и уже закрытыми пунктами.
    """
    rows_by_protocol: dict[str, list[dict[str, Any]]] = {}
    for row in register_rows:
        protocol_ref = str(row.get("Протокол_Key") or "")
        if protocol_ref:
            rows_by_protocol.setdefault(protocol_ref, []).append(row)

    active_refs: list[str] = []
    open_tasks = 0
    for protocol_ref in protocol_refs:
        open_rows = [
            row
            for row in rows_by_protocol.get(protocol_ref, [])
            if protocol_register_row_is_open(row)
        ]
        if not open_rows:
            continue
        active_refs.append(protocol_ref)
        open_tasks += len(open_rows)
    return active_refs, open_tasks


def _count_protocol_tasks(
    session: requests.Session,
    config: ODataConfig,
    protocol_refs: list[str],
) -> int:
    """Count open (unconfirmed) protocol tasks for tab badges."""

    if not protocol_refs:
        return 0
    try:
        rows = fetch_register_rows_for_protocol_keys(session, config, set(protocol_refs))
        _, open_tasks = filter_protocol_refs_with_open_tasks(protocol_refs, rows)
        return open_tasks
    except Exception:  # noqa: BLE001
        logger.warning("protocol_summary_task_count_failed")
        return 0


def _active_protocol_refs(
    session: requests.Session,
    config: ODataConfig,
    *,
    manager_keys: set[str],
) -> tuple[list[str], int]:
    """Refs of protocols under control + count of their open tasks."""

    protocol_refs = _open_document_refs(
        session, config, entity=PROTOCOL_DOCUMENT, manager_keys=manager_keys
    )
    if not protocol_refs:
        return [], 0
    try:
        rows = fetch_register_rows_for_protocol_keys(session, config, set(protocol_refs))
    except Exception:  # noqa: BLE001
        logger.warning("protocol_summary_active_refs_failed")
        return protocol_refs, 0
    return filter_protocol_refs_with_open_tasks(protocol_refs, rows)


def normalize_poruchenie_summary_document(
    parent: dict[str, Any],
    *,
    manager_fio: str,
) -> dict[str, Any]:
    return {
        "item_type": "poruchenie",
        "document_ref": parent.get("Ref_Key"),
        "document_number": parent.get("Number"),
        "document_date": parent.get("Date"),
        "source_revision": parent.get("DataVersion") or "",
        "subject": parent.get("ОЧем") or parent.get("Number") or "",
        "status": parent.get("Статус"),
        "manager": manager_fio,
        "tasks_count": None,
        "tasks": [],
        "artifact_files": [],
    }


def normalize_protocol_summary_document(
    protocol: dict[str, Any],
    *,
    manager_fio: str,
) -> dict[str, Any]:
    topic = str(protocol.get("ТемаСовещания") or "").strip()
    return {
        "item_type": "protocol",
        "document_ref": protocol.get("Ref_Key"),
        "document_number": protocol.get("Number"),
        "document_date": protocol.get("Date"),
        "source_revision": protocol.get("DataVersion") or "",
        "topic": topic,
        "subject": topic or protocol.get("Number") or "",
        "status": protocol.get("Статус"),
        "manager": manager_fio,
        "reviewer": "",
        "tasks_count": None,
        "tasks": [],
        "artifact_files": [],
    }


_SUMMARY_ONLY_RESPONSE_SIGNAL_FIELDS = (
    "response_signal",
    "response_signal_status",
    "response_signal_reason",
    "response_materials_count",
    "response_materials_updated_at",
)


def _strip_summary_only_artifact_state(document: dict[str, Any]) -> dict[str, Any]:
    """Do not turn missing lazy attachment metadata into a negative signal."""

    for key in _SUMMARY_ONLY_RESPONSE_SIGNAL_FIELDS:
        document.pop(key, None)
    document["artifact_files"] = []
    return document


def hydrate_poruchenie_summary_documents(
    session: requests.Session,
    parents: dict[str, dict[str, Any]],
    *,
    config: ODataConfig = CONFIG,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Add page-level task aggregates without loading attachment metadata."""

    if not parents:
        return []
    current = (now or datetime.now()).replace(microsecond=0)
    tabular_rows = fetch_tabular_rows_for_document_keys(session, config, set(parents))
    user_keys, person_keys = collect_lookup_keys(tabular_rows, parents)
    users = load_users_for_keys(session, user_keys, config=config)
    persons = load_persons_for_keys(session, person_keys, config=config)
    basis_labels = resolve_basis_labels(session, parents, config=config)
    documents = group_porucheniya_documents(
        parents,
        tabular_rows,
        users=users,
        persons=persons,
        departments_by_responsible={},
        artifact_files_by_document={},
        now=current,
        basis_labels=basis_labels,
    )
    return [_strip_summary_only_artifact_state(document) for document in documents]


def hydrate_protocol_summary_documents(
    session: requests.Session,
    protocols: dict[str, dict[str, Any]],
    *,
    config: ODataConfig = CONFIG,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Add page-level protocol task aggregates without file/OCR requests."""

    if not protocols:
        return []
    current = (now or datetime.now()).replace(microsecond=0)
    register_rows = fetch_register_rows_for_protocol_keys(session, config, set(protocols))
    user_keys, person_keys, topic_keys = collect_protocol_lookup_keys(register_rows, protocols)
    users = load_users_for_keys(session, user_keys, config=config)
    persons = load_persons_for_keys(session, person_keys, config=config)
    topics = load_documents_for_keys(
        session,
        topic_keys,
        entity=TOPIC_CATALOG,
        config=config,
    )
    documents = group_protocol_documents(
        protocols,
        register_rows,
        users=users,
        persons=persons,
        topics=topics,
        departments_by_responsible={},
        artifact_files_by_document={},
        now=current,
    )
    return [_strip_summary_only_artifact_state(document) for document in documents]


def query_porucheniya_summary(
    *,
    author_fio: str,
    page: int = 1,
    size: int = 50,
    document_kind: str | None = None,
    include_aggregates: bool = False,
    config: ODataConfig = CONFIG,
) -> dict[str, Any]:
    """Read document headers, optionally enriching the visible page with task aggregates."""

    normalized_fio = author_fio.strip()
    if not normalized_fio:
        raise ValueError("author_fio is required")
    if page < 1:
        raise ValueError("page must be >= 1")
    if size < 1:
        raise ValueError("size must be >= 1")
    if document_kind not in {None, "poruchenie", "protocol"}:
        raise ValueError("document_kind must be poruchenie or protocol")

    session = create_session(config)
    manager_keys = resolve_manager_keys_for_fio(session, normalized_fio, config=config)
    offset = (page - 1) * size
    window_size = size + 1
    candidates: list[dict[str, Any]] = []
    porucheniya_by_ref: dict[str, dict[str, Any]] = {}
    protocols_by_ref: dict[str, dict[str, Any]] = {}
    active_protocol_refs: list[str] | None = None
    active_protocol_task_count: int | None = None

    def _ensure_active_protocols() -> tuple[list[str], int]:
        nonlocal active_protocol_refs, active_protocol_task_count
        if active_protocol_refs is None:
            active_protocol_refs, active_protocol_task_count = _active_protocol_refs(
                session, config, manager_keys=manager_keys
            )
        return active_protocol_refs, int(active_protocol_task_count or 0)

    if document_kind in {None, "poruchenie"}:
        porucheniya = _fetch_open_document_headers(
            session,
            config,
            entity=PORUCHENIYA_DOCUMENT,
            manager_keys=manager_keys,
            fields=_PORUCHENIE_SUMMARY_FIELDS,
            limit=(offset + window_size) if document_kind is None else window_size,
            offset=0 if document_kind is None else offset,
        )
        porucheniya_by_ref = {
            str(item.get("Ref_Key") or ""): item
            for item in porucheniya
            if item.get("Ref_Key") and not is_excluded_task_tracker_status(item.get("Статус"))
        }
        candidates.extend(
            normalize_poruchenie_summary_document(item, manager_fio=normalized_fio)
            for item in porucheniya
            if not is_excluded_task_tracker_status(item.get("Статус"))
        )

    if document_kind in {None, "protocol"}:
        # Протоколы: только с открытыми (неподтверждёнными) задачами. Пагинацию
        # делаем в памяти — OData не знает про регистр задач.
        active_refs, _ = _ensure_active_protocols()
        active_ref_set = set(active_refs)
        protocols = _fetch_open_document_headers(
            session,
            config,
            entity=PROTOCOL_DOCUMENT,
            manager_keys=manager_keys,
            fields=_PROTOCOL_SUMMARY_FIELDS,
            limit=_DOCUMENT_COUNT_CAP,
            offset=0,
        )
        protocols = [
            item
            for item in protocols
            if item.get("Ref_Key")
            and not is_excluded_task_tracker_status(item.get("Статус"))
            and str(item.get("Ref_Key")) in active_ref_set
        ]
        protocols_by_ref = {
            str(item.get("Ref_Key") or ""): item
            for item in protocols
            if item.get("Ref_Key")
        }
        candidates.extend(
            normalize_protocol_summary_document(item, manager_fio=normalized_fio)
            for item in protocols
        )

    candidates.sort(
        key=lambda item: parse_onec_datetime(item.get("document_date")) or datetime.min,
        reverse=True,
    )
    # poruchenie-only уже странируется через OData offset; protocol / mixed — здесь.
    if document_kind != "poruchenie":
        candidates = candidates[offset : offset + window_size]
    has_more = len(candidates) > size
    documents = candidates[:size]
    if include_aggregates:
        selected_porucheniya = {
            document_ref: porucheniya_by_ref[document_ref]
            for document_ref in (
                str(item.get("document_ref") or "")
                for item in documents
                if item.get("item_type") == "poruchenie"
            )
            if document_ref in porucheniya_by_ref
        }
        selected_protocols = {
            document_ref: protocols_by_ref[document_ref]
            for document_ref in (
                str(item.get("document_ref") or "")
                for item in documents
                if item.get("item_type") == "protocol"
            )
            if document_ref in protocols_by_ref
        }
        hydrated_by_target = {
            (str(item.get("item_type") or ""), str(item.get("document_ref") or "")): item
            for item in [
                *hydrate_poruchenie_summary_documents(
                    session,
                    selected_porucheniya,
                    config=config,
                ),
                *hydrate_protocol_summary_documents(
                    session,
                    selected_protocols,
                    config=config,
                ),
            ]
        }
        documents = [
            hydrated_by_target.get(
                (str(item.get("item_type") or ""), str(item.get("document_ref") or "")),
                item,
            )
            for item in documents
        ]
    start, end = resolve_porucheniya_period(None, None)
    porucheniya_page_count = sum(
        1 for item in documents if item.get("item_type") == "poruchenie"
    )
    protocol_page_count = sum(
        1 for item in documents if item.get("item_type") == "protocol"
    )
    # Both tab badges must always show the totals per kind (documents and tasks),
    # even for the kind that is not currently paged. Counting tabular/register rows
    # is the lightweight part of the load (no attachments/LLM/hydration) and is only
    # done on the dashboard path (include_aggregates); delta-polling stays lean.
    if include_aggregates:
        poruchenie_refs = _open_document_refs(
            session, config, entity=PORUCHENIYA_DOCUMENT, manager_keys=manager_keys
        )
        protocol_refs, protocol_tasks_total = _ensure_active_protocols()
        porucheniya_total = len(poruchenie_refs)
        protocol_total = len(protocol_refs)
        porucheniya_tasks_total = _count_poruchenie_activities(session, config, poruchenie_refs)
    else:
        porucheniya_total = porucheniya_page_count
        protocol_total = protocol_page_count
        porucheniya_tasks_total = 0
        protocol_tasks_total = 0
    return {
        "author_fio": normalized_fio,
        "page": page,
        "size": size,
        "has_more": has_more,
        "document_kind": document_kind,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "porucheniya": [item for item in documents if item.get("item_type") == "poruchenie"],
        "protocols": [item for item in documents if item.get("item_type") == "protocol"],
        "counts": {
            "porucheniya_documents": porucheniya_total,
            "porucheniya_tasks": porucheniya_tasks_total,
            "protocol_documents": protocol_total,
            "protocol_tasks": protocol_tasks_total,
            "total_tasks": porucheniya_tasks_total + protocol_tasks_total,
        },
    }


MANAGER_FETCH_POOL_MULTIPLIER = 5
MANAGER_FETCH_POOL_MIN = 100
MANAGER_FETCH_POOL_MAX = 1000


def build_task_period_filter(period_start: date, period_end: date) -> str:
    """Legacy: фильтр по сроку (для CLI/тестов; основная выборка по статусу)."""
    return (
        f"СрокИсполнения ge {format_odata_datetime(period_start)} "
        f"and СрокИсполнения le {format_odata_datetime(period_end, end=True)}"
    )


def build_document_period_filter(period_start: date, period_end: date) -> str:
    """Legacy: фильтр по дате документа (основная выборка — по открытому статусу)."""
    return (
        f"Date ge {format_odata_datetime(period_start)} "
        f"and Date le {format_odata_datetime(period_end, end=True)} "
        f"and DeletionMark eq false"
    )


def normalize_document_status_key(value: str | None) -> str:
    # OData может вернуть обычные/неразрывные пробелы или переводы строк.
    # split() нормализует любой Unicode-пробельный символ.
    return "".join(str(value or "").casefold().split())


def is_closed_document_status(value: str | None) -> bool:
    """True, если статус документа — закрытый («Закрыт» / «Принято и закрыто»)."""
    key = normalize_document_status_key(value)
    if not key:
        return False
    if key in _CLOSED_STATUS_KEYS:
        return True
    # На случай вариантов вроде «Принято  и  закрыто»
    return key.startswith("принят") and "закрыт" in key


def is_excluded_task_tracker_status(value: str | None) -> bool:
    """True, если документ не должен отображаться в Action Tracker или идти в LLM."""
    key = normalize_document_status_key(value)
    return bool(key) and (
        key in _EXCLUDED_TASK_TRACKER_STATUS_KEYS or is_closed_document_status(value)
    )


def build_open_documents_filter() -> str:
    """OData: только не удалённые документы (дата не участвует).

    Фильтр по Статус в OData 1С часто даёт 400 (enum / пробелы в значении),
    поэтому статусы, исключённые из контроля, отсекаем в Python через
    filter_open_documents.
    """
    return "DeletionMark eq false"


build_period_filter = build_task_period_filter


def fetch_porucheniya_documents(
    session: requests.Session,
    config: ODataConfig,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    limit: int,
    manager_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    del period_start, period_end
    odata_filter = build_open_documents_filter()
    if manager_keys:
        odata_filter = f"{odata_filter} and {build_manager_filter(manager_keys)}"
    return fetch_limited_rows(
        session,
        config,
        entity=PORUCHENIYA_DOCUMENT,
        odata_filter=odata_filter,
        limit=limit,
        orderby="Date desc",
    )


def fetch_tabular_rows_for_document_keys(
    session: requests.Session,
    config: ODataConfig,
    document_keys: set[str],
) -> list[dict[str, Any]]:
    keys = [key for key in document_keys if not is_empty_key(key)]
    if not keys:
        return []

    rows: list[dict[str, Any]] = []
    chunk_size = 10
    for offset in range(0, len(keys), chunk_size):
        chunk = keys[offset : offset + chunk_size]
        filter_expr = " or ".join(f"Ref_Key eq guid'{key}'" for key in chunk)
        url = (
            f"{entity_url(config.url, PORUCHENIYA_TABULAR)}"
            f"?$filter={quote(filter_expr, safe='')}"
            f"&$orderby=LineNumber asc&$format=json"
        )
        for row in fetch_all(session, url, page=100, timeout=config.timeout):
            rows.append(row)
    return rows


def fetch_porucheniya_rows(
    session: requests.Session,
    config: ODataConfig,
    *,
    period_start: date,
    period_end: date,
    limit: int,
) -> list[dict[str, Any]]:
    return fetch_limited_rows(
        session,
        config,
        entity=PORUCHENIYA_TABULAR,
        odata_filter=build_task_period_filter(period_start, period_end),
        limit=limit,
        orderby="СрокИсполнения desc",
    )


def fetch_protocol_documents(
    session: requests.Session,
    config: ODataConfig,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    limit: int,
    manager_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    del period_start, period_end
    odata_filter = build_open_documents_filter()
    if manager_keys:
        odata_filter = f"{odata_filter} and {build_manager_filter(manager_keys)}"
    return fetch_limited_rows(
        session,
        config,
        entity=PROTOCOL_DOCUMENT,
        odata_filter=odata_filter,
        limit=limit,
        orderby="Date desc",
    )


def fetch_register_rows_for_protocol_keys(
    session: requests.Session,
    config: ODataConfig,
    protocol_keys: set[str],
) -> list[dict[str, Any]]:
    keys = [key for key in protocol_keys if not is_empty_key(key)]
    if not keys:
        return []

    rows: list[dict[str, Any]] = []
    chunk_size = 8
    for offset in range(0, len(keys), chunk_size):
        chunk = keys[offset : offset + chunk_size]
        filter_expr = " or ".join(f"Протокол_Key eq guid'{key}'" for key in chunk)
        url = (
            f"{entity_url(config.url, PROTOCOL_TASKS_REGISTER)}"
            f"?$filter={quote(filter_expr, safe='')}"
            f"&$orderby=НомерПунктаПротокола asc&$format=json"
        )
        for row in fetch_all(session, url, page=200, timeout=config.timeout):
            rows.append(row)
    return rows


def fetch_protocol_task_rows(
    session: requests.Session,
    config: ODataConfig,
    *,
    period_start: date,
    period_end: date,
    limit: int,
) -> list[dict[str, Any]]:
    return fetch_limited_rows(
        session,
        config,
        entity=PROTOCOL_TASKS_REGISTER,
        odata_filter=build_task_period_filter(period_start, period_end),
        limit=limit,
        orderby="СрокИсполнения desc",
    )


def filter_rows_by_manager(
    rows: list[dict[str, Any]],
    parents: dict[str, dict[str, Any]],
    manager_keys: set[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        parent = parents.get(row.get("Ref_Key") or "", {})
        if parent.get("Руководитель_Key") in manager_keys:
            filtered.append(row)
        if len(filtered) >= limit:
            break
    return filtered


def filter_protocol_tasks_by_manager(
    rows: list[dict[str, Any]],
    protocols: dict[str, dict[str, Any]],
    manager_keys: set[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        protocol = protocols.get(row.get("Протокол_Key") or "", {})
        if protocol.get("Руководитель_Key") in manager_keys:
            filtered.append(row)
        if len(filtered) >= limit:
            break
    return filtered


def _collect_protocol_header_lookup_keys(
    protocol: dict[str, Any],
    *,
    user_keys: set[str],
    person_keys: set[str],
    topic_keys: set[str],
) -> None:
    for key_name in ("Руководитель_Key", "Ответственный_Key", "Подготовил_Key"):
        key = protocol.get(key_name)
        if not is_empty_key(key):
            user_keys.add(key)
        if key_name == "Ответственный_Key" and not is_empty_key(key):
            person_keys.add(key)
    topic_key = protocol.get("ТемаСовещания_Key")
    if not is_empty_key(topic_key):
        topic_keys.add(topic_key)


def collect_protocol_lookup_keys(
    rows: list[dict[str, Any]],
    protocols: dict[str, dict[str, Any]],
) -> tuple[set[str], set[str], set[str]]:
    user_keys: set[str] = set()
    person_keys: set[str] = set()
    topic_keys: set[str] = set()

    for protocol in protocols.values():
        _collect_protocol_header_lookup_keys(
            protocol,
            user_keys=user_keys,
            person_keys=person_keys,
            topic_keys=topic_keys,
        )

    for row in rows:
        protocol = protocols.get(row.get("Протокол_Key") or "", {})
        for key_name in ("Ответственный_Key", "Автор_Key"):
            key = row.get(key_name)
            if not is_empty_key(key):
                user_keys.add(key)
                person_keys.add(key)
        topic_key = row.get("ТемаСовещания_Key") or protocol.get("ТемаСовещания_Key")
        if not is_empty_key(topic_key):
            topic_keys.add(topic_key)

    return user_keys, person_keys, topic_keys


def normalize_protocol_register_task_row(
    row: dict[str, Any],
    protocol: dict[str, Any],
    *,
    users: dict[str, dict[str, Any]],
    persons: dict[str, dict[str, Any]],
    manager_fio: str,
    now: datetime,
    department: str = "",
) -> dict[str, Any]:
    due_date = parse_onec_datetime(row.get("СрокИсполнения"))
    completed = bool(row.get("Выполнена"))
    confirmed = bool(row.get("Подтверждена"))
    overdue = due_date is not None and due_date < now and not completed
    responsible = persons.get(row.get("Ответственный_Key") or "", {})
    if not responsible:
        responsible = users.get(row.get("Ответственный_Key") or "", {})
    has_file = row_has_file(row)
    comment = row.get("Комментарий") or ""
    note = row.get("Примечание") or ""

    return {
        "item_type": "protocol_task",
        "task_id": row.get("ИдентификаторЗадачи"),
        # GUID бизнес-процесса ДО (рядом с ним создаётся ЗадачаИсполнителя).
        "process_id": row.get("ПроцессID"),
        "topic_key": row.get("ТемаСовещания_Key") or protocol.get("ТемаСовещания_Key"),
        "protocol_item_number": row.get("НомерПунктаПротокола"),
        "activity": row.get("Задача") or "",
        "responsible": person_description(responsible) or user_description(responsible),
        "responsible_key": str(row.get("Ответственный_Key") or "").strip() or None,
        "department": department,
        "assigned_date": row.get("ДатаПостановкиЗадачи"),
        "due_date": row.get("СрокИсполнения"),
        "completed_date": row.get("ДатаИсполнения"),
        "sent": bool(row.get("Отправлена")),
        "completed": completed,
        "confirmed": confirmed,
        "comment": comment,
        "note": note,
        **extract_postponement_fields(note=note, comment=comment),
        "overdue": overdue,
        "has_file": format_has_file(has_file),
        "priority": compute_priority(
            due_date=due_date,
            confirmed=confirmed,
            completed=completed,
            has_file=has_file,
            manager=manager_fio,
            now=now,
        ),
    }


def normalize_protocol_document(
    protocol: dict[str, Any],
    *,
    users: dict[str, dict[str, Any]],
    persons: dict[str, dict[str, Any]],
    topics: dict[str, dict[str, Any]],
    tasks: list[dict[str, Any]],
    artifact_files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manager = users.get(protocol.get("Руководитель_Key") or "", {})
    reviewer_entity = persons.get(protocol.get("Ответственный_Key") or "", {})
    if not reviewer_entity:
        reviewer_entity = users.get(protocol.get("Ответственный_Key") or "", {})
    topic = topics.get(protocol.get("ТемаСовещания_Key") or "", {})
    topic_name = entity_description(topic)

    return {
        "item_type": "protocol",
        "document_ref": protocol.get("Ref_Key"),
        "document_number": protocol.get("Number"),
        "document_date": protocol.get("Date"),
        "source_revision": protocol.get("DataVersion") or "",
        "mapping_context_fingerprint": document_mapping_context_fingerprint(
            {"document_ref": protocol.get("Ref_Key"), "tasks": tasks}
        ),
        "topic": topic_name,
        "subject": topic_name,
        "status": protocol.get("Статус"),
        "manager": user_description(manager),
        "reviewer": person_description(reviewer_entity) or user_description(reviewer_entity),
        "tasks_count": len(tasks),
        "tasks": tasks,
        "artifact_files": artifact_files or [],
    }


def group_protocol_documents(
    protocols: dict[str, dict[str, Any]],
    register_rows: list[dict[str, Any]],
    *,
    users: dict[str, dict[str, Any]],
    persons: dict[str, dict[str, Any]],
    topics: dict[str, dict[str, Any]],
    departments_by_responsible: dict[str, str],
    now: datetime,
    artifact_files_by_document: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    rows_by_protocol: dict[str, list[dict[str, Any]]] = {}
    for row in register_rows:
        protocol_ref = row.get("Протокол_Key") or ""
        if protocol_ref:
            rows_by_protocol.setdefault(protocol_ref, []).append(row)

    documents: list[dict[str, Any]] = []
    sorted_refs = sorted(
        protocols.keys(),
        key=lambda ref: parse_onec_datetime(protocols[ref].get("Date")) or datetime.min,
        reverse=True,
    )
    for protocol_ref in sorted_refs:
        protocol = protocols[protocol_ref]
        manager_fio = user_description(users.get(protocol.get("Руководитель_Key") or "", {}))
        tasks: list[dict[str, Any]] = []
        for row in rows_by_protocol.get(protocol_ref, []):
            responsible_key = row.get("Ответственный_Key") or ""
            tasks.append(
                normalize_protocol_register_task_row(
                    row,
                    protocol,
                    users=users,
                    persons=persons,
                    manager_fio=manager_fio,
                    now=now,
                    department=departments_by_responsible.get(responsible_key, ""),
                )
            )
        documents.append(
            normalize_protocol_document(
                protocol,
                users=users,
                persons=persons,
                topics=topics,
                tasks=sort_items_by_due_date(tasks),
                artifact_files=(artifact_files_by_document or {}).get(protocol_ref, []),
            )
        )

    return documents


def normalize_protocol_task_row(
    row: dict[str, Any],
    protocol: dict[str, Any],
    *,
    topics: dict[str, dict[str, Any]],
    users: dict[str, dict[str, Any]],
    persons: dict[str, dict[str, Any]],
    now: datetime,
    department: str = "",
) -> dict[str, Any]:
    """Плоское представление задачи протокола (legacy / flatten)."""
    manager_fio = user_description(users.get(protocol.get("Руководитель_Key") or "", {}))
    task = normalize_protocol_register_task_row(
        row,
        protocol,
        users=users,
        persons=persons,
        manager_fio=manager_fio,
        now=now,
        department=department,
    )
    topic_key = task.get("topic_key") or protocol.get("ТемаСовещания_Key")
    topic_name = entity_description(topics.get(topic_key or "", {}))
    author = users.get(row.get("Автор_Key") or "", {})

    return {
        **task,
        "protocol_ref": protocol.get("Ref_Key") or row.get("Протокол_Key"),
        "document_number": protocol.get("Number"),
        "document_date": protocol.get("Date"),
        "topic": topic_name,
        "subject": topic_name,
        "status": protocol.get("Статус"),
        "author": user_description(author),
        "manager": manager_fio,
    }


def sort_items_by_due_date(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> datetime:
        parsed = parse_onec_datetime(item.get("due_date"))
        return parsed or datetime.min

    return sorted(items, key=sort_key, reverse=True)


def filter_items_by_manager_fio(items: list[dict[str, Any]], manager_fio: str) -> list[dict[str, Any]]:
    normalized_manager = manager_fio.strip()
    return [
        item
        for item in items
        if fio_matches(item.get("manager"), normalized_manager)
        or fio_matches(item.get("author"), normalized_manager)
    ]


def collect_lookup_keys(
    rows: list[dict[str, Any]],
    parents: dict[str, dict[str, Any]],
) -> tuple[set[str], set[str]]:
    user_keys: set[str] = set()
    person_keys: set[str] = set()

    for parent in parents.values():
        if not is_empty_key(parent.get("Руководитель_Key")):
            user_keys.add(parent["Руководитель_Key"])
        if not is_empty_key(parent.get("СекретарьРК_Key")):
            user_keys.add(parent["СекретарьРК_Key"])
        if not is_empty_key(parent.get("КтоДоложитОЗавершенииМероприятий_Key")):
            user_keys.add(parent["КтоДоложитОЗавершенииМероприятий_Key"])

    for row in rows:
        if not is_empty_key(row.get("ОтветственноеЛицо_Key")):
            person_keys.add(row["ОтветственноеЛицо_Key"])
            user_keys.add(row["ОтветственноеЛицо_Key"])

    return user_keys, person_keys


def load_porucheniya_documents(
    session: requests.Session,
    config: ODataConfig,
    *,
    period_start: date,
    period_end: date,
    limit: int,
    fetch_limit: int,
    filter_manager_keys: set[str] | None,
    now: datetime,
    include_closed: bool = False,
) -> list[dict[str, Any]]:
    del fetch_limit
    parent_rows = fetch_porucheniya_documents(
        session,
        config,
        period_start=period_start,
        period_end=period_end,
        limit=limit,
        manager_keys=filter_manager_keys,
    )
    if not include_closed:
        # Фильтруем до запросов ТЧ, вложений и справочников: закрытые
        # и принятые поручения не должны попадать ни в Action Tracker,
        # ни в LLM-контекст.
        parent_rows = [
            row
            for row in parent_rows
            if not is_excluded_task_tracker_status(row.get("Статус"))
        ]
    parents = {
        row["Ref_Key"]: row
        for row in parent_rows
        if row.get("Ref_Key")
    }
    tabular_rows = fetch_tabular_rows_for_document_keys(
        session,
        config,
        set(parents.keys()),
    )
    user_keys, person_keys = collect_lookup_keys(tabular_rows, parents)
    users = load_users_for_keys(session, user_keys, config=config)
    persons = load_persons_for_keys(session, person_keys, config=config)
    responsible_keys = {
        row.get("ОтветственноеЛицо_Key")
        for row in tabular_rows
        if not is_empty_key(row.get("ОтветственноеЛицо_Key"))
    }
    departments_by_responsible = load_departments_for_responsible_keys(
        session,
        responsible_keys,
        users=users,
        persons=persons,
        config=config,
    )
    basis_labels = resolve_basis_labels(session, parents, config=config)
    artifact_files_by_document = load_attached_files_for_owner_keys(
        session,
        set(parents.keys()),
        entity=PORUCHENIYA_ATTACHED_FILES,
        config=config,
    )

    return group_porucheniya_documents(
        parents,
        tabular_rows,
        users=users,
        persons=persons,
        departments_by_responsible=departments_by_responsible,
        artifact_files_by_document=artifact_files_by_document,
        now=now,
        basis_labels=basis_labels,
    )


load_porucheniya_items = load_porucheniya_documents


def load_protocol_documents(
    session: requests.Session,
    config: ODataConfig,
    *,
    period_start: date,
    period_end: date,
    limit: int,
    fetch_limit: int,
    filter_manager_keys: set[str] | None,
    now: datetime,
    include_closed: bool = False,
) -> list[dict[str, Any]]:
    del fetch_limit
    parent_rows = fetch_protocol_documents(
        session,
        config,
        period_start=period_start,
        period_end=period_end,
        limit=limit,
        manager_keys=filter_manager_keys,
    )
    if not include_closed:
        parent_rows = [
            row
            for row in parent_rows
            if not is_excluded_task_tracker_status(row.get("Статус"))
        ]
    protocols = {
        row["Ref_Key"]: row
        for row in parent_rows
        if row.get("Ref_Key")
    }
    register_rows = fetch_register_rows_for_protocol_keys(
        session,
        config,
        set(protocols.keys()),
    )
    if not include_closed:
        active_refs, _ = filter_protocol_refs_with_open_tasks(
            [str(ref) for ref in protocols.keys()],
            register_rows,
        )
        active_ref_set = set(active_refs)
        protocols = {
            ref: row for ref, row in protocols.items() if str(ref) in active_ref_set
        }
        register_rows = [
            row
            for row in register_rows
            if str(row.get("Протокол_Key") or "") in active_ref_set
        ]
    user_keys, person_keys, topic_keys = collect_protocol_lookup_keys(register_rows, protocols)
    users = load_users_for_keys(session, user_keys, config=config)
    persons = load_persons_for_keys(session, person_keys, config=config)
    topics = load_documents_for_keys(
        session,
        topic_keys,
        entity=TOPIC_CATALOG,
        config=config,
    )
    responsible_keys = {
        row.get("Ответственный_Key")
        for row in register_rows
        if not is_empty_key(row.get("Ответственный_Key"))
    }
    departments_by_responsible = load_departments_for_responsible_keys(
        session,
        responsible_keys,
        users=users,
        persons=persons,
        config=config,
    )
    artifact_files_by_document = load_attached_files_for_owner_keys(
        session,
        set(protocols.keys()),
        entity=PROTOCOL_ATTACHED_FILES,
        config=config,
    )

    return group_protocol_documents(
        protocols,
        register_rows,
        users=users,
        persons=persons,
        topics=topics,
        departments_by_responsible=departments_by_responsible,
        artifact_files_by_document=artifact_files_by_document,
        now=now,
    )


load_protocol_task_items = load_protocol_documents


def fetch_document_by_ref(
    session: requests.Session,
    config: ODataConfig,
    *,
    entity: str,
    document_ref: str,
    manager_keys: set[str],
) -> dict[str, Any] | None:
    if not looks_like_guid(document_ref):
        raise ValueError("document_ref must be a 1C GUID")
    odata_filter = f"Ref_Key eq guid'{document_ref}' and {build_open_documents_filter()}"
    if manager_keys:
        odata_filter = f"{odata_filter} and {build_manager_filter(manager_keys)}"
    rows = fetch_limited_rows(
        session,
        config,
        entity=entity,
        odata_filter=odata_filter,
        limit=1,
    )
    return rows[0] if rows else None


def query_porucheniya_document_detail(
    *,
    author_fio: str,
    document_ref: str,
    document_kind: str,
    config: ODataConfig = CONFIG,
) -> dict[str, Any]:
    """Load activities and attachment metadata for exactly one accessible document."""

    normalized_fio = author_fio.strip()
    if not normalized_fio:
        raise ValueError("author_fio is required")
    if document_kind not in {"poruchenie", "protocol"}:
        raise ValueError("document_kind must be poruchenie or protocol")

    session = create_session(config)
    manager_keys = resolve_manager_keys_for_fio(session, normalized_fio, config=config)
    now = datetime.now().replace(microsecond=0)

    if document_kind == "poruchenie":
        parent = fetch_document_by_ref(
            session,
            config,
            entity=PORUCHENIYA_DOCUMENT,
            document_ref=document_ref,
            manager_keys=manager_keys,
        )
        if parent is None or is_excluded_task_tracker_status(parent.get("Статус")):
            raise LookupError("Поручение не найдено или не требует контроля.")
        parents = {document_ref: parent}
        tabular_rows = fetch_tabular_rows_for_document_keys(session, config, {document_ref})
        user_keys, person_keys = collect_lookup_keys(tabular_rows, parents)
        users = load_users_for_keys(session, user_keys, config=config)
        persons = load_persons_for_keys(session, person_keys, config=config)
        responsible_keys = {
            row.get("ОтветственноеЛицо_Key")
            for row in tabular_rows
            if not is_empty_key(row.get("ОтветственноеЛицо_Key"))
        }
        departments_by_responsible = load_departments_for_responsible_keys(
            session,
            responsible_keys,
            users=users,
            persons=persons,
            config=config,
        )
        basis_labels = resolve_basis_labels(session, parents, config=config)
        artifact_files_by_document = load_attached_files_for_owner_keys(
            session,
            {document_ref},
            entity=PORUCHENIYA_ATTACHED_FILES,
            config=config,
        )
        documents = group_porucheniya_documents(
            parents,
            tabular_rows,
            users=users,
            persons=persons,
            departments_by_responsible=departments_by_responsible,
            artifact_files_by_document=artifact_files_by_document,
            now=now,
            basis_labels=basis_labels,
        )
    else:
        protocol = fetch_document_by_ref(
            session,
            config,
            entity=PROTOCOL_DOCUMENT,
            document_ref=document_ref,
            manager_keys=manager_keys,
        )
        if protocol is None or is_excluded_task_tracker_status(protocol.get("Статус")):
            raise LookupError("Протокол не найден или не требует контроля.")
        protocols = {document_ref: protocol}
        register_rows = fetch_register_rows_for_protocol_keys(session, config, {document_ref})
        user_keys, person_keys, topic_keys = collect_protocol_lookup_keys(register_rows, protocols)
        users = load_users_for_keys(session, user_keys, config=config)
        persons = load_persons_for_keys(session, person_keys, config=config)
        topics = load_documents_for_keys(
            session,
            topic_keys,
            entity=TOPIC_CATALOG,
            config=config,
        )
        responsible_keys = {
            row.get("Ответственный_Key")
            for row in register_rows
            if not is_empty_key(row.get("Ответственный_Key"))
        }
        departments_by_responsible = load_departments_for_responsible_keys(
            session,
            responsible_keys,
            users=users,
            persons=persons,
            config=config,
        )
        artifact_files_by_document = load_attached_files_for_owner_keys(
            session,
            {document_ref},
            entity=PROTOCOL_ATTACHED_FILES,
            config=config,
        )
        documents = group_protocol_documents(
            protocols,
            register_rows,
            users=users,
            persons=persons,
            topics=topics,
            departments_by_responsible=departments_by_responsible,
            artifact_files_by_document=artifact_files_by_document,
            now=now,
        )

    if not documents:
        raise LookupError("Документ не найден.")
    return documents[0]


def resolve_porucheniya_period(
    period_start: date | str | None,
    period_end: date | str | None,
    *,
    today: date | None = None,
) -> tuple[date, date]:
    """Период по умолчанию — вчерашняя дата (один календарный день)."""
    yesterday = (today or date.today()) - timedelta(days=1)
    if period_start is None and period_end is None:
        return yesterday, yesterday
    end = parse_input_date(period_end, default=yesterday)
    start = parse_input_date(period_start, default=end)
    return start, end


def query_ast_porucheniya_documents(
    *,
    author_fio: str,
    limit: int = 500,
    include_closed: bool = True,
    as_of: date | datetime | None = None,
    config: ODataConfig = CONFIG,
) -> list[dict[str, Any]]:
    """Документы АСТ по руководителю (для снимков/недельного отчёта)."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    fio = (author_fio or "").strip()
    if not fio:
        raise ValueError("author_fio is required")

    if isinstance(as_of, datetime):
        now = as_of.replace(microsecond=0)
    elif isinstance(as_of, date):
        now = datetime(as_of.year, as_of.month, as_of.day, 18, 0, 0)
    else:
        now = datetime.now().replace(microsecond=0)

    session = create_session(config)
    start, end = resolve_porucheniya_period(None, None, today=now.date())
    filter_manager_keys = resolve_manager_keys_for_fio(session, fio, config=config)
    fetch_limit = min(
        max(limit * MANAGER_FETCH_POOL_MULTIPLIER, MANAGER_FETCH_POOL_MIN),
        MANAGER_FETCH_POOL_MAX,
    )
    documents = load_porucheniya_documents(
        session,
        config,
        period_start=start,
        period_end=end,
        limit=limit,
        fetch_limit=fetch_limit,
        filter_manager_keys=filter_manager_keys,
        now=now,
        include_closed=include_closed,
    )
    if not include_closed:
        documents = filter_open_documents(documents)
    documents = filter_porucheniya_documents_by_manager_fio(documents, fio)

    # Пересчитать overdue на as_of (на случай если now внутри load отличается).
    as_of_day = now.date()
    for document in documents:
        due = parse_onec_datetime(document.get("due_date"))
        document["overdue"] = document_is_overdue(
            status=document.get("status"),
            due_date=due,
            as_of=as_of_day,
        )
    return documents


def query_porucheniya(
    *,
    period_start: date | str | None = None,
    period_end: date | str | None = None,
    limit: int = 500,
    author_fio: str | None = None,
    config: ODataConfig = CONFIG,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be >= 1")

    start, end = resolve_porucheniya_period(period_start, period_end)
    if start > end:
        raise ValueError("period_start не может быть позже period_end")

    session = create_session(config)
    now = datetime.now().replace(microsecond=0)

    filter_manager_keys: set[str] | None = None
    selection_method = (
        f"OData: {PORUCHENIYA_DOCUMENT} + {PROTOCOL_DOCUMENT} "
        f"by open status (not closed)"
    )
    fetch_limit = limit
    if author_fio and author_fio.strip():
        filter_manager_keys = resolve_manager_keys_for_fio(session, author_fio, config=config)
        fetch_limit = min(
            max(limit * MANAGER_FETCH_POOL_MULTIPLIER, MANAGER_FETCH_POOL_MIN),
            MANAGER_FETCH_POOL_MAX,
        )
        selection_method = (
            f"OData: {PORUCHENIYA_DOCUMENT} + {PROTOCOL_DOCUMENT} "
            f"by open status, filter Руководитель (author_fio={author_fio.strip()})"
        )

    porucheniya_documents = load_porucheniya_documents(
        session,
        config,
        period_start=start,
        period_end=end,
        limit=limit,
        fetch_limit=fetch_limit,
        filter_manager_keys=filter_manager_keys,
        now=now,
    )
    protocol_documents = load_protocol_documents(
        session,
        config,
        period_start=start,
        period_end=end,
        limit=limit,
        fetch_limit=fetch_limit,
        filter_manager_keys=filter_manager_keys,
        now=now,
    )

    porucheniya_documents = filter_open_documents(porucheniya_documents)
    protocol_documents = filter_open_documents(protocol_documents)

    if author_fio and author_fio.strip():
        porucheniya_documents = filter_porucheniya_documents_by_manager_fio(
            porucheniya_documents,
            author_fio,
        )
        protocol_documents = filter_protocol_documents_by_manager_fio(
            protocol_documents,
            author_fio,
        )

    porucheniya_tasks_count = sum(
        len(document.get("tasks") or []) for document in porucheniya_documents
    )
    protocol_tasks_count = sum(
        len(document.get("tasks") or []) for document in protocol_documents
    )
    protocol_tasks = flatten_protocol_tasks(protocol_documents)
    items = flatten_all_tasks(porucheniya_documents, protocol_documents)
    counts = {
        "porucheniya_documents": len(porucheniya_documents),
        "porucheniya_tasks": porucheniya_tasks_count,
        "protocol_documents": len(protocol_documents),
        "protocol_tasks": protocol_tasks_count,
        "total_tasks": len(items),
    }

    return {
        "document_entity": PORUCHENIYA_DOCUMENT,
        "tabular_entity": PORUCHENIYA_TABULAR,
        "register_entity": PROTOCOL_TASKS_REGISTER,
        "protocol_entity": PROTOCOL_DOCUMENT,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "limit": limit,
        "count": counts["total_tasks"],
        "counts": counts,
        "author_fio": author_fio.strip() if author_fio and author_fio.strip() else None,
        "selection_method": selection_method,
        "porucheniya": porucheniya_documents,
        "protocols": protocol_documents,
        "protocol_tasks": protocol_tasks,
        "items": items,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Получить поручения из 1С через OData.",
    )
    parser.add_argument(
        "--start",
        help="Игнорируется: выборка по открытому статусу, не по дате",
    )
    parser.add_argument(
        "--end",
        help="Игнорируется: выборка по открытому статусу, не по дате",
    )
    parser.add_argument("--limit", type=int, default=500, help="Максимум документов каждого типа")
    parser.add_argument("--author-fio", help="Фильтр по ФИО руководителя поручения")
    parser.add_argument("-o", "--output", help="Путь к JSON-файлу результата")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    try:
        result = query_porucheniya(
            period_start=args.start,
            period_end=args.end,
            limit=args.limit,
            author_fio=args.author_fio,
        )
    except (requests.RequestException, RuntimeError, ValueError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(text)
        print(f"Сохранено: {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
