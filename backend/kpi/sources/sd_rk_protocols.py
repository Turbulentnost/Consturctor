"""Своевременность протоколов СД+РК: план — Outlook «Совещания», факт — OData.

ПЛ-НПО-010: факт = Pвовремя / Pвсего, протокол не позднее T+2 рабочих дня,
цель ≥ 95%, иначе оценка = факт / 95%.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

TARGET_PCT = 95
WEIGHT = 25
PREP_MARKERS = (
    "повестку заседания",
    "формирует и утверждает",
    "секретарь рк еженедельно",
)
SD_TOPIC = "совет директоров"
RK_TOPIC = "ревизион"


def parse_day(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def add_workdays(value: date, days: int) -> date:
    """T+N рабочих дней, только сб/вс (праздники РФ не зашиты)."""
    cursor = value
    left = days
    while left > 0:
        cursor += timedelta(days=1)
        if cursor.isoweekday() < 6:
            left -= 1
    return cursor


def sub_workdays(value: date, days: int) -> date:
    """T−N рабочих дней, только сб/вс (праздники РФ не зашиты)."""
    cursor = value
    left = days
    while left > 0:
        cursor -= timedelta(days=1)
        if cursor.isoweekday() < 6:
            left -= 1
    return cursor


def protocol_deadline(meeting_day: date) -> date:
    return add_workdays(meeting_day, 2)


def gate_score(fact_pct: float, *, target_pct: int = TARGET_PCT) -> float:
    if fact_pct + 1e-9 >= target_pct:
        return 100.0
    return round(fact_pct / target_pct * 100.0, 1)


def classify_meeting(subject: str) -> str | None:
    text = str(subject or "").casefold()
    if any(marker in text for marker in PREP_MARKERS):
        return None
    if SD_TOPIC in text:
        return "sd"
    if RK_TOPIC in text:
        return "rk"
    return None


def classify_protocol(number: str, topic: str) -> str | None:
    number_text = str(number or "").strip()
    topic_text = str(topic or "").casefold()
    if SD_TOPIC in topic_text:
        return "sd"
    if number_text.startswith("РК") or RK_TOPIC in topic_text:
        return "rk"
    return None


def protocol_issued(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").strip()
    if status == "Подготовлен" or row.get("needs_review"):
        return False
    return bool(row.get("posted"))


def meetings_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        subject = str(event.get("subject") or event.get("title") or "")
        kind = classify_meeting(subject)
        meeting_day = parse_day(event.get("start") or event.get("date"))
        if kind is None or meeting_day is None:
            continue
        key = (kind, meeting_day.isoformat())
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "kind": kind,
                "subject": subject,
                "plan_date": meeting_day,
                "deadline": protocol_deadline(meeting_day),
            }
        )
    rows.sort(key=lambda item: (item["plan_date"], item["kind"]))
    return rows


def protocols_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = str(row.get("number") or row.get("Number") or "")
        topic = str(row.get("meeting_topic") or row.get("topic") or "")
        kind = classify_protocol(number, topic)
        protocol_day = parse_day(row.get("date") or row.get("Date"))
        if kind is None or protocol_day is None:
            continue
        items.append(
            {
                "kind": kind,
                "number": number,
                "topic": topic,
                "date": protocol_day,
                "issued": protocol_issued(row),
                "status": str(row.get("status") or ""),
                "posted": bool(row.get("posted")),
            }
        )
    return items


def _match_protocol(
    meeting: dict[str, Any],
    protocols: list[dict[str, Any]],
    used: set[int],
) -> dict[str, Any] | None:
    plan = meeting["plan_date"]
    deadline = meeting["deadline"]
    best: tuple[int, int, int, dict[str, Any]] | None = None
    for index, protocol in enumerate(protocols):
        if index in used or protocol["kind"] != meeting["kind"]:
            continue
        day = protocol["date"]
        if day < plan - timedelta(days=1) or day > deadline:
            continue
        delta = abs((day - plan).days)
        score = 0 if day == plan else 10 + delta
        candidate = (score, delta, index, protocol)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None
    used.add(best[2])
    return best[3]


def score_protocol_kpi(
    events: list[dict[str, Any]],
    protocols: list[dict[str, Any]],
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    meetings = meetings_from_events(events)
    if date_from is not None:
        meetings = [row for row in meetings if row["plan_date"] >= date_from]
    if date_to is not None:
        meetings = [row for row in meetings if row["plan_date"] <= date_to]
    catalog = protocols_from_rows(protocols)
    used: set[int] = set()
    rows: list[dict[str, Any]] = []
    for meeting in meetings:
        hit = _match_protocol(meeting, catalog, used)
        due = meeting["deadline"] <= as_of
        issued = bool(hit and hit["issued"])
        on_time = bool(due and issued and hit is not None and hit["date"] <= meeting["deadline"])
        rows.append(
            {
                "kind": meeting["kind"],
                "kind_label": "СД" if meeting["kind"] == "sd" else "РК",
                "subject": meeting["subject"],
                "plan_date": meeting["plan_date"].isoformat(),
                "deadline": meeting["deadline"].isoformat(),
                "due": due,
                "protocol_number": hit["number"] if hit else "",
                "protocol_date": hit["date"].isoformat() if hit else "",
                "protocol_status": hit["status"] if hit else "",
                "issued": issued,
                "on_time": on_time,
            }
        )
    due_rows = [row for row in rows if row["due"]]
    total = len(due_rows)
    on_time = sum(1 for row in due_rows if row["on_time"])
    fact_pct = round(100.0 * on_time / total, 1) if total else None
    score_pct = gate_score(fact_pct) if fact_pct is not None else None
    return {
        "as_of": as_of.isoformat(),
        "p_total": total,
        "p_on_time": on_time,
        "fact_pct": fact_pct,
        "score_pct": score_pct,
        "weight": WEIGHT,
        "contrib_pct": round(score_pct * WEIGHT / 100.0, 1) if score_pct is not None else None,
        "rows": rows,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"{'орган':<4} {'план':<12} {'T+2':<12} {'протокол':<18} {'факт':<12} {'вовремя':<8}",
        "-" * 78,
    ]
    for row in report.get("rows") or []:
        if not row.get("due"):
            mark = "ждёт"
        elif row.get("on_time"):
            mark = "да"
        else:
            mark = "нет"
        lines.append(
            f"{row.get('kind_label', ''):<4} {str(row.get('plan_date') or ''):<12} "
            f"{str(row.get('deadline') or ''):<12} {str(row.get('protocol_number') or '—'):<18} "
            f"{str(row.get('protocol_date') or '—'):<12} {mark:<8}"
        )
    lines.append("-" * 78)
    total = report.get("p_total") or 0
    on_time = report.get("p_on_time") or 0
    fact = report.get("fact_pct")
    score = report.get("score_pct")
    fact_text = "нет данных" if fact is None else f"{fact}%"
    score_text = "нет данных" if score is None else f"{score}%"
    lines.append(f"Pвовремя / Pвсего = {on_time}/{total}  факт {fact_text}  оценка {score_text}")
    return "\n".join(lines)
