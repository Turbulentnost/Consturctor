"""Регистрация приказов и распоряжений помощника руководителя.

План и факт — одно число: документы 1С за месяц, где ответственный
Акинина Татьяна Владимировна. Оценка 100%, потому что план совпадает с фактом.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

PERFORMER = "Акинина Татьяна Владимировна"
USER_KEY = "7a3fa603-0899-11f0-9637-6cb31113810e"
USER_ENTITY = "Catalog_Пользователи"
ORDER_ENTITY = "Document_ТД_Приказ"
DIRECTIVE_ENTITY = "Document_ТД_Распоряжение"
ENTITIES = (ORDER_ENTITY, DIRECTIVE_ENTITY)
USER_FIELD = "Ответственный_Key"
WEIGHT = 10
PAGE = 200

SOURCE = {
    "kind": "onec",
    "loader": "odata",
    "performer": PERFORMER,
    "user_key": USER_KEY,
    "entities": list(ENTITIES),
    "user_field": USER_FIELD,
}


def _as_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _bounds(ctx: Any, date_from: date | None, date_to: date | None) -> tuple[date | None, date | None]:
    start = date_from or getattr(ctx, "date_from", None)
    end = date_to or getattr(ctx, "date_to", None)
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()
    if start and end and end < start:
        start, end = end, start
    return start, end


def parse_day(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value if value.year > 1900 else None
    text = str(value).strip()
    if not text or text.startswith("0001-01-01"):
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return parsed if parsed.year > 1900 else None


def _odata_str(value: str) -> str:
    return value.replace("'", "''")


def _extra(ctx: Any) -> dict[str, Any]:
    extra = dict(SOURCE)
    more = ctx.extra_for() if hasattr(ctx, "extra_for") else {}
    if isinstance(more, dict):
        extra.update(more)
    return extra


def _kind(entity: str) -> str:
    return "directive" if "Распоряж" in entity else "order"


def _in_period(day: date | None, date_from: date | None, date_to: date | None) -> bool:
    if day is None:
        return False
    if date_from and day < date_from:
        return False
    if date_to and day > date_to:
        return False
    return True


def odata_filter(
    user_key: str,
    date_from: date | None,
    date_to: date | None,
    *,
    user_field: str = USER_FIELD,
) -> str:
    parts = ["DeletionMark eq false", f"{user_field} eq guid'{user_key}'"]
    if date_from:
        parts.append(f"Date ge datetime'{date_from.isoformat()}T00:00:00'")
    if date_to:
        parts.append(f"Date le datetime'{date_to.isoformat()}T23:59:59'")
    return " and ".join(parts)


def _load(ctx: Any, extra: dict[str, Any]) -> list[dict[str, Any]]:
    load = getattr(ctx, "load_for", None)
    if not callable(load):
        return []
    return _as_rows(load(extra))


def resolve_user_key(ctx: Any, extra: dict[str, Any]) -> str:
    performer = str(extra.get("performer") or PERFORMER).strip()
    fallback = str(extra.get("user_key") or USER_KEY).strip()
    if not performer:
        return fallback
    rows = _load(
        ctx,
        {
            "loader": "odata",
            "entity": USER_ENTITY,
            "filter": f"Description eq '{_odata_str(performer)}'",
            "top": 5,
        },
    )
    wanted = performer.casefold()
    for row in rows:
        key = str(row.get("Ref_Key") or "").strip()
        name = str(row.get("Description") or "").strip().casefold()
        if key and (not name or name == wanted):
            return key
    return fallback


def _page(ctx: Any, *, entity: str, filt: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = 0
    while skip <= PAGE * 10:
        batch = _load(
            ctx,
            {
                "loader": "odata",
                "entity": entity,
                "filter": filt,
                "top": PAGE,
                "skip": skip,
            },
        )
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        skip += PAGE
    return rows


def _subject(row: dict[str, Any]) -> str:
    text = str(row.get("Содержание") or row.get("Description") or row.get("subject") or "").strip()
    return text[:240]


def normalize_row(row: dict[str, Any], *, entity: str = "") -> dict[str, Any] | None:
    if row.get("DeletionMark") is True:
        return None
    kind = str(row.get("kind") or _kind(entity or str(row.get("entity") or "")))
    if kind not in {"order", "directive"}:
        return None
    day = parse_day(row.get("date") or row.get("Date"))
    number = str(row.get("number") or row.get("Number") or "").strip()
    ref = str(row.get("ref") or row.get("Ref_Key") or "").strip()
    if not number and not ref:
        return None
    posted = row.get("posted")
    if posted is None:
        posted = bool(row.get("Posted"))
    return {
        "kind": kind,
        "doc_kind": "Распоряжение" if kind == "directive" else "Приказ",
        "number": number,
        "date": day.isoformat() if day else "",
        "posted": bool(posted),
        "content": _subject(row),
    }


def load_orders_rows(
    ctx: Any,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]] | None:
    extra = _extra(ctx)
    user_key = resolve_user_key(ctx, extra)
    if not user_key:
        return None
    field = str(extra.get("user_field") or USER_FIELD).strip() or USER_FIELD
    entities = extra.get("entities") or list(ENTITIES)
    if isinstance(entities, str):
        entities = [entities]
    filt = odata_filter(user_key, date_from, date_to, user_field=field)
    rows: list[dict[str, Any]] = []
    for entity in entities:
        name = str(entity or "").strip()
        if not name or name == USER_ENTITY:
            continue
        for raw in _page(ctx, entity=name, filt=filt):
            item = normalize_row(raw, entity=name)
            if item is not None:
                rows.append(item)
    return rows


def score_orders_registration_kpi(
    rows: list[dict[str, Any]] | None,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for raw in _as_rows(rows):
        if raw.get("DeletionMark") is True:
            continue
        item = raw if "content" in raw and "doc_kind" in raw else normalize_row(raw)
        if item is None:
            continue
        if not _in_period(parse_day(item.get("date")), date_from, date_to):
            continue
        items.append(item)
    items.sort(key=lambda row: (row.get("date") or "", row.get("kind") or "", row.get("number") or ""))
    orders = sum(1 for row in items if row.get("kind") == "order")
    directives = sum(1 for row in items if row.get("kind") == "directive")
    count = len(items)
    return {
        "as_of": as_of.isoformat() if isinstance(as_of, date) else str(as_of or ""),
        "date_from": date_from.isoformat() if isinstance(date_from, date) else "",
        "date_to": date_to.isoformat() if isinstance(date_to, date) else "",
        "orders": orders,
        "directives": directives,
        "count": count,
        "plan": count,
        "fact": count,
        "fact_pct": 100.0,
        "score_pct": 100.0,
        "weight": WEIGHT,
        "contrib_pct": float(WEIGHT),
        "rows": items,
    }


def _empty(as_of: date, date_from: date | None, date_to: date | None) -> dict[str, Any]:
    return {
        "as_of": as_of.isoformat() if isinstance(as_of, date) else str(as_of or ""),
        "date_from": date_from.isoformat() if isinstance(date_from, date) else "",
        "date_to": date_to.isoformat() if isinstance(date_to, date) else "",
        "orders": None,
        "directives": None,
        "count": None,
        "plan": None,
        "fact": None,
        "fact_pct": None,
        "score_pct": None,
        "weight": WEIGHT,
        "contrib_pct": None,
        "rows": [],
    }


def compute_orders_registration_kpi(
    ctx: Any,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    start, end = _bounds(ctx, date_from, date_to)
    rows = load_orders_rows(ctx, date_from=start, date_to=end)
    if rows is None:
        return _empty(as_of, start, end)
    return score_orders_registration_kpi(rows, as_of=as_of, date_from=start, date_to=end)


def format_report(report: dict[str, Any]) -> str:
    if report.get("count") is None:
        return "Ответственного в 1С не нашли, приказы не посчитаны."
    lines = [f"{'вид':<14} {'дата':<12} {'номер':<16} содержание"]
    for row in report.get("rows") or []:
        kind = "распоряжение" if row.get("kind") == "directive" else "приказ"
        lines.append(
            f"{kind:<14} {str(row.get('date') or ''):<12} "
            f"{str(row.get('number') or ''):<16} {row.get('content') or ''}"
        )
    lines.append(
        f"Приказов {report.get('orders')}, распоряжений {report.get('directives')}, "
        f"всего {report.get('count')}. План = факт, {report.get('fact_pct')}%."
    )
    return "\n".join(lines)
