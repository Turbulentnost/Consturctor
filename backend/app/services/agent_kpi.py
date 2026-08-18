from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.schemas.workflow import (
    AgentKpiSchema,
    KpiMeasureSchema,
    KpiMethodSchema,
    KpiScheduleSchema,
    KpiSideSchema,
    KpiTileSchema,
)
from app.services.workflows.prompts import _extract_json_blob


KPI_KINDS = frozenset(
    {
        "expected_interval",
        "runs_count",
        "success_rate",
        "on_schedule_rate",
        "fail_count",
    }
)
NO_RUNS_LABEL = "ещё нет прогонов"
DEFAULT_GREEN_MIN = 90.0
DEFAULT_YELLOW_MIN = 70.0
MIN_INTERVAL_SECONDS = 5 * 60
RETRY_SECONDS = 120
CALC_LOCK_TTL = timedelta(minutes=10)

_UNIT_TO_MINUTES = {
    "minutes": 1.0,
    "minute": 1.0,
    "min": 1.0,
    "мин": 1.0,
    "hours": 60.0,
    "hour": 60.0,
    "час": 60.0,
    "часа": 60.0,
    "часов": 60.0,
    "days": 1440.0,
    "day": 1440.0,
    "день": 1440.0,
    "дня": 1440.0,
    "дней": 1440.0,
}


def parse_kpi_payload(text: str) -> dict[str, Any] | None:
    data = _extract_json_blob(text or "")
    if not data:
        return None
    tiles = data.get("tiles")
    if not isinstance(tiles, list) or not tiles:
        return None
    return data


def parse_calc_payload(text: str) -> list[dict[str, Any]]:
    data = _extract_json_blob(text or "")
    tiles = data.get("tiles") if isinstance(data, dict) else None
    if not isinstance(tiles, list):
        return []
    return [item for item in tiles if isinstance(item, dict) and str(item.get("id") or "").strip()]


