"""Local onec.meeting_protocols: OData filter on desktop, fetch via backend proxy.

The remote backend may not yet expose onec.meeting_protocols on /tools/invoke,
but onec.odata_get usually works. Filter rules mirror backend meeting_protocols.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

PROTOCOL_ENTITY = "Document_ТД_Протокол"

PROTOCOL_TABULAR_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Решения", "Document_ТД_Протокол_Решения"),
    ("ПовесткаСовещания", "Document_ТД_Протокол_ПовесткаСовещания"),
    ("ПланЗадачНаПериод", "Document_ТД_Протокол_ПланЗадачНаПериод"),
)

_KIND_ALIASES = {
    "rk": "rk",
    "ревизион": "rk",
    "ревизионная": "rk",
    "ревизионной": "rk",
    "рк": "rk",
    "sd": "sd",
    "совет": "sd",
    "сд": "sd",
    "board": "sd",
}

_NUMBER_PREFIXES: dict[str, tuple[str, ...]] = {
    "rk": ("РК",),
    "sd": ("ПСД", "СПГ", "СД"),
}

_REVIEW_STATUSES = frozenset({"Подготовлен"})


def _normalize_kind(raw: str) -> str:
    key = (raw or "").strip().casefold()
    kind = _KIND_ALIASES.get(key)
    if not kind:
        raise ValueError(
            "meeting_kind обязателен: rk (Ревизионная комиссия) или sd (Совет директоров)"
        )
    return kind


def _parse_iso_date(raw: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(text[:10])


def _period(args: dict[str, Any]) -> tuple[date | None, date | None]:
    single = _parse_iso_date(str(args.get("date") or ""))
    start = _parse_iso_date(str(args.get("date_from") or ""))
    end = _parse_iso_date(str(args.get("date_to") or ""))
    if single:
        return single, single
    if start or end:
        return start, end or start
    return None, None


def _odata_datetime(value: date, *, end_of_day: bool = False) -> str:
    if end_of_day:
        return f"datetime'{value.isoformat()}T23:59:59'"
    return f"datetime'{value.isoformat()}T00:00:00'"


def _escape_odata_string(value: str) -> str:
    return (value or "").replace("'", "''")


def _number_prefix_filter(kind: str) -> str:
    parts = [f"startswith(Number,'{prefix}')" for prefix in _NUMBER_PREFIXES[kind]]
    if len(parts) == 1:
        return parts[0]
    return "(" + " or ".join(parts) + ")"


def _arg_flag(value: Any, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "да", "истина"}:
        return True
    if text in {"0", "false", "no", "нет", "ложь", ""}:
        return False
    return default


def psd_mark_requested(args: dict[str, Any]) -> bool:
    for key in ("psd_mark", "psd_only", "only_psd"):
        if key in args and _arg_flag(args.get(key)) is True:
            return True
    return False


def _number_scope_filter(args: dict[str, Any], *, kind: str) -> str:
    if psd_mark_requested(args):
        return "startswith(Number,'ПСД')"
    return _number_prefix_filter(kind)


def protocol_navigation_path(ref_key: str, section: str) -> str:
    key = (ref_key or "").strip()
    if not key:
        raise ValueError("ref_key required")
    return f"{PROTOCOL_ENTITY}(guid'{key}')/{section.strip()}"


def build_protocol_filter(args: dict[str, Any], *, kind: str) -> str:
    filters: list[str] = ["DeletionMark eq false"]
    number = str(args.get("number") or args.get("Number") or "").strip()
    psd_only = psd_mark_requested(args)
    if number:
        filters.append(f"Number eq '{_escape_odata_string(number)}'")
    else:
        filters.append(_number_scope_filter(args, kind=kind))

    review_only = args.get("review_only")
    if review_only is None:
        review_only = not psd_only
    if _arg_flag(review_only, default=not psd_only):
        filters.append("(Posted eq false or Статус eq 'Подготовлен')")
    else:
        include_closed = args.get("include_closed")
        if include_closed is None:
            include_closed = psd_only
        if not _arg_flag(include_closed, default=False):
            filters.append("Статус ne 'Закрыт'")

    start, end = _period(args)
    if start:
        filters.append(f"Date ge {_odata_datetime(start)}")
    if end:
        filters.append(f"Date le {_odata_datetime(end, end_of_day=True)}")
    return " and ".join(filters)


_PAGE_SIZE = 100
_FULL_SERIES_CAP = 2000


def build_protocol_list_path(*, odata_filter: str, limit: int, skip: int = 0) -> str:
    filt = quote(odata_filter, safe="=,'")
    skip_q = f"&$skip={int(skip)}" if skip else ""
    return (
        f"{PROTOCOL_ENTITY}?$format=json&$top={limit}"
        f"{skip_q}&$filter={filt}&$orderby=Date%20desc&$expand=ТемаСовещания"
    )


def _relaxed_protocol_filters(args: dict[str, Any], *, kind: str) -> list[str]:
    strict = build_protocol_filter(args, kind=kind)
    parts: list[str] = ["DeletionMark eq false"]
    number = str(args.get("number") or args.get("Number") or "").strip()
    if number:
        parts.append(f"Number eq '{_escape_odata_string(number)}'")
    else:
        parts.append(_number_scope_filter(args, kind=kind))
    start, end = _period(args)
    if start:
        parts.append(f"Date ge {_odata_datetime(start)}")
    if end:
        parts.append(f"Date le {_odata_datetime(end, end_of_day=True)}")
    relaxed: list[str] = []
    for candidate in (" and ".join([*parts, "Posted eq false"]), " and ".join(parts)):
        if candidate != strict and candidate not in relaxed:
            relaxed.append(candidate)
    return relaxed


def _topic_from_row(row: dict[str, Any]) -> str:
    theme = row.get("ТемаСовещания")
    if isinstance(theme, dict):
        return str(theme.get("Description") or theme.get("Наименование") or "").strip()
    for key in ("ТемаСовещания", "ТемаСовещания_Name", "Description"):
        value = str(row.get(key) or "").strip()
        if value and not value.endswith("_Key"):
            return value
    return ""


def normalize_protocol_row(row: dict[str, Any], *, kind: str) -> dict[str, Any]:
    status = str(row.get("Статус") or "").strip()
    posted = bool(row.get("Posted"))
    needs_review = (not posted) or status in _REVIEW_STATUSES
    return {
        "ref_key": str(row.get("Ref_Key") or "").strip(),
        "number": str(row.get("Number") or "").strip(),
        "date": str(row.get("Date") or "").strip(),
        "posted": posted,
        "status": status,
        "needs_review": needs_review,
        "meeting_topic": _topic_from_row(row),
        "meeting_kind": kind,
        "meeting_kind_label": "Ревизионная комиссия" if kind == "rk" else "Совет директоров",
        "meeting_type": str(row.get("ВидСовещания") or "").strip(),
        "responsible_key": str(row.get("Ответственный_Key") or "").strip(),
        "department_key": str(row.get("Подразделение_Key") or "").strip(),
        "comment": str(row.get("Комментарий") or "").strip(),
    }


def _fetch_protocol_page(
    *,
    odata_filter: str,
    limit: int,
    skip: int = 0,
) -> dict[str, Any]:
    from app.tools.onec_odata_invoke import fetch_odata_list

    path = build_protocol_list_path(odata_filter=odata_filter, limit=limit, skip=skip)
    return fetch_odata_list(entity=PROTOCOL_ENTITY, path=path, top=limit)


def _page_protocol_rows(
    *,
    odata_filter: str,
    page_size: int,
    cap: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    rows: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    skip = 0
    while len(rows) < cap:
        take = min(page_size, cap - len(rows))
        raw = _fetch_protocol_page(odata_filter=odata_filter, limit=take, skip=skip)
        batch = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
        rows.extend(batch)
        if len(batch) < take:
            return rows, raw, False
        skip += len(batch)
    return rows, raw, True


def _fetch_protocol_rows(args: dict[str, Any], *, kind: str, limit: int) -> tuple[dict[str, Any], str, str]:
    odata_filter = build_protocol_filter(args, kind=kind)
    raw = _fetch_protocol_page(odata_filter=odata_filter, limit=limit)
    rows = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
    if rows:
        return raw, odata_filter, ""

    for fallback_filter in _relaxed_protocol_filters(args, kind=kind):
        try:
            raw = _fetch_protocol_page(odata_filter=fallback_filter, limit=limit)
        except RuntimeError:
            continue
        rows = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
        if rows:
            note = (
                "Строгий фильтр «на проверку» не дал строк — применён ослабленный фильтр. "
                f"Было: {odata_filter}. Стало: {fallback_filter}."
            )
            return {**raw, "filter_relaxed": True}, fallback_filter, note
    return raw, odata_filter, ""


def _attach_protocol_sections(protocol: dict[str, Any]) -> None:
    from app.tools.onec_odata_invoke import fetch_odata_list, odata_rows

    ref_key = str(protocol.get("ref_key") or "").strip()
    if not ref_key:
        return
    sections: dict[str, list[dict[str, Any]]] = {}
    for section_name, entity_name in PROTOCOL_TABULAR_SECTIONS:
        nav_path = f"{protocol_navigation_path(ref_key, section_name)}?$format=json&$top=50"
        try:
            raw = fetch_odata_list(entity=PROTOCOL_ENTITY, path=nav_path, top=50)
            rows = odata_rows(raw)
        except RuntimeError:
            continue
        if rows:
            sections[entity_name] = rows
    if sections:
        protocol["tabular_parts"] = sections
        protocol["sections_path_prefix"] = f"{PROTOCOL_ENTITY}(guid'{ref_key}')/"


def invoke_meeting_protocols(args: dict[str, Any]) -> dict[str, Any]:
    kind = _normalize_kind(str(args.get("meeting_kind") or args.get("kind") or ""))
    psd_only = psd_mark_requested(args)
    include_sections = bool(args.get("include_sections") or args.get("with_sections"))
    start, end = _period(args)
    review_only = args.get("review_only")
    if review_only is None:
        review_only = not psd_only
    truncated = False
    odata_filter = build_protocol_filter(args, kind=kind)

    try:
        if psd_only and not str(args.get("number") or args.get("Number") or "").strip():
            rows, raw, truncated = _page_protocol_rows(
                odata_filter=odata_filter,
                page_size=_PAGE_SIZE,
                cap=_FULL_SERIES_CAP,
            )
            filter_note = ""
            raw = {**raw, "value": rows}
        else:
            limit = max(1, min(100, int(args.get("max_results") or args.get("limit") or 30)))
            raw, odata_filter, filter_note = _fetch_protocol_rows(args, kind=kind, limit=limit)
            rows = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
            rows = rows[:limit]
    except RuntimeError as exc:
        return {
            "protocols": [],
            "count": 0,
            "source": "odata",
            "readonly": True,
            "meeting_kind": kind,
            "entity": PROTOCOL_ENTITY,
            "method": "odata_meeting_protocols",
            "filter": build_protocol_filter(args, kind=kind),
            "date_from": start.isoformat() if start else "",
            "date_to": end.isoformat() if end else "",
            "error": str(exc),
            "hint": (
                "Document_ТД_Протокол недоступен через OData или фильтр не поддерживается. "
                "Проверьте права учётки OData и meeting_kind (rk/sd)."
            ),
        }

    protocols = [normalize_protocol_row(row, kind=kind) for row in rows]
    if include_sections:
        for protocol in protocols:
            _attach_protocol_sections(protocol)

    result: dict[str, Any] = {
        "protocols": protocols,
        "count": len(protocols),
        "source": "odata",
        "readonly": True,
        "meeting_kind": kind,
        "meeting_kind_label": "Ревизионная комиссия" if kind == "rk" else "Совет директоров",
        "entity": PROTOCOL_ENTITY,
        "path": raw.get("path"),
        "filter": odata_filter,
        "review_only": bool(_arg_flag(review_only, default=False)),
        "psd_mark": psd_only,
        "truncated": truncated,
        "date_from": start.isoformat() if start else "",
        "date_to": end.isoformat() if end else "",
        "method": "odata_meeting_protocols",
        "summary": raw.get("summary") or f"найдено {len(protocols)} протоколов ({kind})",
        "tabular_hint": (
            "Для строк протокола читайте табличные части полным OData-путём "
            f"{PROTOCOL_ENTITY}(guid'<Ref_Key>')/<Раздел>, например …/Решения, …/ПовесткаСовещания."
        ),
    }
    if filter_note:
        result["filter_note"] = filter_note
    if raw.get("filter_relaxed"):
        result["filter_relaxed"] = True
    return result
