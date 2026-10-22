"""Качество протоколов СД+РК секретаря (Ильченко).

В Document_ТД_Протокол нет поля возврата / доработки. Протоколы, которые
создавала Ильченко, считаем без возвратов: Vоши = 0, факт = 100% при Vвсего > 0.
"""

from __future__ import annotations

from typing import Any

from kpi.sources.sd_rk_protocols import classify_protocol, parse_day

TARGET_PCT = 98
WEIGHT = 25


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
                "status": str(row.get("status") or ""),
                "returned": False,
            }
        )
    return items


def score_quality_kpi(protocols: list[dict[str, Any]]) -> dict[str, Any]:
    rows = protocols_from_rows(protocols)
    total = len(rows)
    errors = 0
    fact_pct = 100.0 if total else None
    score_pct = 100.0 if total else None
    return {
        "v_total": total,
        "v_errors": errors,
        "fact_pct": fact_pct,
        "score_pct": score_pct,
        "weight": WEIGHT,
        "contrib_pct": round(score_pct * WEIGHT / 100.0, 1) if score_pct is not None else None,
        "assumption": "ilchenko_protocols_no_returns",
        "rows": rows,
    }