def interval_minutes(schedule: dict[str, Any] | None) -> float | None:
    for item in (schedule or {}).get("triggers") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().casefold()
        if kind != "interval":
            continue
        try:
            value = float(item.get("interval_value") or 0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        unit = str(item.get("interval_unit") or "hours").strip().casefold()
        factor = _UNIT_TO_MINUTES.get(unit, 60.0)
        return round(value * factor, 2)
    return None


def default_tiles(*, title: str = "", goal: str = "", schedule: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    minutes = interval_minutes(schedule)
    tiles: list[dict[str, Any]] = []
    if minutes is not None:
        tiles.append(
            {
                "id": "expected_interval",
                "name": "Частота запусков",
                "plan": {
                    "label": "План",
                    "value": minutes,
                    "unit": "мин",
                    "description": "Как часто агент должен запускаться по расписанию.",
                },
                "fact": {
                    "label": "Факт",
                    "value": None,
                    "unit": "мин",
                    "description": "Средний интервал между фактическими прогонами.",
                },
                "measure": {
                    "kind": "expected_interval",
                    "params": {},
                    "formula": "Средний промежуток между started_at соседних прогонов",
                },
            }
        )
        tiles.append(
            {
                "id": "on_schedule_rate",
                "name": "Своевременность запусков",
                "plan": {
                    "label": "План",
                    "value": 100,
                    "unit": "%",
                    "description": "Доля запусков, которые должны укладываться в расписание.",
                },
                "fact": {
                    "label": "Факт",
                    "value": None,
                    "unit": "%",
                    "description": "Доля trigger-прогонов в допустимом окне относительно интервала.",
                },
                "measure": {
                    "kind": "on_schedule_rate",
                    "params": {},
                    "formula": "trigger-прогоны с интервалом в пределах ±20% от плана / все trigger-прогоны",
                },
            }
        )
    tiles.append(
        {
            "id": "runs_count",
            "name": "Число прогонов",
            "plan": {
                "label": "План",
                "value": _expected_runs_per_day(minutes),
                "unit": "шт/день" if minutes else "шт",
                "description": (
                    "Ожидаемое число запусков в сутки по расписанию."
                    if minutes
                    else "Запуски по запросу из чата — планового числа нет."
                ),
            },
            "fact": {
                "label": "Факт",
                "value": None,
                "unit": "шт",
                "description": "Сколько раз агент реально запускался.",
            },
            "measure": {
                "kind": "runs_count",
                "params": {},
                "formula": "Количество записей в истории прогонов",
            },
        }
    )
    tiles.append(
        {
            "id": "success_rate",
            "name": "Успешность",
            "plan": {
                "label": "План",
                "value": 100,
                "unit": "%",
                "description": "Какая доля прогонов должна завершаться без ошибки.",
            },
            "fact": {
                "label": "Факт",
                "value": None,
                "unit": "%",
                "description": "Доля прогонов со статусом ok.",
            },
            "measure": {
                "kind": "success_rate",
                "params": {},
                "formula": "ok / (ok + error) × 100",
            },
        }
    )
    tiles.append(
        {
            "id": "fail_count",
            "name": "Ошибки",
            "plan": {
                "label": "План",
                "value": 0,
                "unit": "шт",
                "description": "Сколько прогонов может завершиться ошибкой.",
            },
            "fact": {
                "label": "Факт",
                "value": None,
                "unit": "шт",
                "description": "Число прогонов со статусом error.",
            },
            "measure": {
                "kind": "fail_count",
                "params": {},
                "formula": "Количество прогонов со статусом error",
            },
        }
    )
    _ = title, goal
    return tiles[:5]


def default_summary(*, title: str, goal: str, schedule: dict[str, Any] | None = None) -> str:
    minutes = interval_minutes(schedule)
    name = (title or "Агент").strip() or "Агент"
    purpose = (goal or "").strip()
    if minutes is not None:
        cadence = _human_interval(minutes)
        body = f"{name} должен запускаться {cadence} и каждый раз доводить задачу до результата."
    else:
        body = f"{name} запускается вручную из чата и должен завершать задачу без ошибки."
    if purpose:
        return f"{body} Цель: {purpose}"
    return body


def normalize_method(
    raw: dict[str, Any] | None,
    *,
    kind: str = "",
    schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    green = _clamp_percent(_as_float(source.get("green_min")), DEFAULT_GREEN_MIN)
    yellow = _clamp_percent(_as_float(source.get("yellow_min")), DEFAULT_YELLOW_MIN)
    if yellow >= green:
        yellow = max(0.0, green - 1.0)
    sched_raw = source.get("schedule") if isinstance(source.get("schedule"), dict) else {}
    sched_kind = str(sched_raw.get("kind") or "").strip().casefold()
    if sched_kind not in {"interval", "at"}:
        sched_kind = "interval"
    interval = _as_int(sched_raw.get("interval_seconds"))
    if interval is None or interval <= 0:
        minutes = interval_minutes(schedule)
        interval = int(round((minutes or 60.0) * 60.0))
    interval = max(MIN_INTERVAL_SECONDS, interval)
    at = str(sched_raw.get("at") or "").strip() if sched_kind == "at" else ""
    return {
        "how": str(source.get("how") or "").strip() or _default_how(kind),
        "when": str(source.get("when") or "").strip() or _default_when(interval, at, sched_kind),
        "plan_update": str(source.get("plan_update") or "").strip() or _default_plan_update(),
        "fact_update": str(source.get("fact_update") or "").strip() or _default_fact_update(),
        "percent_formula": str(source.get("percent_formula") or "").strip() or _default_percent(kind),
        "green_min": green,
        "yellow_min": yellow,
        "schedule": {
            "kind": sched_kind,
            "interval_seconds": interval,
            "at": at,
        },
    }


def tile_color(
    score: float | None,
    green_min: float | None = None,
    yellow_min: float | None = None,
) -> str:
    if score is None:
        return "none"
    green = DEFAULT_GREEN_MIN if green_min is None else float(green_min)
    yellow = DEFAULT_YELLOW_MIN if yellow_min is None else float(yellow_min)
    if score >= green:
        return "green"
    if score >= yellow:
        return "yellow"
    return "red"


def initial_next_run_at(method: dict[str, Any] | None, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    sched = (method or {}).get("schedule") if isinstance((method or {}).get("schedule"), dict) else {}
    if str(sched.get("kind") or "") == "at":
        stamp = _as_datetime(sched.get("at"))
        if stamp is not None:
            return stamp.isoformat()
    return now.isoformat()


def advance_next_run_at(
    method: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    failed: bool = False,
    failures: int = 1,
) -> str:
    now = now or datetime.now(timezone.utc)
    sched = (method or {}).get("schedule") if isinstance((method or {}).get("schedule"), dict) else {}
    kind = str(sched.get("kind") or "interval")
    if failed and failures <= 1:
        return (now + timedelta(seconds=RETRY_SECONDS)).isoformat()
    if kind == "at":
        return ""
    seconds = _as_int(sched.get("interval_seconds")) or 3600
    seconds = max(MIN_INTERVAL_SECONDS, seconds)
    return (now + timedelta(seconds=seconds)).isoformat()


def is_tile_due(tile: dict[str, Any] | None, now: datetime | None = None) -> bool:
    if not isinstance(tile, dict):
        return False
    stamp = _as_datetime(tile.get("next_run_at"))
    if stamp is None:
        return not str(tile.get("updated_at") or "").strip()
    now = now or datetime.now(timezone.utc)
    return stamp <= now


def is_calc_lock_active(calculating_at: Any, now: datetime | None = None) -> bool:
    stamp = _as_datetime(calculating_at)
    if stamp is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - stamp < CALC_LOCK_TTL


def due_tile_ids(kpi: dict[str, Any] | None, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    ids: list[str] = []
    for raw in (kpi or {}).get("tiles") or []:
        if isinstance(raw, dict) and is_tile_due(raw, now):
            tid = str(raw.get("id") or "").strip()
            if tid:
                ids.append(tid)
    return ids


def apply_calc_updates(
    kpi: dict[str, Any],
    updates: list[dict[str, Any]],
    *,
    due_ids: set[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    out = dict(kpi or {})
    tiles = [dict(item) for item in out.get("tiles") or [] if isinstance(item, dict)]
    by_id = {str(item.get("id") or ""): item for item in tiles}
    seen: set[str] = set()
    for raw in updates:
        if not isinstance(raw, dict):
            continue
        tid = str(raw.get("id") or "").strip()
        tile = by_id.get(tid)
        if tile is None:
            continue
        if due_ids is not None and tid not in due_ids:
            continue
        seen.add(tid)
        if isinstance(raw.get("plan"), dict):
            plan = dict(tile.get("plan") or {})
            if "value" in raw["plan"]:
                plan["value"] = _as_float(raw["plan"].get("value"))
            if raw["plan"].get("unit"):
                plan["unit"] = str(raw["plan"]["unit"])
            if raw["plan"].get("description"):
                plan["description"] = str(raw["plan"]["description"])
            tile["plan"] = plan
        if isinstance(raw.get("fact"), dict):
            fact = dict(tile.get("fact") or {})
            fact["value"] = _as_float(raw["fact"].get("value"))
            if raw["fact"].get("unit"):
                fact["unit"] = str(raw["fact"]["unit"])
            if raw["fact"].get("description"):
                fact["description"] = str(raw["fact"]["description"])
            if not str(fact.get("label") or "").strip():
                fact["label"] = "Факт"
            tile["fact"] = fact
        score = _as_float(raw.get("score_percent"))
        if score is not None:
            score = max(0.0, min(100.0, score))
        tile["score_percent"] = score
        method = tile.get("method") if isinstance(tile.get("method"), dict) else {}
        tile["color"] = tile_color(score, method.get("green_min"), method.get("yellow_min"))
        tile["updated_at"] = now.isoformat()
        tile["calc_failures"] = 0
        tile["next_run_at"] = advance_next_run_at(method, now=now, failed=False)
        evidence = str(raw.get("evidence") or "").strip()
        if not evidence:
            evidence = NO_RUNS_LABEL if score is None and (tile.get("fact") or {}).get("value") is None else ""
        tile["evidence"] = evidence
    pending = (due_ids or set()) - seen
    for tid in pending:
        tile = by_id.get(tid)
        if tile is None:
            continue
        failures = int(tile.get("calc_failures") or 0) + 1
        tile["calc_failures"] = failures
        method = tile.get("method") if isinstance(tile.get("method"), dict) else {}
        tile["next_run_at"] = advance_next_run_at(method, now=now, failed=True, failures=failures)
    out["tiles"] = tiles
    return out


def refresh_tile_status(tiles: list[dict[str, Any]]) -> None:
    for tile in tiles:
        method = tile.get("method") if isinstance(tile.get("method"), dict) else {}
        tile["color"] = tile_color(
            _as_float(tile.get("score_percent")),
            method.get("green_min"),
            method.get("yellow_min"),
        )


def runs_digest(runs: list[Any], *, answer_limit: int = 500) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in runs:
        started = getattr(row, "started_at", None)
        finished = getattr(row, "finished_at", None)
        items.append(
            {
                "id": str(getattr(row, "id", "") or ""),
                "status": str(getattr(row, "status", "") or ""),
                "source": str(getattr(row, "source", "") or ""),
                "started_at": started.isoformat() if isinstance(started, datetime) else str(started or ""),
                "finished_at": finished.isoformat() if isinstance(finished, datetime) else str(finished or ""),
                "answer": str(getattr(row, "answer", "") or "")[:answer_limit],
            }
        )
    return items


def build_kpi_record(
    parsed: dict[str, Any] | None,
    *,
    title: str = "",
    goal: str = "",
    schedule: dict[str, Any] | None = None,
    status: str = "draft",
    generated_at: str = "",
    preserve_runtime: bool = False,
) -> dict[str, Any]:
    source = parsed if isinstance(parsed, dict) else {}
    tiles = _normalize_tiles(
        source.get("tiles") if isinstance(source.get("tiles"), list) else None,
        schedule=schedule,
        preserve_runtime=preserve_runtime,
    )
    if not tiles:
        tiles = _normalize_tiles(default_tiles(title=title, goal=goal, schedule=schedule), schedule=schedule)
    else:
        _enrich_plan_from_schedule(tiles, schedule)
    refresh_tile_status(tiles)
    summary = str(source.get("summary") or "").strip() or default_summary(
        title=title, goal=goal, schedule=schedule
    )
    return {
        "status": status if status in {"draft", "ready"} else "draft",
        "generated_at": generated_at or _now_iso(),
        "summary": summary,
        "calculating_at": str(source.get("calculating_at") or "") if preserve_runtime else "",
        "tiles": tiles,
    }


def apply_facts(
    kpi: dict[str, Any],
    runs: list[Any],
    schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(kpi or {})
    tiles: list[dict[str, Any]] = []
    for raw in out.get("tiles") or []:
        if not isinstance(raw, dict):
            continue
        tile = dict(raw)
        fact = dict(tile.get("fact") or {})
        measure = dict(tile.get("measure") or {})
        kind = str(measure.get("kind") or "").strip()
        params = measure.get("params") if isinstance(measure.get("params"), dict) else {}
        value, _hint = compute_fact(kind, params, runs, schedule)
        fact["value"] = value
        if not str(fact.get("label") or "").strip():
            fact["label"] = "Факт"
        tile["fact"] = fact
        tiles.append(tile)
    out["tiles"] = tiles
    return out


def compute_fact(
    kind: str,
    params: dict[str, Any],
    runs: list[Any],
    schedule: dict[str, Any] | None = None,
) -> tuple[float | None, str]:
    finished = [row for row in runs if str(getattr(row, "status", "") or "") in {"ok", "error"}]
    if kind == "runs_count":
        if not runs:
            return None, NO_RUNS_LABEL
        return float(len(runs)), "число прогонов"
    if kind == "fail_count":
        if not finished:
            return None, NO_RUNS_LABEL
        return float(sum(1 for row in finished if str(getattr(row, "status", "")) == "error")), "ошибки"
    if kind == "success_rate":
        if not finished:
            return None, NO_RUNS_LABEL
        ok = sum(1 for row in finished if str(getattr(row, "status", "")) == "ok")
        return round(100.0 * ok / len(finished), 1), "доля успешных"
    if kind == "expected_interval":
        times = _started_times(runs)
        if len(times) < 2:
            return None, NO_RUNS_LABEL
        gaps = [(times[i] - times[i - 1]).total_seconds() / 60.0 for i in range(1, len(times))]
        return round(sum(gaps) / len(gaps), 1), "средний интервал"
    if kind == "on_schedule_rate":
        minutes = interval_minutes(schedule)
        try:
            tolerance = float((params or {}).get("tolerance_minutes") or 0)
        except (TypeError, ValueError):
            tolerance = 0.0
        trigger_times = _started_times(
            [row for row in runs if str(getattr(row, "source", "") or "") == "trigger"]
        )
        if minutes is None or len(trigger_times) < 2:
            return None, NO_RUNS_LABEL
        window = tolerance if tolerance > 0 else max(5.0, minutes * 0.2)
        on_time = 0
        for prev, current in zip(trigger_times, trigger_times[1:]):
            gap = abs((current - prev).total_seconds() / 60.0 - minutes)
            if gap <= window:
                on_time += 1
        total = len(trigger_times) - 1
        return round(100.0 * on_time / total, 1), "своевременность"
    return None, NO_RUNS_LABEL


def list_runs_for_kpi(db: Session, *, user_id: str, workflow_id: str) -> list[AgentRun]:
    return list(
        db.execute(
            select(AgentRun)
            .where(AgentRun.workflow_id == workflow_id, AgentRun.user_id == user_id)
            .order_by(AgentRun.started_at.asc())
            .limit(200)
        )
        .scalars()
        .all()
    )


def kpi_to_schema(
    kpi: dict[str, Any],
    *,
    workflow_id: str = "",
    title: str = "",
) -> AgentKpiSchema:
    tiles: list[KpiTileSchema] = []
    for raw in (kpi or {}).get("tiles") or []:
        if not isinstance(raw, dict):
            continue
        plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else {}
        fact = raw.get("fact") if isinstance(raw.get("fact"), dict) else {}
        measure = raw.get("measure") if isinstance(raw.get("measure"), dict) else {}
        method = raw.get("method") if isinstance(raw.get("method"), dict) else {}
        sched = method.get("schedule") if isinstance(method.get("schedule"), dict) else {}
        tiles.append(
            KpiTileSchema(
                id=str(raw.get("id") or ""),
                name=str(raw.get("name") or ""),
                plan=_side_schema(plan),
                fact=_side_schema(fact),
                measure=KpiMeasureSchema(
                    kind=str(measure.get("kind") or ""),
                    params=dict(measure.get("params") or {})
                    if isinstance(measure.get("params"), dict)
                    else {},
                    formula=str(measure.get("formula") or ""),
                ),
                score_percent=_as_float(raw.get("score_percent")),
                color=str(raw.get("color") or "none"),
                updated_at=str(raw.get("updated_at") or ""),
                next_run_at=str(raw.get("next_run_at") or ""),
                evidence=str(raw.get("evidence") or ""),
                method=KpiMethodSchema(
                    how=str(method.get("how") or ""),
                    when=str(method.get("when") or ""),
                    plan_update=str(method.get("plan_update") or ""),
                    fact_update=str(method.get("fact_update") or ""),
                    percent_formula=str(method.get("percent_formula") or ""),
                    green_min=float(method.get("green_min") or DEFAULT_GREEN_MIN),
                    yellow_min=float(method.get("yellow_min") or DEFAULT_YELLOW_MIN),
                    schedule=KpiScheduleSchema(
                        kind=str(sched.get("kind") or "interval"),
                        interval_seconds=int(sched.get("interval_seconds") or 3600),
                        at=str(sched.get("at") or ""),
                    ),
                ),
            )
        )
    return AgentKpiSchema(
        status=str((kpi or {}).get("status") or "draft"),
        generated_at=str((kpi or {}).get("generated_at") or ""),
        summary=str((kpi or {}).get("summary") or ""),
        tiles=tiles,
        workflow_id=workflow_id,
        title=title,
    )


def _side_schema(data: dict[str, Any]) -> KpiSideSchema:
    return KpiSideSchema(
        label=str(data.get("label") or ""),
        value=_as_float(data.get("value")),
        unit=str(data.get("unit") or ""),
        description=str(data.get("description") or ""),
    )


def _normalize_tiles(
    raw_tiles: list[Any] | None,
    *,
    schedule: dict[str, Any] | None = None,
    preserve_runtime: bool = False,
) -> list[dict[str, Any]]:
    tiles: list[dict[str, Any]] = []
    seen_kinds: set[str] = set()
    for index, raw in enumerate(raw_tiles or []):
        if not isinstance(raw, dict):
            continue
        measure = raw.get("measure") if isinstance(raw.get("measure"), dict) else {}
        kind = str(measure.get("kind") or "").strip()
        if kind not in KPI_KINDS or kind in seen_kinds:
            continue
        seen_kinds.add(kind)
        plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else {}
        fact = raw.get("fact") if isinstance(raw.get("fact"), dict) else {}
        method = normalize_method(
            raw.get("method") if isinstance(raw.get("method"), dict) else None,
            kind=kind,
            schedule=schedule,
        )
        tile_id = str(raw.get("id") or kind or f"kpi_{index + 1}").strip() or kind
        score = _as_float(raw.get("score_percent")) if preserve_runtime else None
        next_run = str(raw.get("next_run_at") or "") if preserve_runtime else ""
        if not next_run:
            if preserve_runtime and str(method["schedule"]["kind"]) == "at" and str(raw.get("updated_at") or ""):
                next_run = ""
            else:
                next_run = initial_next_run_at(method)
        tiles.append(
            {
                "id": tile_id,
                "name": str(raw.get("name") or _default_name(kind)),
                "plan": {
                    "label": str(plan.get("label") or "План"),
                    "value": _as_float(plan.get("value")),
                    "unit": str(plan.get("unit") or _default_unit(kind)),
                    "description": str(plan.get("description") or ""),
                },
                "fact": {
                    "label": str(fact.get("label") or "Факт"),
                    "value": _as_float(fact.get("value")) if preserve_runtime else None,
                    "unit": str(fact.get("unit") or _default_unit(kind)),
                    "description": str(fact.get("description") or ""),
                },
                "measure": {
                    "kind": kind,
                    "params": dict(measure.get("params") or {})
                    if isinstance(measure.get("params"), dict)
                    else {},
                    "formula": str(measure.get("formula") or ""),
                },
                "score_percent": score,
                "color": tile_color(score, method["green_min"], method["yellow_min"]),
                "updated_at": str(raw.get("updated_at") or "") if preserve_runtime else "",
                "next_run_at": next_run,
                "evidence": str(raw.get("evidence") or "") if preserve_runtime else "",
                "calc_failures": int(raw.get("calc_failures") or 0) if preserve_runtime else 0,
                "method": method,
            }
        )
        if len(tiles) >= 5:
            break
    return tiles


def _enrich_plan_from_schedule(tiles: list[dict[str, Any]], schedule: dict[str, Any] | None) -> None:
    minutes = interval_minutes(schedule)
    for tile in tiles:
        measure = tile.get("measure") if isinstance(tile.get("measure"), dict) else {}
        plan = tile.get("plan") if isinstance(tile.get("plan"), dict) else {}
        kind = str(measure.get("kind") or "")
        if kind == "expected_interval" and plan.get("value") is None and minutes is not None:
            plan["value"] = minutes
            plan["unit"] = plan.get("unit") or "мин"
        elif kind == "success_rate" and plan.get("value") is None:
            plan["value"] = 100
            plan["unit"] = plan.get("unit") or "%"
        elif kind == "on_schedule_rate" and plan.get("value") is None:
            plan["value"] = 100
            plan["unit"] = plan.get("unit") or "%"
        elif kind == "fail_count" and plan.get("value") is None:
            plan["value"] = 0
            plan["unit"] = plan.get("unit") or "шт"
        elif kind == "runs_count" and plan.get("value") is None:
            plan["value"] = _expected_runs_per_day(minutes)
            if minutes is not None and not plan.get("unit"):
                plan["unit"] = "шт/день"
        tile["plan"] = plan


def _expected_runs_per_day(minutes: float | None) -> float | None:
    if minutes is None or minutes <= 0:
        return None
    return round(1440.0 / minutes, 1)


def _human_interval(minutes: float) -> str:
    if minutes < 60:
        value = int(minutes) if minutes == int(minutes) else minutes
        return f"каждые {value} мин"
    if minutes < 1440:
        hours = minutes / 60.0
        value = int(hours) if hours == int(hours) else round(hours, 1)
        return f"каждые {value} ч"
    days = minutes / 1440.0
    value = int(days) if days == int(days) else round(days, 1)
    return f"каждые {value} дн"


def _human_seconds(seconds: int) -> str:
    return _human_interval(max(1.0, seconds / 60.0))


def _default_name(kind: str) -> str:
    return {
        "expected_interval": "Частота запусков",
        "runs_count": "Число прогонов",
        "success_rate": "Успешность",
        "on_schedule_rate": "Своевременность запусков",
        "fail_count": "Ошибки",
    }.get(kind, kind)


def _default_unit(kind: str) -> str:
    return {
        "expected_interval": "мин",
        "runs_count": "шт",
        "success_rate": "%",
        "on_schedule_rate": "%",
        "fail_count": "шт",
    }.get(kind, "")


def _default_how(kind: str) -> str:
    return {
        "expected_interval": "Средний промежуток между started_at соседних прогонов в минутах.",
        "on_schedule_rate": "Доля trigger-прогонов, чей интервал укладывается в ±20% от плана.",
        "runs_count": "Число записей в истории прогонов агента.",
        "success_rate": "Доля прогонов со статусом ok среди завершённых (ok + error).",
        "fail_count": "Число прогонов со статусом error.",
    }.get(kind, "По истории прогонов агента и методике плитки.")


def _default_percent(kind: str) -> str:
    return {
        "expected_interval": "100 − |факт − план| / план × 100, не ниже 0.",
        "on_schedule_rate": "Факт уже в процентах — это и есть KPI.",
        "runs_count": "min(100, факт / план × 100), если план задан.",
        "success_rate": "Факт уже в процентах — это и есть KPI.",
        "fail_count": "100, если факт ≤ плана, иначе снижать процент за каждую лишнюю ошибку.",
    }.get(kind, "факт / план × 100, ограничить 0–100.")


def _default_when(interval_seconds: int, at: str, kind: str) -> str:
    if kind == "at" and at:
        return f"Однократно в {at}."
    return f"Фоновый расчёт {_human_seconds(interval_seconds)}, первый — сразу после формирования KPI."


def _default_plan_update() -> str:
    return "При изменении расписания или цели агента и когда методика велит пересмотреть норму."


def _default_fact_update() -> str:
    return "При каждом фоновом расчёте по расписанию методики."


def _clamp_percent(value: float | None, fallback: float) -> float:
    if value is None:
        return fallback
    return max(0.0, min(100.0, value))


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _started_times(runs: list[Any]) -> list[datetime]:
    times: list[datetime] = []
    for row in runs:
        stamp = _as_datetime(getattr(row, "started_at", None))
        if stamp is not None:
            times.append(stamp)
    times.sort()
    return times


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
