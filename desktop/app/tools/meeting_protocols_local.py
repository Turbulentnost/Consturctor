"""Local onec.meeting_protocols: OData filter on desktop, fetch via backend proxy.

The remote backend may not yet expose onec.meeting_protocols on /tools/invoke,
but onec.odata_get usually works. Filter rules mirror backend meeting_protocols.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any

PROTOCOL_ENTITY = "Document_ТД_Протокол"

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


def build_protocol_filter(args: dict[str, Any], *, kind: str) -> str:
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


def invoke_meeting_protocols(args: dict[str, Any]) -> dict[str, Any]:
    from app.tools import runtime_api

    kind = _normalize_kind(str(args.get("meeting_kind") or args.get("kind") or ""))
    limit = max(1, min(100, int(args.get("max_results") or args.get("limit") or 30)))
    odata_filter = build_protocol_filter(args, kind=kind)
    start, end = _period(args)
    review_only = args.get("review_only")
    if review_only is None:
        review_only = True

    try:
        data = runtime_api.request(
            "POST",
            "/api/v1/tools/onec.odata_get/invoke",
            json={
                "arguments": {
                    "entity": PROTOCOL_ENTITY,
                    "filter": odata_filter,
                    "top": limit,
                }
            },
            timeout=180.0,
        )
    except RuntimeError as exc:
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

    if isinstance(data, dict) and "result" in data:
        raw = data.get("result")
        if not isinstance(raw, dict):
            raw = {"value": raw}
    elif isinstance(data, dict):
        raw = data
    else:
        raw = {"value": data}

    rows = [row for row in (raw.get("value") or []) if isinstance(row, dict)]
    protocols = [normalize_protocol_row(row, kind=kind) for row in rows[:limit]]
    return {
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
    }
