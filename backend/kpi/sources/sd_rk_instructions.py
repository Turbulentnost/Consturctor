"""Реестр и контроль поручений СД+РК.

План месяца — OData: все протоколы ПСД и все поручения АСТ00 за период.
Факт — те же номера есть в ActionTracker.xlsx, который ведёт агент.

ПЛ-НПО-010: факт = min(KPI3.1, KPI3.2).
KPI3.1 = R24 / Rвсего. Rвсего — протоколы ПСД + поручения с Date в периоде.
R24 — строка есть в Excel, для поручения заполнены текст/владелец/срок,
и карточка не позже 24 часов после даты решения.
KPI3.2 = Rконтроль / Rактив по открытым поручениям: вложение или
еженедельный отчёт не старше 7 дней.
Цель ≥ 95%, иначе оценка = факт / 95%.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from kpi.sources.sd_rk_protocols import gate_score, parse_day

TARGET_PCT = 95
WEIGHT = 25
CONTROL_DAYS = 7
SD_TOPIC = "совет директоров"
RK_TOPIC = "ревизион"
PROTOCOL_SD_RE = re.compile(r"псд[_\s]+\d", re.IGNORECASE)
PROTOCOL_RK_RE = re.compile(r"рк_{1,2}\d", re.IGNORECASE)
CLOSED_STATUSES = {
    "done",
    "closed",
    "закрыт",
    "закрыто",
    "исполнено",
    "принято",
    "completed",
    "выполнено",
    "принято и закрыто",
}
COLUMN_ALIASES = {
    "id": ("id", "ID"),
    "source": ("source", "Источник", "Источник (CEO/ОКМ/комитет)"),
    "decided": ("decided", "Дата решения"),
    "text": ("text", "Поручение (результат/артефакт)", "Поручение"),
    "owner": ("owner", "Владелец"),
    "due": ("due", "Срок"),
    "status": ("status", "Статус"),
    "evidence": (
        "evidence",
        "Ссылка на результат/документы",
        "Ссылка на результат/док-ты",
    ),
    "entered": ("entered", "created", "Дата внесения", "Дата появления"),
    "basis": ("basis", "Основание", "Орган"),
    "topic": ("topic", "Тема", "ОЧем"),
}


def cell(row: dict[str, Any], name: str) -> Any:
    for key in COLUMN_ALIASES.get(name, (name,)):
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def normalize_number(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) < 3:
        return text
    mapped: list[str] = []
    for char in text[:3]:
        if char in "Aa":
            mapped.append("А")
        elif char in "CcСс":
            mapped.append("С")
        elif char in "TtТт":
            mapped.append("Т")
        else:
            mapped.append(char)
    if "".join(mapped) == "АСТ" and text[:3] != "АСТ":
        return "АСТ" + text[3:]
    return text


def assignment_number(row: dict[str, Any]) -> str:
    for raw in (cell(row, "source"), cell(row, "id"), row.get("number")):
        number = normalize_number(raw)
        if number.startswith("АСТ"):
            return number
    return ""


def protocol_number(row: dict[str, Any]) -> str:
    for raw in (cell(row, "source"), cell(row, "id"), row.get("number")):
        number = str(raw or "").strip().split()[0] if raw else ""
        if number.startswith("ПСД") or number.startswith("РК"):
            return number
    return ""


def is_protocol_dump(row: dict[str, Any]) -> bool:
    return bool(protocol_number(row)) and not assignment_number(row)


def classify_instruction(*parts: Any) -> str | None:
    tokens = [str(part or "").strip() for part in parts if str(part or "").strip()]
    blob = " ".join(tokens).casefold()
    if PROTOCOL_SD_RE.search(blob) or SD_TOPIC in blob:
        return "sd"
    if PROTOCOL_RK_RE.search(blob) or "ревизионн" in blob or "план работ рк" in blob:
        return "rk"
    return None


def parse_dt(value: Any) -> tuple[datetime, bool] | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.year < 2000:
            return None
        has_time = not (value.hour == 0 and value.minute == 0 and value.second == 0)
        return value.replace(tzinfo=None), has_time
    if isinstance(value, date):
        if value.year < 2000:
            return None
        return datetime.combine(value, datetime.min.time()), False
    text = str(value).strip()
    if "T" in text or " " in text:
        stamp = text.replace("Z", "").replace(" ", "T", 1)
        try:
            parsed = datetime.fromisoformat(stamp[:19])
        except ValueError:
            day = parse_day(text)
            if day is None or day.year < 2000:
                return None
            return datetime.combine(day, datetime.min.time()), False
        if parsed.year < 2000:
            return None
        has_time = not (parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0)
        return parsed, has_time
    day = parse_day(text)
    if day is None or day.year < 2000:
        return None
    return datetime.combine(day, datetime.min.time()), False


def _field(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.startswith("0001"):
        return ""
    return text


def _alive_day(value: Any) -> date | None:
    parsed = parse_dt(value)
    return parsed[0].date() if parsed else None


def _in_range(day: date | None, date_from: date | None, date_to: date | None) -> bool:
    if day is None:
        return False
    if date_from is not None and day < date_from:
        return False
    if date_to is not None and day > date_to:
        return False
    return True


def within_24h(entered: datetime, decided: datetime, *, precise: bool) -> bool:
    if precise:
        return entered <= decided + timedelta(hours=24)
    return entered.date() <= decided.date() + timedelta(days=1)


def is_closed(status: Any, *, card_open: bool | None = None) -> bool:
    key = "".join(str(status or "").casefold().split())
    if key in {"".join(item.split()) for item in CLOSED_STATUSES}:
        return True
    if key and card_open is None:
        return False
    if not key and card_open is False:
        return True
    return card_open is False


def _first_line(card: dict[str, Any] | None, field: str) -> str:
    if not card:
        return ""
    for line in card.get("lines") or []:
        if not isinstance(line, dict):
            continue
        text = _field(line.get(field))
        if text:
            return text
    return ""


def _filled(row: dict[str, Any] | None, card: dict[str, Any] | None) -> tuple[str, str, str]:
    row = row or {}
    text = _field(cell(row, "text")) or _field((card or {}).get("topic")) or _first_line(card, "text")
    owner = _field(cell(row, "owner")) or _first_line(card, "executor") or _field((card or {}).get("reporter"))
    due = _field(cell(row, "due")) or _field((card or {}).get("due")) or _first_line(card, "due")
    return text, owner, due


def _tracker_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for number in (assignment_number(row), protocol_number(row)):
            if number:
                index[number] = row
    return index


def _has_control(row: dict[str, Any] | None, card: dict[str, Any] | None, as_of: date) -> bool:
    since = as_of - timedelta(days=CONTROL_DAYS)
    if card:
        for item in card.get("files") or []:
            if not isinstance(item, dict):
                continue
            created = _alive_day(item.get("created"))
            if created is not None and since <= created <= as_of:
                return True
        for key in ("weekly_report_date", "final_report_date"):
            stamp = _alive_day(card.get(key))
            if stamp is not None and since <= stamp <= as_of:
                return True
    if row:
        stamp = _alive_day(cell(row, "evidence"))
        if stamp is not None and since <= stamp <= as_of:
            return True
    return False


def _ratio(ok: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(100.0 * ok / total, 1)


def _expected_assignments(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        number = normalize_number(card.get("number"))
        day = _alive_day(card.get("date"))
        if not number:
            continue
        items.append(
            {
                "item_kind": "assignment",
                "kind": classify_instruction(card.get("basis"), card.get("topic"), card.get("number")) or "",
                "number": number,
                "decided": day,
                "source": card,
            }
        )
    return items


def _expected_protocols(protocols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in protocols:
        if not isinstance(row, dict):
            continue
        number = str(row.get("number") or "").strip()
        if not number.startswith("ПСД"):
            continue
        items.append(
            {
                "item_kind": "protocol",
                "kind": "sd",
                "number": number,
                "decided": _alive_day(row.get("date")),
                "source": row,
            }
        )
    return items


def score_instruction_kpi(
    tracker_rows: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    protocols: list[dict[str, Any]] | None = None,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    tracker = _tracker_index(tracker_rows)
    rows: list[dict[str, Any]] = []
    for item in (*_expected_assignments(cards), *_expected_protocols(protocols or [])):
        decided = item["decided"]
        in_period = _in_range(decided, date_from, date_to) if date_from or date_to else decided is not None
        hit = tracker.get(item["number"])
        in_tracker = hit is not None
        source = item["source"]
        if item["item_kind"] == "protocol":
            complete = in_tracker
            entered_raw = parse_dt(cell(hit, "entered")) if hit else None
            decided_dt = parse_dt(decided)
            precise = bool(entered_raw and decided_dt and entered_raw[1] and decided_dt[1])
            entered = entered_raw[0] if entered_raw else (decided_dt[0] if in_tracker and decided_dt else None)
            on_time = bool(in_period and in_tracker)
            active = False
            control = False
            status = str(source.get("status") or "")
        else:
            text, owner, due = _filled(hit, source)
            complete = bool(in_tracker and text and owner and due)
            decided_dt = parse_dt(cell(hit, "decided")) if hit else None
            if decided_dt is None:
                decided_dt = parse_dt(source.get("date"))
            entered_raw = parse_dt(cell(hit, "entered")) if hit else None
            if entered_raw is None and in_tracker:
                entered_raw = parse_dt(source.get("date"))
            precise = bool(decided_dt and entered_raw and decided_dt[1] and entered_raw[1])
            entered = entered_raw[0] if entered_raw else None
            decided_at = decided_dt[0] if decided_dt else None
            on_time = bool(
                in_period
                and complete
                and entered is not None
                and decided_at is not None
                and within_24h(entered, decided_at, precise=precise)
            )
            status = (cell(hit, "status") if hit else None) or source.get("status") or ""
            active = not is_closed(status, card_open=None if hit and cell(hit, "status") else source.get("open"))
            control = bool(active and _has_control(hit, source, as_of))
        kind = item["kind"] or ("sd" if item["item_kind"] == "protocol" else "")
        rows.append(
            {
                "item_kind": item["item_kind"],
                "kind": kind,
                "kind_label": "ПСД" if item["item_kind"] == "protocol" else "АСТ",
                "number": item["number"],
                "decided": decided.isoformat() if decided else "",
                "entered": entered.date().isoformat() if entered else "",
                "in_tracker": in_tracker,
                "complete": complete,
                "in_period": in_period,
                "on_time": on_time,
                "active": active,
                "control": control,
                "status": str(status or ""),
            }
        )
    period_rows = [row for row in rows if row["in_period"]]
    active_rows = [row for row in rows if row["item_kind"] == "assignment" and row["active"]]
    r_total = len(period_rows)
    r24 = sum(1 for row in period_rows if row["on_time"])
    r_in_tracker = sum(1 for row in period_rows if row["in_tracker"])
    r_active = len(active_rows)
    r_control = sum(1 for row in active_rows if row["control"])
    kpi3_1 = _ratio(r24, r_total)
    kpi3_2 = _ratio(r_control, r_active)
    parts = [item for item in (kpi3_1, kpi3_2) if item is not None]
    fact_pct = min(parts) if parts else None
    score_pct = gate_score(fact_pct) if fact_pct is not None else None
    return {
        "as_of": as_of.isoformat(),
        "r_total": r_total,
        "r24": r24,
        "r_in_tracker": r_in_tracker,
        "r_active": r_active,
        "r_control": r_control,
        "kpi3_1_pct": kpi3_1,
        "kpi3_2_pct": kpi3_2,
        "fact_pct": fact_pct,
        "score_pct": score_pct,
        "weight": WEIGHT,
        "contrib_pct": round(score_pct * WEIGHT / 100.0, 1) if score_pct is not None else None,
        "rows": rows,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"{'тип':<4} {'номер':<18} {'1С':<12} {'Excel':<6} {'R24':<6} {'актив':<6} {'контроль':<8}",
        "-" * 78,
    ]
    for row in report.get("rows") or []:
        if not row.get("in_period") and not row.get("active"):
            continue
        lines.append(
            f"{row.get('kind_label', ''):<4} {str(row.get('number') or '—'):<18} "
            f"{str(row.get('decided') or '—'):<12} "
            f"{'да' if row.get('in_tracker') else 'нет':<6} "
            f"{'да' if row.get('on_time') else 'нет':<6} "
            f"{'да' if row.get('active') else 'нет':<6} "
            f"{'да' if row.get('control') else 'нет':<8}"
        )
    lines.append("-" * 78)
    k1 = report.get("kpi3_1_pct")
    k2 = report.get("kpi3_2_pct")
    fact = report.get("fact_pct")
    score = report.get("score_pct")
    lines.append(
        f"в Excel {report.get('r_in_tracker')}/{report.get('r_total')}  "
        f"KPI3.1 R24/Rвсего = {report.get('r24')}/{report.get('r_total')}  "
        f"{'нет данных' if k1 is None else f'{k1}%'}"
    )
    lines.append(
        f"KPI3.2 Rконтроль/Rактив = {report.get('r_control')}/{report.get('r_active')}  "
        f"{'нет данных' if k2 is None else f'{k2}%'}"
    )
    lines.append(
        f"факт min = {'нет данных' if fact is None else f'{fact}%'}  "
        f"оценка {'нет данных' if score is None else f'{score}%'}"
    )
    return "\n".join(lines)
