"""OData-backed 1C document tools for desktop (no COM)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.tools.ac.workers.onec_meeting_notes import (
    default_addressee,
    document_from_com32_row,
    meeting_params_from_row,
    note_from_com32_row,
    parse_note_period,
    person_needles,
)
from app.tools.onec_odata_invoke import fetch_odata_list, odata_rows

SERVICE_NOTE_ENTITY = "Document_ТД_СлужебнаяЗаписка"
INCOMING_ENTITY = "Document_ТД_ВходящаяКорреспонденция"

_SEARCH_ENTITIES: tuple[tuple[str, str, str], ...] = (
    (SERVICE_NOTE_ENTITY, "ТД_СлужебнаяЗаписка", "Служебная записка"),
    (INCOMING_ENTITY, "ТД_ВходящаяКорреспонденция", "Входящая корреспонденция"),
)


def _parse_iso_date(raw: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _odata_datetime(value: date, *, end_of_day: bool = False) -> str:
    if end_of_day:
        return f"datetime'{value.isoformat()}T23:59:59'"
    return f"datetime'{value.isoformat()}T00:00:00'"


def _escape_odata_string(value: str) -> str:
    return (value or "").replace("'", "''")


def _field_text(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if isinstance(value, dict):
        for key in ("Description", "Наименование", "Presentation", "Value"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
    name_key = f"{field}_Name"
    if row.get(name_key):
        return str(row.get(name_key) or "").strip()
    if value is None:
        return ""
    return str(value).strip()


def _row_to_com32(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "Number": row.get("Number"),
        "DocDate": row.get("Date"),
        "Theme": _field_text(row, "ТемаСлужебнойЗаписки"),
        "MeetingTopic": _field_text(row, "ТемаСовещания"),
        "Place": _field_text(row, "МестоПроведенияСовещания"),
        "DesiredDate": row.get("ЖелаемаяДатаПроведенияСовещания"),
        "StartTime": row.get("ВремяНачалаСовещания"),
        "EndTime": row.get("ВремяОкончанияСовещания"),
        "MeetingDate": row.get("ДатаПроведенияСовещания"),
        "MeetingKind": _field_text(row, "ВидСовещания"),
        "PsdLevel": row.get("НаУровнеПСД"),
        "Leader": _field_text(row, "РуководительСовещания"),
        "Priority": _field_text(row, "Приоритет"),
        "Schedule": _field_text(row, "Расписание"),
        "Purpose": _field_text(row, "ЦельПланаСовещания"),
        "Addressee": _field_text(row, "МенеджерКому"),
    }


def _matches_meeting_theme(text: str) -> bool:
    folded = (text or "").casefold()
    if not folded:
        return False
    if "организация совещаний" in folded:
        return True
    return "организац" in folded and "совещ" in folded


def _matches_person(text: str, fio: str) -> bool:
    if not fio:
        return True
    folded = (text or "").casefold()
    if not folded:
        return False
    for needle in person_needles(fio):
        if needle.casefold() in folded:
            return True
    return False


def _build_date_filter(date_from: date, date_to: date) -> str:
    parts = ["DeletionMark eq false"]
    parts.append(f"Date ge {_odata_datetime(date_from)}")
    parts.append(f"Date le {_odata_datetime(date_to, end_of_day=True)}")
    return " and ".join(parts)


def _matches_query(row: dict[str, Any], query: str, *, entity: str) -> bool:
    needle = (query or "").strip().casefold()
    if not needle:
        return True
    parts = [
        str(row.get("Number") or ""),
        _field_text(row, "ТемаСлужебнойЗаписки"),
        _field_text(row, "ТемаСовещания"),
        _field_text(row, "Содержание"),
        str(row.get("Комментарий") or ""),
        _field_text(row, "МенеджерКому"),
    ]
    if entity == INCOMING_ENTITY:
        parts.extend([_field_text(row, "Тема"), str(row.get("Содержание") or "")])
    return any(needle in part.casefold() for part in parts if part)


def _looks_like_document_number(value: str) -> bool:
    text = (value or "").strip()
    return bool(text) and text.replace("-", "").replace("_", "").isalnum() and any(ch.isdigit() for ch in text)


def invoke_meeting_service_notes(args: dict[str, Any]) -> dict[str, Any]:
    date_from, date_to = parse_note_period(args)
    addressee = str(args.get("fio") or "").strip() or default_addressee()
    limit = max(1, min(200, int(args.get("max_results") or args.get("limit") or 50)))
    odata_filter = _build_date_filter(date_from, date_to)

    try:
        raw = fetch_odata_list(
            entity=SERVICE_NOTE_ENTITY,
            odata_filter=odata_filter,
            top=min(limit * 5, 200),
        )
    except RuntimeError as exc:
        return {
            "notes": [],
            "count": 0,
            "source": "odata",
            "readonly": True,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "addressee": addressee,
            "theme": "организация совещаний",
            "entity": SERVICE_NOTE_ENTITY,
            "method": "odata_meeting_service_notes",
            "error": str(exc),
        }

    notes: list[dict[str, Any]] = []
    for row in odata_rows(raw):
        com32 = _row_to_com32(row)
        theme = str(com32.get("Theme") or "")
        if not _matches_meeting_theme(theme):
            continue
        if not _matches_person(str(com32.get("Addressee") or ""), addressee):
            continue
        item = note_from_com32_row(
            com32,
            document_name="ТД_СлужебнаяЗаписка",
            addressee=addressee,
        )
        item["ref"] = str(row.get("Ref_Key") or item.get("number") or "").strip()
        item["metadata_name"] = "ТД_СлужебнаяЗаписка"
        notes.append(item)
        if len(notes) >= limit:
            break

    return {
        "notes": notes,
        "count": len(notes),
        "source": "odata",
        "readonly": True,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "addressee": addressee,
        "theme": "организация совещаний",
        "document_type": "Служебная записка",
        "entity": SERVICE_NOTE_ENTITY,
        "filter": odata_filter,
        "method": "odata_meeting_service_notes",
    }


def invoke_search_documents(args: dict[str, Any]) -> dict[str, Any]:
    query = str(
        args.get("number") or args.get("query") or args.get("document_ref") or ""
    ).strip()
    limit = max(1, min(200, int(args.get("max_results") or args.get("limit") or 10)))
    document_type = str(
        args.get("document_type") or args.get("type") or args.get("section") or ""
    ).strip()

    if not query:
        return {
            "documents": [],
            "count": 0,
            "source": "odata",
            "method": "odata_search_documents",
            "note": "Укажите номер документа или текст для поиска",
        }

    exact_number = bool(str(args.get("number") or "").strip()) or _looks_like_document_number(query)
    entities = _entities_for_type(document_type)
    documents: list[dict[str, Any]] = []
    last_error = ""

    for entity, metadata_name, label in entities:
        try:
            if exact_number:
                raw = fetch_odata_list(entity=entity, number=query, top=limit)
            else:
                raw = fetch_odata_list(
                    entity=entity,
                    odata_filter="DeletionMark eq false",
                    top=min(limit * 8, 200),
                )
        except RuntimeError as exc:
            last_error = str(exc)
            continue

        for row in odata_rows(raw):
            if exact_number or _matches_query(row, query, entity=entity):
                if entity == SERVICE_NOTE_ENTITY:
                    doc = document_from_com32_row(
                        _row_to_com32(row),
                        document_name=metadata_name,
                        document_type=label,
                    )
                else:
                    doc = _incoming_document_row(row, metadata_name=metadata_name, label=label)
                doc["ref"] = str(row.get("Ref_Key") or doc.get("number") or "").strip()
                documents.append(doc)
            if len(documents) >= limit:
                break
        if documents:
            break

    result: dict[str, Any] = {
        "documents": documents[:limit],
        "count": min(len(documents), limit),
        "found": bool(documents),
        "query": query,
        "source": "odata",
        "method": "odata_search_documents",
    }
    if documents:
        result["document_type"] = documents[0].get("document_type") or ""
    if last_error and not documents:
        result["error"] = last_error
    return result


def invoke_get_document_card(args: dict[str, Any]) -> dict[str, Any]:
    ref_key = str(args.get("ref_key") or args.get("document_ref") or "").strip()
    number = str(args.get("number") or "").strip()
    query = str(args.get("query") or "").strip()
    metadata_name = str(args.get("metadata_name") or args.get("document_type") or "").strip()
    entity = _entity_from_metadata(metadata_name) or SERVICE_NOTE_ENTITY

    if ref_key and len(ref_key) >= 32:
        try:
            raw = fetch_odata_list(entity=entity, ref_key=ref_key, top=1)
            rows = odata_rows(raw)
            if rows:
                document = _document_from_odata_row(rows[0], entity=entity)
                return {
                    "document": document,
                    "source": "odata",
                    "method": "odata_get_document_card",
                }
        except RuntimeError:
            pass

    search_args = dict(args)
    if number:
        search_args["number"] = number
    elif query:
        search_args["query"] = query
    elif ref_key:
        search_args["query"] = ref_key
    else:
        raise ValueError("Для get_document_card нужен ref_key, number или query")

    found = invoke_search_documents({**search_args, "max_results": 1})
    documents = found.get("documents") if isinstance(found.get("documents"), list) else []
    document = documents[0] if documents else {}
    return {
        "document": document,
        "source": "odata",
        "method": "odata_get_document_card",
        **({"error": found.get("error")} if found.get("error") and not document else {}),
    }


def _entities_for_type(document_type: str) -> list[tuple[str, str, str]]:
    folded = (document_type or "").casefold()
    if "входящ" in folded or "корреспонд" in folded:
        return [(item[0], item[1], item[2]) for item in _SEARCH_ENTITIES if item[0] == INCOMING_ENTITY]
    if "служеб" in folded or "записк" in folded:
        return [(item[0], item[1], item[2]) for item in _SEARCH_ENTITIES if item[0] == SERVICE_NOTE_ENTITY]
    return list(_SEARCH_ENTITIES)


def _entity_from_metadata(metadata_name: str) -> str:
    folded = (metadata_name or "").casefold()
    if "входящ" in folded:
        return INCOMING_ENTITY
    if "служеб" in folded or "тд_служеб" in folded:
        return SERVICE_NOTE_ENTITY
    if metadata_name.startswith("Document_"):
        return metadata_name
    return ""


def _incoming_document_row(
    row: dict[str, Any],
    *,
    metadata_name: str,
    label: str,
) -> dict[str, Any]:
    theme = _field_text(row, "Тема") or _field_text(row, "Содержание")
    number = str(row.get("Number") or "").strip()
    return {
        "found": True,
        "document_type": label,
        "metadata_name": metadata_name,
        "kind": "document",
        "ref": str(row.get("Ref_Key") or number).strip(),
        "number": number,
        "date": str(row.get("Date") or "").strip(),
        "title": theme,
        "theme": theme,
        "fields": {key: row.get(key) for key in row if not str(key).endswith("@navigationLinkUrl")},
        "attachments": [],
    }


def _document_from_odata_row(row: dict[str, Any], *, entity: str) -> dict[str, Any]:
    if entity == SERVICE_NOTE_ENTITY:
        doc = document_from_com32_row(
            _row_to_com32(row),
            document_name="ТД_СлужебнаяЗаписка",
            document_type="Служебная записка",
        )
    else:
        doc = _incoming_document_row(
            row,
            metadata_name="ТД_ВходящаяКорреспонденция",
            label="Входящая корреспонденция",
        )
    doc["ref"] = str(row.get("Ref_Key") or doc.get("number") or "").strip()
    meeting = meeting_params_from_row(_row_to_com32(row)) if entity == SERVICE_NOTE_ENTITY else {}
    if meeting.get("topic"):
        doc["meeting_topic"] = meeting["topic"]
        doc["place"] = meeting.get("place") or ""
        doc["meeting"] = meeting
    doc["fields"] = {key: row.get(key) for key in row if not str(key).endswith("@navigationLinkUrl")}
    return doc
