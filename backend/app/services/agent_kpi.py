from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.schemas.workflow import AgentKpiSchema, KpiMeasureSchema, KpiSideSchema, KpiTileSchema
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


def build_kpi_record(
    parsed: dict[str, Any] | None,
    *,
    title: str = "",
    goal: str = "",
    schedule: dict[str, Any] | None = None,
    status: str = "draft",
    generated_at: str = "",
) -> dict[str, Any]:
    source = parsed if isinstance(parsed, dict) else {}
    tiles = _normalize_tiles(source.get("tiles") if isinstance(source.get("tiles"), list) else None)
    if not tiles:
        tiles = default_tiles(title=title, goal=goal, schedule=schedule)
    else:
        _enrich_plan_from_schedule(tiles, schedule)
    summary = str(source.get("summary") or "").strip() or default_summary(
        title=title, goal=goal, schedule=schedule
    )
    return {
        "status": status if status in {"draft", "ready"} else "draft",
        "generated_at": generated_at or _now_iso(),
        "summary": summary,
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
            if not runs:
                return None, NO_RUNS_LABEL
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
    value = data.get("value")
    parsed: float | None
    if value is None or value == "":
        parsed = None
    else:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = None
    return KpiSideSchema(
        label=str(data.get("label") or ""),
        value=parsed,
        unit=str(data.get("unit") or ""),
        description=str(data.get("description") or ""),
    )


def _normalize_tiles(raw_tiles: list[Any] | None) -> list[dict[str, Any]]:
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
        tile_id = str(raw.get("id") or kind or f"kpi_{index + 1}").strip() or kind
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
                    "value": None,
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


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
