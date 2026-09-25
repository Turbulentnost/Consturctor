"""Своевременность пакета СД+РК: предыдущий протокол к следующему Outlook.

План — заседания СД/РК в календаре «Совещания».
Факт — предыдущий протокол той же серии со статусом «Закрыт» или «НаИсполнении»:
в этих статусах материалы уже разосланы.
Пакет вовремя, если дата протокола не позже T−2 рабочих дня
до следующего совещания в Outlook.
Отдельного поля «ДатаЗакрытия» нет — берём Date.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from kpi.sources.sd_rk_protocols import (
    TARGET_PCT,
    WEIGHT,
    classify_meeting,
    classify_protocol,
    gate_score,
    parse_day,
    sub_workdays,
)

READY_STATUSES = frozenset({"закрыт", "наисполнении"})
_SPACE_RE = re.compile(r"\s+")


def package_deadline(meeting_day: date) -> date:
    return sub_workdays(meeting_day, 2)


def _folded(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").replace("«", " ").replace("»", " ").replace('"', " ")).strip().casefold()


def series_key(kind: str, text: str) -> str:
    """Серия заседания: РК одна, СД делим на «по ГК» и «ИТЦ/Авион»."""
    if kind == "rk":
        return "rk"
    folded = _folded(text)
    if any(token in folded for token in ("итц", "авион", "магакян")):
        return "sd:itc"
    if "групп" in folded or "по гк" in folded or folded.endswith(" гк"):
        return "sd:gk"
    return "sd:gk" if kind == "sd" else f"{kind}:{folded[:48]}"


def protocol_ready_at(row: dict[str, Any]) -> date | None:
    status = str(row.get("status") or row.get("Статус") or "").strip().casefold().replace(" ", "")
    if status not in READY_STATUSES:
        return None
    return parse_day(
        row.get("closed_at")
        or row.get("ready_at")
        or row.get("ДатаЗакрытия")
        or row.get("date")
        or row.get("Date")
    )


def packages_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = str(row.get("number") or row.get("Number") or "")
        topic = str(row.get("meeting_topic") or row.get("topic") or "")
        kind = classify_protocol(number, topic)
        meeting_day = parse_day(row.get("date") or row.get("Date"))
        if kind is None or meeting_day is None:
            continue
        items.append(
            {
                "kind": kind,
                "number": number,
                "topic": topic,
                "series": series_key(kind, topic),
                "date": meeting_day,
                "closed_at": protocol_ready_at(row),
                "next_meeting": parse_day(
                    row.get("next_meeting") or row.get("ДатаСледующегоСовещания")
                ),
                "status": str(row.get("status") or row.get("Статус") or ""),
            }
        )
    items.sort(key=lambda item: (item["series"], item["date"], item["number"]))
    return items


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
                "series": series_key(kind, subject),
                "plan_date": meeting_day,
                "deadline": package_deadline(meeting_day),
            }
        )
    rows.sort(key=lambda item: (item["series"], item["plan_date"]))
    return rows


def _previous_protocol(meeting: dict[str, Any], packages: list[dict[str, Any]]) -> dict[str, Any] | None:
    previous: dict[str, Any] | None = None
    for item in packages:
        if item["series"] != meeting["series"] or item["kind"] != meeting["kind"]:
            continue
        if item["date"] >= meeting["plan_date"]:
            continue
        if previous is None or item["date"] > previous["date"]:
            previous = item
    return previous


def meetings_from_packages(packages: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Без Outlook: следующее заседание — ДатаСледующегоСовещания или дата следующего протокола."""
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    by_series: dict[str, list[dict[str, Any]]] = {}
    for item in packages:
        by_series.setdefault(item["series"], []).append(item)
    for series_items in by_series.values():
        ordered = sorted(series_items, key=lambda item: item["date"])
        for index, previous in enumerate(ordered):
            nxt = previous.get("next_meeting")
            if nxt is None and index + 1 < len(ordered):
                nxt = ordered[index + 1]["date"]
            if nxt is None:
                continue
            meeting = {
                "kind": previous["kind"],
                "subject": previous["topic"] or previous["number"],
                "series": previous["series"],
                "plan_date": nxt,
                "deadline": package_deadline(nxt),
            }
            pairs.append((meeting, previous))
    pairs.sort(key=lambda pair: (pair[0]["series"], pair[0]["plan_date"]))
    return pairs


def _in_period(day: date, date_from: date | None, date_to: date | None) -> bool:
    if date_from is not None and day < date_from:
        return False
    if date_to is not None and day > date_to:
        return False
    return True


def score_package_kpi(
    events: list[dict[str, Any]],
    protocols: list[dict[str, Any]],
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    catalog = packages_from_rows(protocols)
    if events:
        meetings = [
            row
            for row in meetings_from_events(events)
            if _in_period(row["plan_date"], date_from, date_to)
        ]
        pairs = [(meeting, _previous_protocol(meeting, catalog)) for meeting in meetings]
    else:
        pairs = [
            (meeting, previous)
            for meeting, previous in meetings_from_packages(catalog)
            if _in_period(meeting["plan_date"], date_from, date_to)
        ]

    rows: list[dict[str, Any]] = []
    for meeting, previous in pairs:
        due = meeting["deadline"] <= as_of
        closed_at = previous.get("closed_at") if previous else None
        prepared = closed_at is not None
        on_time = bool(due and closed_at is not None and closed_at <= meeting["deadline"])
        rows.append(
            {
                "kind": meeting["kind"],
                "kind_label": "СД" if meeting["kind"] == "sd" else "РК",
                "series": meeting["series"],
                "subject": meeting["subject"],
                "plan_date": meeting["plan_date"].isoformat(),
                "deadline": meeting["deadline"].isoformat(),
                "due": due,
                "protocol_number": previous.get("number", "") if previous else "",
                "protocol_date": previous["date"].isoformat() if previous else "",
                "closed_at": closed_at.isoformat() if closed_at else "",
                "prepared": prepared,
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
        "z_total": total,
        "z_on_time": on_time,
        "fact_pct": fact_pct,
        "score_pct": score_pct,
        "weight": WEIGHT,
        "target_pct": TARGET_PCT,
        "contrib_pct": round(score_pct * WEIGHT / 100.0, 1) if score_pct is not None else None,
        "rows": rows,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"{'орган':<4} {'план':<12} {'T-2':<12} {'пред.прот.':<18} {'закрыт':<12} {'вовремя':<8}",
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
            f"{str(row.get('closed_at') or '—'):<12} {mark:<8}"
        )
    lines.append("-" * 78)
    total = report.get("z_total") or 0
    on_time = report.get("z_on_time") or 0
    fact = report.get("fact_pct")
    score = report.get("score_pct")
    fact_text = "нет данных" if fact is None else f"{fact}%"
    score_text = "нет данных" if score is None else f"{score}%"
    lines.append(f"Zвовремя / Zвсего = {on_time}/{total}  факт {fact_text}  оценка {score_text}")
    return "\n".join(lines)
