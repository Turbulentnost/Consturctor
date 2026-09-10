"""OData search for Document_ТД_Протокол (list-form logic for RK / SD agents).

Mirrors Документ.ТД_Протокол.Форма.ФормаСписка selection rules discovered via live OData:
- RK (Ревизионная комиссия): Number starts with «РК» (e.g. РК__001_О_037)
- SD (Совет директоров по ГК): Number starts with «ПСД» (e.g. ПСД_001_О_225),
  also legacy «СПГ» and «СД»/«СДП»
- Exclude deletion mark
- «На проверку»: Posted=false or Статус=«Подготовлен» (draft before posting)
- OData: startswith(Number,...) works; contains() is not supported on this ERP
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

PROTOCOL_ENTITY = "Document_ТД_Протокол"

# OData navigation / tabular sections (full paths, not the document header only).
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
    # ПСД — текущий формат протоколов заседания СД ГК; СПГ/СД — старые серии.
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


def protocol_navigation_path(ref_key: str, section: str) -> str:
    """Full OData path to a protocol tabular section, e.g. …/Решения."""
    key = (ref_key or "").strip()
    if not key:
        raise ValueError("ref_key required")
    return f"{PROTOCOL_ENTITY}(guid'{key}')/{section.strip()}"


def build_protocol_filter(args: dict[str, Any], *, kind: str) -> str:
    """Build OData $filter for Document_ТД_Протокол list selection."""
    filters: list[str] = ["DeletionMark eq false"]
    number = str(args.get("number") or args.get("Number") or "").strip()
    if number:
        filters.append(f"Number eq '{_escape_odata_string(number)}'")
    else:
        filters.append(_number_prefix_filter(kind))

    review_only = args.get("review_only")
    if review_only is None:
        review_only = True
    if review_only:
        filters.append("(Posted eq false or Статус eq 'Подготовлен')")
    else:
        include_closed = bool(args.get("include_closed"))
        if not include_closed:
            filters.append("Статус ne 'Закрыт'")

    start, end = _period(args)
    if start:
        filters.append(f"Date ge {_odata_datetime(start)}")
    if end:
        filters.append(f"Date le {_odata_datetime(end, end_of_day=True)}")
    return " and ".join(filters)


def build_protocol_list_path(*, odata_filter: str, limit: int) -> str:
    """OData list path for Document_ТД_Протокол with topic expand."""
    filt = quote(odata_filter, safe="=,'")
    return (
        f"{PROTOCOL_ENTITY}?$format=json&$top={limit}"
        f"&$filter={filt}&$orderby=Date%20desc&$expand=ТемаСовещания"
    )


def _relaxed_protocol_filters(args: dict[str, Any], *, kind: str) -> list[str]:
    """Fallback filters when strict review filter returns zero rows."""
    strict = build_protocol_filter(args, kind=kind)
    parts: list[str] = ["DeletionMark eq false"]
    number = str(args.get("number") or args.get("Number") or "").strip()
    if number:
        parts.append(f"Number eq '{_escape_odata_string(number)}'")
    else:
        parts.append(_number_prefix_filter(kind))
    start, end = _period(args)
    if start:
        parts.append(f"Date ge {_odata_datetime(start)}")
    if end:
        parts.append(f"Date le {_odata_datetime(end, end_of_day=True)}")
    posted_only = " and ".join([*parts, "Posted eq false"])
    open_only = " and ".join(parts)
    relaxed: list[str] = []
    for candidate in (posted_only, open_only):
        if candidate != strict and candidate not in relaxed:
            relaxed.append(candidate)
    return relaxed


def _fetch_protocol_rows(
    args: dict[str, Any],
    *,
    kind: str,
    limit: int,
) -> tuple[dict[str, Any], str, str]:
    from app.services.onec_tools import OnecToolError, _fetch_odata_list

    odata_filter = build_protocol_filter(args, kind=kind)
    path = build_protocol_list_path(odata_filter=odata_filter, limit=limit)
    fetch_args: dict[str, Any] = {
        "entity": PROTOCOL_ENTITY,
        "path": path,
        "top": limit,
    }
    raw = _fetch_odata_list(fetch_args)
    rows = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
    used_filter = odata_filter
    if rows:
        return raw, used_filter, used_filter

    for fallback_filter in _relaxed_protocol_filters(args, kind=kind):
        fallback_path = build_protocol_list_path(odata_filter=fallback_filter, limit=limit)
        try:
            raw = _fetch_odata_list(
                {
                    "entity": PROTOCOL_ENTITY,
                    "path": fallback_path,
                    "top": limit,
                }
            )
        except OnecToolError:
            continue
        rows = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
        if rows:
            note = (
                "Строгий фильтр «на проверку» не дал строк — применён ослабленный фильтр. "
                f"Было: {odata_filter}. Стало: {fallback_filter}."
            )
            raw = {**raw, "filter_note": note, "filter_relaxed": True}
            return raw, fallback_filter, note
    return raw, used_filter, ""


def _attach_protocol_sections(
    protocol: dict[str, Any],
    *,
    fetch: Any,
) -> None:
    ref_key = str(protocol.get("ref_key") or "").strip()
    if not ref_key:
        return
    sections: dict[str, list[dict[str, Any]]] = {}
    for section_name, entity_name in PROTOCOL_TABULAR_SECTIONS:
        nav_path = f"{protocol_navigation_path(ref_key, section_name)}?$format=json&$top=50"
        try:
            raw = fetch({"path": nav_path, "entity": PROTOCOL_ENTITY})
        except Exception:  # noqa: BLE001
            continue
        payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        rows = payload.get("value") if isinstance(payload, dict) else None
        if isinstance(rows, list) and rows:
            sections[entity_name] = [row for row in rows if isinstance(row, dict)]
    if sections:
        protocol["tabular_parts"] = sections
        protocol["sections_path_prefix"] = f"{PROTOCOL_ENTITY}(guid'{ref_key}')/"


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


def list_meeting_protocols(
    args: dict[str, Any],
    *,
    access: Any | None = None,
) -> dict[str, Any]:
    from app.services.onec_access import OnecAccessDenied, filter_odata_result
    from app.services.onec_tools import OnecToolError, _fetch_odata_list

    kind = _normalize_kind(str(args.get("meeting_kind") or args.get("kind") or ""))
    limit = max(1, min(100, int(args.get("max_results") or args.get("limit") or 30)))
    include_sections = bool(args.get("include_sections") or args.get("with_sections"))
    odata_filter = build_protocol_filter(args, kind=kind)
    try:
        raw, odata_filter, filter_note = _fetch_protocol_rows(args, kind=kind, limit=limit)
    except OnecToolError as exc:
        start, end = _period(args)
        return {
            "protocols": [],
            "count": 0,
            "source": "odata",
            "readonly": True,
            "meeting_kind": kind,
            "entity": PROTOCOL_ENTITY,
            "method": "odata_meeting_protocols",
            "filter": odata_filter,
            "date_from": start.isoformat() if start else "",
            "date_to": end.isoformat() if end else "",
            "error": str(exc),
            "hint": (
                "Document_ТД_Протокол недоступен через OData или фильтр не поддерживается. "
                "Проверьте права учётки OData и meeting_kind (rk/sd)."
            ),
        }

    rows = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
    if access is not None:
        try:
            rows = filter_odata_result({"value": rows}, access, PROTOCOL_ENTITY).get("value") or []
        except OnecAccessDenied as exc:
            raise OnecToolError(str(exc)) from exc
    protocols = [normalize_protocol_row(row, kind=kind) for row in rows[:limit]]
    if include_sections:
        from app.services.onec_tools import _odata_get

        for protocol in protocols:
            _attach_protocol_sections(protocol, fetch=_odata_get)
    start, end = _period(args)
    review_only = args.get("review_only")
    if review_only is None:
        review_only = True
    result = {
        "protocols": protocols,
        "count": len(protocols),
        "source": "odata",
        "readonly": True,
        "meeting_kind": kind,
        "meeting_kind_label": "Ревизионная комиссия" if kind == "rk" else "Совет директоров",
        "entity": PROTOCOL_ENTITY,
        "path": raw.get("path"),
        "filter": odata_filter,
        "review_only": bool(review_only),
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


def stub_meeting_protocols(args: dict[str, Any]) -> dict[str, Any]:
    try:
        kind = _normalize_kind(str(args.get("meeting_kind") or args.get("kind") or "rk"))
    except ValueError:
        kind = "rk"
    start, end = _period(args)
    return {
        "protocols": [],
        "count": 0,
        "source": "stub",
        "readonly": True,
        "meeting_kind": kind,
        "entity": PROTOCOL_ENTITY,
        "date_from": start.isoformat() if start else "",
        "date_to": end.isoformat() if end else "",
        "note": "OData 1С не настроена — протоколы Document_ТД_Протокол не прочитаны.",
    }
