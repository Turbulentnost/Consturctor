"""Что считает плитку KPI: код модуля, источник данных и формула."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.position_kpi import PositionKpiMetric, PositionKpiModule, PositionKpiSource
from app.services.position_kpi.daily import PositionKpiNotFound, resolve_profile
from app.services.position_kpi.sources import SOURCES, validate_spec


class PositionKpiMetricNotFound(Exception):
    """У должности нет показателя с таким кодом."""


def _builtin_source(module_name: str) -> str:
    try:
        return inspect.getsource(importlib.import_module(module_name))
    except Exception:  # noqa: BLE001 — модуль мог уехать, карточку всё равно показываем
        return ""


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else ""


def explain_metric(db: Session, position: str, code: str) -> dict[str, Any]:
    profile = resolve_profile(db, position)
    if profile is None:
        raise PositionKpiNotFound(str(position or "").strip())
    metric = db.execute(
        select(PositionKpiMetric).where(
            PositionKpiMetric.profile_id == profile.id,
            PositionKpiMetric.code == code,
        )
    ).scalar_one_or_none()
    if metric is None:
        raise PositionKpiMetricNotFound(code)
    sources = (
        db.execute(select(PositionKpiSource).where(PositionKpiSource.metric_id == metric.id))
        .scalars()
        .all()
    )
    facts = [row for row in sources if row.role == "fact"]
    fact = next(
        (row for row in facts if isinstance(row.extra_json, dict) and row.extra_json.get("module")),
        facts[0] if facts else None,
    )
    extra = dict(fact.extra_json) if fact is not None and isinstance(fact.extra_json, dict) else {}
    module_name = str(extra.get("module") or "").strip()
    stored = db.execute(
        select(PositionKpiModule).where(
            PositionKpiModule.profile_id == profile.id,
            PositionKpiModule.metric_code == code,
        )
    ).scalar_one_or_none()
    if stored is not None:
        module = {
            "name": stored.module_name,
            "origin": "generated",
            "code": stored.source or "",
            "tests": stored.tests or "",
            "content_hash": stored.content_hash or "",
            "updated_at": _iso(stored.updated_at),
        }
    elif module_name:
        module = {
            "name": module_name,
            "origin": "builtin",
            "code": _builtin_source(module_name),
            "tests": "",
            "content_hash": "",
            "updated_at": "",
        }
    else:
        module = None

    spec = {key: value for key, value in extra.items() if key not in {"module", "validation"}}
    registry = SOURCES.get(str(spec.get("source") or "").strip())
    validation = extra.get("validation") if isinstance(extra.get("validation"), dict) else validate_spec(spec)
    data_source = {
        "source": str(spec.get("source") or "").strip(),
        "params": spec.get("params") if isinstance(spec.get("params"), dict) else {},
        "legacy": {key: value for key, value in spec.items() if key not in {"source", "params"}},
        "registry": registry.describe() if registry is not None else None,
        "validation": {
            "ok": not (validation.get("errors") or []),
            "errors": list(validation.get("errors") or []),
            "warnings": list(validation.get("warnings") or []),
        },
    }
    return {
        "position": profile.position_name,
        "profile_id": profile.id,
        "shared_note": (
            f"Модуль общий для всех сотрудников на должности «{profile.position_name}». "
            "Цифры считаются для каждого сотрудника отдельно."
        ),
        "code": metric.code,
        "name": metric.name,
        "weight": int(metric.weight or 0),
        "unit": metric.unit or "%",
        "plan": metric.plan_value,
        "direction": metric.direction,
        "formula_kind": metric.formula_kind,
        "formula_human": metric.formula_human or "",
        "module": module,
        "data_source": data_source,
        "sources": [
            {
                "role": row.role,
                "kind": row.kind,
                "title": row.title,
                "detail": row.detail,
                "update_rule": row.update_rule,
            }
            for row in sources
        ],
    }
