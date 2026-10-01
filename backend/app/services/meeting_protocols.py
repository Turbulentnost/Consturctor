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

import re
from datetime import date, timedelta
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
    # Calendar / manual form: every Document_ТД_Протокол in the period, no number prefix.
    "any": "any",
    "all": "any",
    "все": "any",
    "календарь": "any",
    "calendar": "any",
}

_NUMBER_PREFIXES: dict[str, tuple[str, ...]] = {
    "rk": ("РК",),
    # ПСД — текущий формат протоколов заседания СД ГК; СПГ/СД — старые серии.
    "sd": ("ПСД", "СПГ", "СД"),
}

_REVIEW_STATUSES = frozenset({"Подготовлен"})

# ПСД/СПГ/СД numbers also cover planning meetings and ДПИ; the board is told apart by its theme.
SD_BOARD_TOPIC = "Совет директоров по ГК"
_PAIR_LOOKBACK_DAYS = 370
_PAIR_LOOKAHEAD_DAYS = 60


def _normalize_kind(raw: str) -> str:
    key = (raw or "").strip().casefold()
    kind = _KIND_ALIASES.get(key)
    if not kind:
        raise ValueError(
            "meeting_kind: rk (Ревизионная комиссия), sd (Совет директоров) или any (все протоколы за период)"
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


def _topic_filter(args: dict[str, Any]) -> str:
    topic = str(args.get("topic") or "").strip()
    if not topic:
        return ""
    return f"ТемаСовещания/Description eq '{_escape_odata_string(topic)}'"


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
    psd_only = psd_mark_requested(args)
    if number:
        filters.append(f"Number eq '{_escape_odata_string(number)}'")
    elif psd_only or kind in _NUMBER_PREFIXES:
        filters.append(_number_scope_filter(args, kind=kind))
    if topic := _topic_filter(args):
        filters.append(topic)

    review_only = args.get("review_only")
    if review_only is None:
        review_only = (not psd_only) and kind != "any"
    if _arg_flag(review_only, default=(not psd_only) and kind != "any"):
        filters.append("(Posted eq false or Статус eq 'Подготовлен')")
    else:
        include_closed = args.get("include_closed")
        if include_closed is None:
            include_closed = psd_only or kind == "any"
        if not _arg_flag(include_closed, default=False):
            filters.append("Статус ne 'Закрыт'")

    start, end = _period(args)
    if start:
        filters.append(f"Date ge {_odata_datetime(start)}")
    if end:
        filters.append(f"Date le {_odata_datetime(end, end_of_day=True)}")
    return " and ".join(filters)


# Without $select 1C returns every tabular part (with Файл_Base64Data): a month of protocols
# exceeds the 60 s OData timeout. Nested person keys stay for the confidentiality filter.
_PROTOCOL_LIST_SELECT = ",".join(
    (
        "Ref_Key",
        "Number",
        "Date",
        "Posted",
        "DeletionMark",
        "Статус",
        "ДатаСоздания",
        "ДатаСледующегоСовещания",
        "ВидСовещания",
        "ВремяНачалаСовещания",
        "ВремяОкончанияСовещания",
        "КраткийСоставДокумента",
        "Комментарий",
        "Ответственный_Key",
        "Руководитель_Key",
        "Подготовил_Key",
        "Подразделение_Key",
        "ТемаСовещания/Description",
        "ПрисутствующиеНаСовещании/Участник_Key",
        "ПовесткаСовещания/Ответственный_Key",
        "ПеременныеЗадачиПротокола/Ответственный_Key",
        "ПеременныеЗадачиПротокола/Автор_Key",
        "ПостоянныеЗадачиПротокола/Автор_Key",
    )
)


def build_protocol_list_path(*, odata_filter: str, limit: int) -> str:
    """OData list path for Document_ТД_Протокол with topic expand."""
    filt = quote(odata_filter, safe="=,'/")
    return (
        f"{PROTOCOL_ENTITY}?$format=json&$top={limit}"
        f"&$filter={filt}&$orderby=Date%20desc&$expand=ТемаСовещания"
        f"&$select={_PROTOCOL_LIST_SELECT}"
    )


def _relaxed_protocol_filters(args: dict[str, Any], *, kind: str) -> list[str]:
    """Fallback filters when strict review filter returns zero rows."""
    strict = build_protocol_filter(args, kind=kind)
    parts: list[str] = ["DeletionMark eq false"]
    number = str(args.get("number") or args.get("Number") or "").strip()
    if number:
        parts.append(f"Number eq '{_escape_odata_string(number)}'")
    elif psd_mark_requested(args) or kind in _NUMBER_PREFIXES:
        parts.append(_number_scope_filter(args, kind=kind))
    if topic := _topic_filter(args):
        parts.append(topic)
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


def _kind_label(kind: str) -> str:
    if kind == "rk":
        return "Ревизионная комиссия"
    if kind == "sd":
        return "Совет директоров"
    return "Все протоколы"


def _clock(value: Any) -> str:
    text = str(value or "").strip()
    if "T" in text:
        text = text.split("T", 1)[1]
    return text[:5] if len(text) >= 5 and text[2:3] == ":" else ""


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
        "created_at": str(row.get("ДатаСоздания") or row.get("created_at") or "").strip(),
        "next_meeting": str(row.get("ДатаСледующегоСовещания") or row.get("next_meeting") or "").strip(),
        "posted": posted,
        "status": status,
        "needs_review": needs_review,
        "meeting_topic": _topic_from_row(row),
        "meeting_kind": kind,
        "meeting_kind_label": _kind_label(kind),
        "meeting_type": str(row.get("ВидСовещания") or "").strip(),
        "time_start": _clock(row.get("ВремяНачалаСовещания")),
        "time_end": _clock(row.get("ВремяОкончанияСовещания")),
        "brief": str(row.get("КраткийСоставДокумента") or "").strip(),
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

    ref_key = str(args.get("ref_key") or args.get("Ref_Key") or "").strip()
    if ref_key:
        return _read_protocol_card(ref_key)
    if _arg_flag(args.get("pair"), default=False):
        return board_protocol_pair(args, access=access)

    kind = _normalize_kind(str(args.get("meeting_kind") or args.get("kind") or ""))
    start, end = _period(args)
    number = str(args.get("number") or args.get("Number") or "").strip()
    if kind == "any" and not number and not start and not end:
        return {
            "protocols": [],
            "count": 0,
            "source": "odata",
            "readonly": True,
            "meeting_kind": kind,
            "entity": PROTOCOL_ENTITY,
            "method": "odata_meeting_protocols",
            "error": "Для meeting_kind=any укажите date или date_from/date_to",
        }
    cap = 200 if kind == "any" else 100
    limit = max(1, min(cap, int(args.get("max_results") or args.get("limit") or (80 if kind == "any" else 30))))
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
        review_only = (not psd_mark_requested(args)) and kind != "any"
    result = {
        "protocols": protocols,
        "count": len(protocols),
        "source": "odata",
        "readonly": True,
        "meeting_kind": kind,
        "meeting_kind_label": _kind_label(kind),
        "entity": PROTOCOL_ENTITY,
        "path": raw.get("path"),
        "filter": odata_filter,
        "review_only": bool(review_only),
        "psd_mark": psd_mark_requested(args),
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


def _read_protocol_card(ref_key: str) -> dict[str, Any]:
    """One protocol as an editable form (names instead of GUIDs). Read-only."""
    from app.services.meeting_protocol_write import ProtocolWriteError, read_protocol_form
    from app.services.onec_tools import OnecToolError

    try:
        protocol = read_protocol_form(ref_key)
    except ProtocolWriteError as exc:
        raise OnecToolError(str(exc)) from exc
    return {
        "protocol": protocol,
        "protocols": [protocol],
        "count": 1,
        "source": "odata",
        "readonly": True,
        "entity": PROTOCOL_ENTITY,
        "method": "odata_meeting_protocol_card",
        "summary": f"протокол {protocol.get('number') or ref_key}: {protocol.get('status') or '—'}",
    }


def _pick_pair(
    protocols: list[dict[str, Any]],
    *,
    anchor: date,
    explicit_day: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Current = meeting on the given day (or the newest draft); previous = the one before it."""
    ordered = sorted(protocols, key=lambda item: item.get("date") or "", reverse=True)
    day = anchor.isoformat()
    if explicit_day:
        on_day = [item for item in ordered if (item.get("date") or "")[:10] == day]
        on_day.sort(key=lambda item: not item.get("needs_review"))
        current = on_day[0] if on_day else None
    else:
        current = next((item for item in ordered if item.get("needs_review")), None)
    border = (current.get("date") or "")[:10] if current else (anchor + timedelta(days=1)).isoformat()
    previous = next(
        (
            item
            for item in ordered
            if item is not current and (item.get("date") or "")[:10] < border
        ),
        None,
    )
    return current, previous


def check_protocol_tasks(
    form: dict[str, Any],
    *,
    posted: bool,
    today: date,
) -> dict[str, Any]:
    """Completeness of «Поставленные задачи»: executor, due date, sent to 1C, file, overdue."""
    tasks = [task for task in form.get("tasks") or [] if isinstance(task, dict)]
    checked: list[dict[str, Any]] = []
    for task in tasks:
        findings: list[str] = []
        if not str(task.get("executor") or "").strip():
            findings.append("не указан исполнитель")
        due = str(task.get("due") or "").strip()
        if not due:
            findings.append("не указан срок")
        if posted and not task.get("sent") and not task.get("process_started"):
            findings.append("не отправлена исполнителю в 1С")
        if not task.get("has_file"):
            findings.append("нет вложенного файла")
        if posted and due and due < today.isoformat() and not str(task.get("note") or "").strip():
            findings.append(f"срок {due} прошёл, нет отметки об исполнении")
        checked.append(
            {
                "item": task.get("item") or "",
                "text": task.get("text") or "",
                "executor": task.get("executor") or "",
                "due": due,
                "note": task.get("note") or "",
                "sent": bool(task.get("sent") or task.get("process_started")),
                "has_file": bool(task.get("has_file")),
                "complete": not findings,
                "findings": findings,
            }
        )
    decisions = check_protocol_decisions(form, posted=posted, today=today)
    agenda = check_protocol_agenda(form)
    gaps: list[str] = []
    if not checked and not decisions:
        gaps.append("в протоколе нет ни поручений («Решения»), ни «Поставленных задач»")
    incomplete = [task for task in checked if not task["complete"]]
    open_decisions = [item for item in decisions if not item["complete"]]
    open_agenda = [item for item in agenda if not item["complete"]]
    return {
        "tasks": checked,
        "tasks_total": len(checked),
        "tasks_incomplete": len(incomplete),
        "decisions": decisions,
        "decisions_total": len(decisions),
        "decisions_incomplete": len(open_decisions),
        "agenda": agenda,
        "agenda_incomplete": len(open_agenda),
        "complete": bool(checked or decisions) and not (incomplete or open_decisions or open_agenda),
        "gaps": gaps,
    }


def check_protocol_decisions(
    form: dict[str, Any],
    *,
    posted: bool,
    today: date,
) -> list[dict[str, Any]]:
    """Each board assignment («Решения»): artifact, result, due date, cancel.

    «Решения» have no executor in 1С, so «Отправлено» is not a finding: the board sends them
    by posting the protocol.
    """
    _ = posted
    checked: list[dict[str, Any]] = []
    for item in form.get("decisions") or []:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        due = str(item.get("due") or item.get("due_in_text") or "").strip()
        done = bool(str(item.get("done_date") or "").strip() or str(item.get("result") or "").strip())
        findings: list[str] = []
        if item.get("canceled"):
            status = "отменено"
        else:
            if not item.get("has_artifact"):
                findings.append("нет артефакта (отметка «Наличие артефакта» не стоит)")
            if not done:
                findings.append("нет результата и даты исполнения")
            if not due:
                findings.append("не указан срок")
            elif due < today.isoformat() and not done:
                findings.append(f"срок {due} прошёл, поручение не исполнено")
            status = "исполнено" if done and item.get("has_artifact") else "не исполнено"
        checked.append(
            {
                "item": item.get("item") or "",
                "text": item.get("text") or "",
                "since": item.get("since") or "",
                "due": due,
                "due_source": "1С" if item.get("due") else ("текст поручения" if due else ""),
                "result": item.get("result") or "",
                "done_date": item.get("done_date") or "",
                "has_artifact": bool(item.get("has_artifact")),
                "sent": bool(item.get("sent")),
                "canceled": bool(item.get("canceled")),
                "cancel_reason": item.get("cancel_reason") or "",
                "status": status,
                "complete": not findings,
                "findings": findings,
            }
        )
    return checked


def check_protocol_agenda(form: dict[str, Any]) -> list[dict[str, Any]]:
    """Each agenda question: a responsible speaker and an attached material."""
    checked: list[dict[str, Any]] = []
    for item in form.get("agenda") or []:
        if not isinstance(item, dict) or not str(item.get("question") or "").strip():
            continue
        findings: list[str] = []
        if not str(item.get("responsible") or "").strip():
            findings.append("не указан ответственный")
        if not item.get("has_file"):
            findings.append("нет приложенного материала")
        checked.append(
            {
                "item": item.get("item") or "",
                "question": item.get("question") or "",
                "responsible": item.get("responsible") or "",
                "has_file": bool(item.get("has_file")),
                "complete": not findings,
                "findings": findings,
            }
        )
    return checked


PROTOCOL_FILES_ENTITY = "Catalog_ТД_ПротоколПрисоединенныеФайлы"

# Name fragments of attached files per package item of п. 6.4 ПЛ-34-242.
PACKAGE_FILE_HINTS: dict[str, tuple[str, ...]] = {
    "резюме": ("резюме", "summary"),
    "опу": ("опу", "бдр", "прибыл", "убыт", "план-факт", "план факт", "планфакт"),
    "ддс": ("ддс", "бддс", "денежн"),
    "инвестиц": ("инвест", "capex"),
    "продаж": ("продаж", "выручк", "коммерч"),
    "дз": ("дз", "дебитор"),
    "производств": ("производ",),
    "ниокр": ("ниокр", "нир", "окр"),
    "риск": ("риск",),
    "персонал": ("персонал", "кадр", "штат", "фот"),
    "поручен": ("поручен",),
    "решения класса а": ("класс а", "класса а"),
    "приложение а": ("приложение а", "прил а", "прил. а", "план-факт", "план факт", "планфакт"),
    "приложение б": ("приложение б", "прил б", "прил. б", "бдр"),
}

# Rows of the п. 6.4 table in the order of ПЛ-34-242.
PACKAGE_LABELS: dict[str, str] = {
    "резюме": "Краткое резюме (1 стр.)",
    "опу": "Финансы план/факт: ОПУ",
    "ддс": "Финансы: ДДС",
    "инвестиц": "Капитал и инвестиции",
    "продаж": "Продажи и клиенты",
    "дз": "Дебиторская задолженность",
    "производств": "Производство и качество",
    "ниокр": "Проекты / НИОКР",
    "риск": "Риски и комплаенс",
    "персонал": "Персонал и преемственность",
    "поручен": "Статус исполнения решений / поручений ПСД",
    "решения класса а": "Решения на согласование (класс А)",
    "приложение а": "Приложение А. План-факт БДР",
    "приложение б": "Приложение Б. БДР",
}

# Agenda questions point to the speaker of a package item when no file names one.
_AGENDA_HINTS: dict[str, tuple[str, ...]] = {
    "опу": ("управленческ", "отчетност", "отчётност"),
    "продаж": ("коммерческ", "продаж"),
    "персонал": ("заработн", "персонал", "кадр"),
    "поручен": ("поручени", "решени"),
}


def protocol_attached_files(ref_key: str) -> list[dict[str, Any]]:
    """Files attached to the protocol card (Catalog_ТД_ПротоколПрисоединенныеФайлы), in upload order."""
    from app.services.onec_tools import _fetch_odata_list

    result = _fetch_odata_list(
        {
            "entity": PROTOCOL_FILES_ENTITY,
            "filter": f"ВладелецФайла_Key eq guid'{ref_key}' and DeletionMark eq false",
            "top": 200,
        }
    )
    files = []
    for row in result.get("value") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Description") or "").strip()
        extension = str(row.get("Расширение") or "").strip()
        files.append(
            {
                "file_id": str(row.get("Ref_Key") or ""),
                "name": f"{name}.{extension}" if name and extension else name or extension,
                "created": str(row.get("ДатаСоздания") or "")[:16].replace("T", " "),
                "uploaded_by": str(row.get("Изменил_Name") or row.get("Изменил") or "").strip(),
            }
        )
    files.sort(key=lambda item: item["created"])
    return files


def package_table(
    sides: list[tuple[dict[str, Any] | None, str]],
    agenda: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One row per п. 6.4 item: responsible person and its documents in upload order."""
    files = [
        {
            "name": str(item.get("name") or ""),
            "created": str(item.get("created") or ""),
            "uploaded_by": str(item.get("uploaded_by") or ""),
            "protocol": str(side.get("number") or ""),
        }
        for side, _label in sides
        if side
        for item in side.get("files") or []
    ]
    files.sort(key=lambda item: item["created"])

    def matches(item: dict[str, Any], hints: tuple[str, ...]) -> bool:
        return any(_name_has_hint(item["name"], hint) for hint in hints)

    def described(item: dict[str, Any]) -> str:
        return f"{item['name']} ({item['created']}, {item['uploaded_by'] or 'автор не указан'}, {item['protocol']})"

    rows: list[dict[str, Any]] = []
    for index, (key, label) in enumerate(PACKAGE_LABELS.items(), start=1):
        docs = [item for item in files if matches(item, PACKAGE_FILE_HINTS.get(key, ()))]
        people = list(dict.fromkeys(item["uploaded_by"] for item in docs if item["uploaded_by"]))
        source = "загрузил файлы в 1С" if people else ""
        if not people:
            speakers = [
                str(question.get("responsible") or "").strip()
                for question in agenda
                if any(hint in str(question.get("question") or "").casefold() for hint in _AGENDA_HINTS.get(key, ()))
            ]
            people = list(dict.fromkeys(name for name in speakers if name))
            source = "ответственный по вопросу повестки" if people else ""
        rows.append(
            {
                "n": index,
                "item": label,
                "responsible": ", ".join(people),
                "responsible_source": source,
                "documents": [described(item) for item in docs],
                "status": "есть" if docs else "нет",
            }
        )
    unread = [item for item in files if not any(matches(item, hints) for hints in PACKAGE_FILE_HINTS.values())]
    if unread:
        rows.append(
            {
                "n": len(rows) + 1,
                "item": "Не определено по имени — прочитать и отнести к пункту",
                "responsible": ", ".join(dict.fromkeys(item["uploaded_by"] for item in unread if item["uploaded_by"])),
                "responsible_source": "загрузил файлы в 1С",
                "documents": [described(item) for item in unread],
                "status": "прочитать",
            }
        )
    return rows


def _name_has_hint(name: str, hint: str) -> bool:
    text = re.sub(r"[_]+", " ", name.casefold())
    if len(hint) <= 3:
        return any(word == hint or word.startswith(hint + " ") for word in re.findall(r"[a-zа-яё0-9]+", text))
    return hint in text


def package_by_files(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Match protocol files to package items by name; unnamed scans must be read to be classified."""
    items: dict[str, list[str]] = {}
    matched: set[str] = set()
    for item, hints in PACKAGE_FILE_HINTS.items():
        names = [f["name"] for f in files if any(_name_has_hint(f["name"], hint) for hint in hints)]
        items[item] = names
        matched.update(names)
    unrecognized = [f for f in files if f["name"] not in matched]
    return {
        "items": [{"item": item, "files": names, "found": bool(names)} for item, names in items.items()],
        "unrecognized": unrecognized,
    }


PACKAGE_TABLE_TITLE = "Пакет п. 6.4"


def package_table_markdown(rows: list[dict[str, Any]]) -> str:
    """The п. 6.4 table as markdown — the agent pastes it as is into the summary and WORK_RESULT."""

    def cell(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).replace("|", "/").strip()

    lines = [
        f"### {PACKAGE_TABLE_TITLE}",
        "",
        "| № | Пункт пакета | Ответственное лицо | Документы (по порядку) | Статус |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        documents = "; ".join(cell(doc) for doc in row.get("documents") or []) or "—"
        responsible = cell(row.get("responsible")) or "не назначен"
        if row.get("responsible_source") == "ответственный по вопросу повестки":
            responsible += " (по вопросу повестки)"
        lines.append(f"| {row.get('n')} | {cell(row.get('item'))} | {responsible} | {documents} | {cell(row.get('status'))} |")
    return "\n".join(lines)


def _pair_side(
    protocol: dict[str, Any] | None,
    *,
    today: date,
    gaps: list[str],
    label: str,
) -> dict[str, Any] | None:
    from app.services.meeting_protocol_write import (
        ProtocolWriteError,
        read_protocol_card,
        read_protocol_form,
    )

    if protocol is None:
        return None
    ref_key = str(protocol.get("ref_key") or "")
    try:
        card = read_protocol_card(ref_key)
        form = read_protocol_form(ref_key, card=card)["form"]
    except ProtocolWriteError as exc:
        gaps.append(f"{label} протокол {protocol.get('number')}: не прочитан ({exc})")
        return {**protocol, "error": str(exc)}
    check = check_protocol_tasks(form, posted=bool(protocol.get("posted")), today=today)
    gaps.extend(f"{label} протокол {protocol.get('number')}: {gap}" for gap in check["gaps"])
    try:
        files = protocol_attached_files(ref_key)
    except Exception as exc:  # noqa: BLE001 — a failed file list must not hide the protocol check
        files = []
        gaps.append(f"{label} протокол {protocol.get('number')}: файлы не прочитаны ({str(exc)[:200]})")
    return {
        **protocol,
        "next_meeting": form.get("next_meeting_date") or protocol.get("next_meeting") or "",
        "participants": form.get("participants") or [],
        "agenda": form.get("agenda") or [],
        "decisions": form.get("decisions") or [],
        "responsible": form.get("responsible") or "",
        "check": check,
        "files": files,
        "package": package_by_files(files),
    }


def _mark_not_carried(current: dict[str, Any] | None, previous: dict[str, Any] | None) -> None:
    if not current or not previous or "check" not in current or "check" not in previous:
        return
    carried = {
        str(task.get("text") or "").strip().casefold() for task in current["check"]["tasks"]
    }
    number = current.get("number") or ""
    for task in previous["check"]["tasks"]:
        if str(task.get("text") or "").strip().casefold() in carried or str(task.get("note") or "").strip():
            continue
        task["findings"].append(f"не перенесена в протокол {number} на контроль")
        task["complete"] = False
    carried_decisions = {_decision_key(item.get("text")) for item in current["check"].get("decisions") or []}
    for item in previous["check"].get("decisions") or []:
        if item["canceled"] or item["status"] == "исполнено":
            continue
        if _decision_key(item.get("text")) in carried_decisions:
            item["carried"] = True
            continue
        item["carried"] = False
        item["findings"].append(f"не исполнено и не перенесено в протокол {number}")
        item["complete"] = False
    check = previous["check"]
    check["tasks_incomplete"] = sum(1 for task in check["tasks"] if not task["complete"])
    check["decisions_incomplete"] = sum(1 for item in check.get("decisions") or [] if not item["complete"])
    check["complete"] = bool(check["tasks"] or check.get("decisions")) and not (
        check["tasks_incomplete"] or check["decisions_incomplete"] or check.get("agenda_incomplete")
    )


def _decision_key(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def board_protocol_pair(args: dict[str, Any], *, access: Any | None = None) -> dict[str, Any]:
    """Current and previous board protocols with a completeness check of their tasks."""
    topic = str(args.get("topic") or SD_BOARD_TOPIC).strip()
    explicit = _parse_iso_date(str(args.get("date") or ""))
    anchor = explicit or date.today()
    listed = list_meeting_protocols(
        {
            "meeting_kind": str(args.get("meeting_kind") or "sd"),
            "topic": topic,
            "date_from": (anchor - timedelta(days=_PAIR_LOOKBACK_DAYS)).isoformat(),
            "date_to": (anchor + timedelta(days=_PAIR_LOOKAHEAD_DAYS)).isoformat(),
            "review_only": False,
            "include_closed": True,
            "max_results": 30,
        },
        access=access,
    )
    base = {
        "pair": True,
        "topic": topic,
        "anchor_date": anchor.isoformat(),
        "source": "odata",
        "readonly": True,
        "entity": PROTOCOL_ENTITY,
        "method": "odata_board_protocol_pair",
    }
    if listed.get("error"):
        return {**base, "current": None, "previous": None, "error": listed["error"],
                "gaps": [f"протоколы «{topic}» не прочитаны: {listed['error']}"]}
    protocols = listed.get("protocols") or []
    current_row, previous_row = _pick_pair(protocols, anchor=anchor, explicit_day=explicit is not None)
    from concurrent.futures import ThreadPoolExecutor

    today = date.today()
    current_gaps: list[str] = []
    previous_gaps: list[str] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        current_job = pool.submit(_pair_side, current_row, today=today, gaps=current_gaps, label="текущий")
        previous_job = pool.submit(_pair_side, previous_row, today=today, gaps=previous_gaps, label="прошлый")
        current, previous = current_job.result(), previous_job.result()
    gaps = current_gaps + previous_gaps
    _mark_not_carried(current, previous)
    if current is None:
        gaps.append(
            f"протокол текущего заседания «{topic}» "
            + (f"на {anchor.isoformat()} " if explicit else "(черновик «Подготовлен») ")
            + "в 1С не найден"
        )
    if previous is None:
        gaps.append(f"протокол прошлого заседания «{topic}» в 1С не найден")
    names = " / ".join(
        f"{side['number']} от {(side.get('date') or '')[:10]}"
        for side in (current, previous)
        if side
    )
    reconciliation = reconciliation_rows(current, previous)
    with_errors = sum(1 for row in reconciliation if row["errors"])
    files_note = "; ".join(
        f"файлов у {side['number']}: {len(side.get('files') or [])}" for side in (current, previous) if side
    )
    package_rows = package_table(
        [(current, "текущий"), (previous, "прошлый")],
        (current or {}).get("agenda") or (previous or {}).get("agenda") or [],
    )
    return {
        **base,
        "package_table_markdown": package_table_markdown(package_rows),
        "current": current,
        "previous": previous,
        "reconciliation": reconciliation,
        "package_table": package_rows,
        "gaps": gaps,
        "candidates": [
            {key: item.get(key) for key in ("number", "date", "status", "posted", "ref_key")}
            for item in sorted(protocols, key=lambda row: row.get("date") or "", reverse=True)[:10]
        ],
        "summary": (
            f"«{topic}»: {names or 'протоколы не найдены'}; сверено строк: {len(reconciliation)}, "
            f"с ошибками: {with_errors}; {files_note + '; ' if files_note else ''}пробелов: {len(gaps)}"
        ),
    }


def reconciliation_rows(
    current: dict[str, Any] | None,
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """One row per assignment / task / agenda question — the table the agent reports as is."""
    rows: list[dict[str, Any]] = []
    for side, label in ((previous, "прошлый"), (current, "текущий")):
        check = (side or {}).get("check") or {}
        number = (side or {}).get("number") or ""
        files = (side or {}).get("files") or []
        posted = bool((side or {}).get("posted"))
        status_1c = str((side or {}).get("status") or "")
        in_card = (
            [f"к протоколу приложено файлов: {len(files)} (к строке в 1С не привязаны)"] if files else []
        )
        for item in check.get("decisions") or []:
            errors = [
                f"отметка «Наличие артефакта» не стоит; к протоколу приложено файлов: {len(files)} — "
                "сверь по содержанию, относятся ли они к поручению"
                if files and error.startswith("нет артефакта")
                else error
                for error in item["findings"]
            ]
            rows.append(
                {
                    "protocol": f"{label} {number}",
                    "section": "поручение",
                    "item": item["item"],
                    "text": item["text"],
                    "responsible": "",
                    "due": item["due"],
                    "status": item["status"],
                    "ok": ["артефакт есть"] * item["has_artifact"]
                    + ([f"исполнено {item['done_date']}".strip()] if item["done_date"] else [])
                    + (["перенесено в текущий протокол"] if item.get("carried") else [])
                    + ([f"протокол проведён, статус «{status_1c}»"] if posted else []),
                    "errors": errors,
                }
            )
        for task in check.get("tasks") or []:
            rows.append(
                {
                    "protocol": f"{label} {number}",
                    "section": "поставленная задача",
                    "item": task["item"],
                    "text": task["text"],
                    "responsible": task["executor"],
                    "due": task["due"],
                    "status": "комплект полный" if task["complete"] else "неполный",
                    "ok": ["файл есть"] * task["has_file"] + ["отправлена в 1С"] * task["sent"],
                    "errors": list(task["findings"]),
                }
            )
        for question in check.get("agenda") or []:
            rows.append(
                {
                    "protocol": f"{label} {number}",
                    "section": "вопрос повестки",
                    "item": question["item"],
                    "text": question["question"],
                    "responsible": question["responsible"],
                    "due": "",
                    "status": "комплект полный" if question["complete"] else "неполный",
                    "ok": ["материал приложен"] * question["has_file"] + (in_card if not question["has_file"] else []),
                    "errors": list(question["findings"]),
                }
            )
    return rows


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
