"""План-факт совещаний руководителя — так же, как Отчет.ТД_ПланФактСовещаний в 1С.

План — РегистрСведений.ТД_КалендарьСовещаний: записи с ДатаСовещания в периоде.
Факт — Документ.ТД_Протокол без пометки удаления, по дате протокола.
Отбор как в отчёте: руководитель совещания, вид совещания (Плановое, Отчетное,
Селектор), тема круга управления = Да. Отклонение = факт − план по теме и дню.
Нарушение — запланированное совещание, по которому в этот день нет протокола.
Шкала ПЛ-НПО-010: меньше 5 нарушений → 100%, от 5 до 8 → 50%, больше 8 → 0%.

Пока календарь в 1С пуст или не опубликован в OData, план временно = факт
(plan_from_fact); как только в регистре появятся записи, берётся настоящий план.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any

from kpi.sources.assistant_meetings import (
    LEADER,
    LEADER_KEY,
    PROTOCOL_ENTITY,
    THEME_ENTITY,
    USER_ENTITY,
    parse_day,
    violation_score,
)

PLAN_ENTITY = "InformationRegister_ТД_КалендарьСовещаний"
KINDS = ("Плановое", "Отчетное", "Селектор")
WEIGHT = 40
PAGE = 200
MAX_ROWS = 5000

SOURCE = {
    "kind": "onec",
    "loader": "odata",
    "report": "Отчет.ТД_ПланФактСовещаний",
    "plan_entity": PLAN_ENTITY,
    "fact_entity": PROTOCOL_ENTITY,
    "leader": LEADER,
    "kinds": list(KINDS),
    "management_circle": True,
    "plan_from_fact": True,
}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _kind_ok(value: Any, kinds: set[str]) -> bool:
    return str(value or "").strip().casefold() in kinds


def _key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "да", "истина", "1"}
    return value is True


def score_report_plan_fact(
    plan_rows: list[dict[str, Any]] | None,
    protocols: list[dict[str, Any]] | None,
    themes: list[dict[str, Any]] | None,
    *,
    leader_key: str,
    as_of: date,
    date_from: date,
    date_to: date,
    kinds: tuple[str, ...] = KINDS,
    management_circle: bool = True,
    plan_error: str = "",
    plan_from_fact: bool = False,
) -> dict[str, Any]:
    wanted = {kind.casefold() for kind in kinds}
    leader = _key(leader_key)
    by_theme = {_key(row.get("Ref_Key")): row for row in _rows(themes) if row.get("Ref_Key")}

    def theme_ok(theme_id: str) -> bool:
        if not management_circle:
            return True
        theme = by_theme.get(theme_id)
        return bool(theme) and _truthy(theme.get("ТемаКругаУправления"))

    def in_period(day: date | None) -> bool:
        return day is not None and date_from <= day <= date_to

    plan: Counter[tuple[date, str]] = Counter()
    for row in _rows(plan_rows):
        theme_id = _key(row.get("ТемаСовещания_Key"))
        day = parse_day(row.get("ДатаСовещания"))
        if not in_period(day) or _key(row.get("РуководительСовещания_Key")) != leader:
            continue
        theme = by_theme.get(theme_id) or {}
        if not _kind_ok(theme.get("ВидСовещания"), wanted) or not theme_ok(theme_id):
            continue
        plan[(day, theme_id)] += 1

    fact: Counter[tuple[date, str]] = Counter()
    for row in _rows(protocols):
        if _truthy(row.get("DeletionMark")):
            continue
        theme_id = _key(row.get("ТемаСовещания_Key"))
        day = parse_day(row.get("Date"))
        if not in_period(day) or _key(row.get("Руководитель_Key")) != leader:
            continue
        if not _kind_ok(row.get("ВидСовещания"), wanted) or not theme_ok(theme_id):
            continue
        fact[(day, theme_id)] += 1

    plan_source = "calendar"
    if plan_from_fact and (plan_error or not plan):
        plan = Counter(fact)
        plan_source = "fact"

    days: dict[date, dict[str, int]] = {}
    violations = 0
    for key in set(plan) | set(fact):
        day = key[0]
        bucket = days.setdefault(day, {"plan": 0, "fact": 0})
        bucket["plan"] += plan[key]
        bucket["fact"] += fact[key]
        violations += max(plan[key] - fact[key], 0)
    rows = [
        {
            "day": day.isoformat(),
            "plan": item["plan"],
            "fact": item["fact"],
            "deviation": item["fact"] - item["plan"],
        }
        for day, item in sorted(days.items())
    ]
    plan_total = sum(plan.values())
    fact_total = sum(fact.values())
    scorable = plan_total and (plan_source == "fact" or not plan_error)
    score = violation_score(violations) if scorable else None
    covered = plan_total - violations
    return {
        "as_of": as_of.isoformat(),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "plan_total": plan_total,
        "fact_total": fact_total,
        "plan_source": plan_source,
        "violations": violations if plan_total else None,
        "fact_pct": round(100.0 * covered / plan_total, 1) if scorable else None,
        "score_pct": score,
        "weight": WEIGHT,
        "contrib_pct": round(score * WEIGHT / 100.0, 1) if score is not None else None,
        "plan_error": plan_error,
        "rows": rows,
    }


def format_report(report: dict[str, Any]) -> str:
    fact = report.get("fact_total") or 0
    if report.get("plan_source") == "fact":
        reason = (
            "регистр «Календарь совещаний» не опубликован в OData 1С"
            if report.get("plan_error")
            else "в «Календаре совещаний» 1С нет плана за период"
        )
        return (
            f"План = факт = {fact} (временно: {reason}). "
            f"Нарушений {report.get('violations') or 0}, оценка {report.get('score_pct')}%."
        )
    if report.get("plan_error"):
        return (
            f"Протоколов (факт): {fact}. План не получен: {report['plan_error']} "
            "Оценку без плана не ставим."
        )
    plan = report.get("plan_total") or 0
    if not plan:
        return (
            f"Протоколов (факт): {fact}. В «Календаре совещаний» 1С нет плана за период — "
            "в отчёте «План-факт совещаний» колонка плана тоже пустая. Оценку без плана не ставим."
        )
    return (
        f"План {plan}, факт {fact}, нарушений {report.get('violations')}, "
        f"оценка {report.get('score_pct')}%."
    )


def _page(ctx: Any, entity: str, filt: str, select: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = 0
    while skip < MAX_ROWS:
        batch = _rows(
            ctx.load_for(
                {"loader": "odata", "entity": entity, "filter": filt, "select": select, "top": PAGE, "skip": skip}
            )
        )
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        skip += PAGE
    return rows


def _leader_key(ctx: Any, name: str, fallback: str) -> str:
    safe = name.replace("'", "''")
    for row in _page(ctx, USER_ENTITY, f"Description eq '{safe}'", "Ref_Key,Description"):
        if str(row.get("Description") or "").strip().casefold() == name.casefold() and row.get("Ref_Key"):
            return str(row["Ref_Key"])
    return fallback


def _plan_error_text(errors: list[str]) -> str:
    joined = "; ".join(errors)
    lowered = joined.casefold()
    if "не найден" in lowered or "404" in lowered or "not allowed" in lowered or "не разрешен" in lowered:
        return (
            "регистр сведений «ТД_КалендарьСовещаний» не опубликован в OData 1С "
            "(нужно добавить его в состав стандартного интерфейса OData)."
        )
    return joined


def _bound(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


def compute_report_plan_fact_kpi(
    ctx: Any,
    *,
    as_of: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    start = _bound(date_from or getattr(ctx, "date_from", None) or as_of)
    end = _bound(date_to or getattr(ctx, "date_to", None) or as_of)
    if end < start:
        start, end = end, start
    extra = ctx.extra_for() if hasattr(ctx, "extra_for") else {}
    extra = extra if isinstance(extra, dict) else {}
    leader_name = str(extra.get("leader") or LEADER).strip()
    kinds = tuple(extra.get("kinds") or KINDS)
    circle = extra.get("management_circle", True) is not False
    plan_from_fact = extra.get("plan_from_fact", True) is not False
    leader = _leader_key(ctx, leader_name, str(extra.get("leader_key") or LEADER_KEY))

    period = f"ge datetime'{start.isoformat()}T00:00:00'"
    period_end = f"le datetime'{end.isoformat()}T23:59:59'"
    themes = _page(
        ctx,
        THEME_ENTITY,
        "DeletionMark eq false and ТемаКругаУправления eq true" if circle else "DeletionMark eq false",
        "Ref_Key,Description,ВидСовещания,ТемаКругаУправления",
    )
    protocols = _page(
        ctx,
        PROTOCOL_ENTITY,
        f"DeletionMark eq false and Руководитель_Key eq guid'{leader}' and Date {period} and Date {period_end}",
        "Ref_Key,Number,Date,DeletionMark,ВидСовещания,ТемаСовещания_Key,Руководитель_Key",
    )
    errors = getattr(ctx, "source_errors", None)
    mark = len(errors) if isinstance(errors, list) else 0
    plan_rows = _page(
        ctx,
        PLAN_ENTITY,
        f"ДатаСовещания {period} and ДатаСовещания {period_end}",
        "",
    )
    plan_error = ""
    # Сбой плана модуль объясняет сам (или подменяет план фактом), а не обнуляет всю плитку.
    if isinstance(errors, list) and len(errors) > mark:
        plan_error = _plan_error_text(errors[mark:])
        del errors[mark:]
    return score_report_plan_fact(
        plan_rows,
        protocols,
        themes,
        leader_key=leader,
        as_of=as_of,
        date_from=start,
        date_to=end,
        kinds=kinds,
        management_circle=circle,
        plan_error=plan_error,
        plan_from_fact=plan_from_fact,
    )
