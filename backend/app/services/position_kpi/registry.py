"""Белый список калькуляторов KPI должности."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.position_kpi import PositionKpiMetric
    from app.services.position_kpi.daily import SourceBundle

Scorer = Callable[["PositionKpiMetric", "SourceBundle"], tuple[dict[str, Any], str]]


def score_packages(_metric: PositionKpiMetric, ctx: SourceBundle) -> tuple[dict[str, Any], str]:
    from kpi.sources.sd_rk_packages import format_report, score_package_kpi

    report = score_package_kpi(
        ctx.events,
        ctx.protocols,
        as_of=ctx.as_of,
        date_from=ctx.date_from,
        date_to=ctx.date_to,
    )
    return report, format_report(report).rsplit("\n", 1)[-1]


def score_protocols(_metric: PositionKpiMetric, ctx: SourceBundle) -> tuple[dict[str, Any], str]:
    from kpi.sources.sd_rk_protocols import format_report, score_protocol_kpi

    report = score_protocol_kpi(
        ctx.events,
        ctx.protocols,
        as_of=ctx.as_of,
        date_from=ctx.date_from,
        date_to=ctx.date_to,
    )
    return report, format_report(report).rsplit("\n", 1)[-1]


def score_instructions(_metric: PositionKpiMetric, ctx: SourceBundle) -> tuple[dict[str, Any], str]:
    from kpi.instruction_tracker import compute_report

    report = compute_report(
        as_of=ctx.as_of,
        date_from=ctx.date_from,
        date_to=ctx.date_to,
        cards=ctx.cards,
        protocols=ctx.protocols,
    )
    return report, ""


def score_assistant_meetings(
    _metric: PositionKpiMetric, ctx: SourceBundle
) -> tuple[dict[str, Any], str]:
    from kpi.sources.assistant_meetings import compute_meetings_schedule_kpi, format_plan_fact_report

    report = compute_meetings_schedule_kpi(
        ctx,
        as_of=ctx.as_of,
        date_from=ctx.date_from,
        date_to=ctx.date_to,
    )
    text = format_plan_fact_report(report).rsplit("\n", 1)[-1]
    return report, text


def score_assistant_dpi(
    _metric: PositionKpiMetric, ctx: SourceBundle
) -> tuple[dict[str, Any], str]:
    from kpi.sources.assistant_dpi import compute_dpi_appointment_kpi, format_report

    report = compute_dpi_appointment_kpi(
        ctx,
        as_of=ctx.as_of,
        date_from=ctx.date_from,
        date_to=ctx.date_to,
    )
    text = format_report(report).rsplit("\n", 1)[-1]
    return report, text


def score_assistant_orders(
    _metric: PositionKpiMetric, ctx: SourceBundle
) -> tuple[dict[str, Any], str]:
    from kpi.sources.assistant_orders import compute_orders_registration_kpi, format_report

    report = compute_orders_registration_kpi(
        ctx,
        as_of=ctx.as_of,
        date_from=ctx.date_from,
        date_to=ctx.date_to,
    )
    text = format_report(report).rsplit("\n", 1)[-1]
    return report, text


def score_assistant_unplanned(
    _metric: PositionKpiMetric, ctx: SourceBundle
) -> tuple[dict[str, Any], str]:
    from kpi.sources.assistant_unplanned import compute_unplanned_meetings_kpi, format_report

    report = compute_unplanned_meetings_kpi(
        ctx,
        as_of=ctx.as_of,
        date_from=ctx.date_from,
        date_to=ctx.date_to,
    )
    text = format_report(report).rsplit("\n", 1)[-1]
    return report, text


def score_assistant_tasks(
    _metric: PositionKpiMetric, ctx: SourceBundle
) -> tuple[dict[str, Any], str]:
    from kpi.sources.assistant_tasks import compute_individual_tasks_kpi, format_report

    report = compute_individual_tasks_kpi(
        ctx,
        as_of=ctx.as_of,
        date_from=ctx.date_from,
        date_to=ctx.date_to,
    )
    text = format_report(report).rsplit("\n", 1)[-1]
    return report, text


def score_quality(_metric: PositionKpiMetric, ctx: SourceBundle) -> tuple[dict[str, Any], str]:
    from kpi.sources.sd_rk_quality import score_quality_kpi

    report = score_quality_kpi(ctx.protocols)
    total = report.get("v_total") or 0
    errors = report.get("v_errors") or 0
    fact = report.get("fact_pct")
    fact_text = "нет данных" if fact is None else f"{fact}%"
    evidence = (
        f"Vоши = {errors}/{total}, факт {fact_text}. "
        "Протоколы Ильченко считаем без возвратов."
    )
    return report, evidence


SCORERS: dict[str, Scorer] = {
    "kpi.sources.sd_rk_packages": score_packages,
    "kpi.sources.sd_rk_protocols": score_protocols,
    "kpi.sources.sd_rk_instructions": score_instructions,
    "kpi.sources.sd_rk_quality": score_quality,
    "kpi.sources.assistant_meetings": score_assistant_meetings,
    "kpi.sources.assistant_dpi": score_assistant_dpi,
    "kpi.sources.assistant_orders": score_assistant_orders,
    "kpi.sources.assistant_unplanned": score_assistant_unplanned,
    "kpi.sources.assistant_tasks": score_assistant_tasks,
}

_ALLOWED_PREFIXES = ("kpi.sources.", "kpi.generated.")


def _find_score_fn(mod: Any):
    fn = getattr(mod, "score_kpi", None)
    if callable(fn):
        return fn
    for name in dir(mod):
        if name.startswith("score_") and name.endswith("_kpi"):
            candidate = getattr(mod, name)
            if callable(candidate):
                return candidate
    return None


def _find_named(mod: Any, prefix: str, suffix: str, exact: str):
    fn = getattr(mod, exact, None)
    if callable(fn):
        return fn
    for name in dir(mod):
        if name.startswith(prefix) and name.endswith(suffix):
            candidate = getattr(mod, name)
            if callable(candidate):
                return candidate
    return None


def _find_load_fn(mod: Any):
    return _find_named(mod, "load_", "_rows", "load_rows")


def _find_compute_fn(mod: Any):
    return _find_named(mod, "compute_", "_kpi", "compute_kpi")


def _merged_extra(mod: Any, ctx: "SourceBundle", metric: "PositionKpiMetric") -> dict[str, Any]:
    extra: dict[str, Any] = {}
    declared = getattr(mod, "SOURCE", None)
    if isinstance(declared, dict):
        extra.update(declared)
    if hasattr(ctx, "extra_for"):
        more = ctx.extra_for(metric) or {}
        if isinstance(more, dict):
            extra.update(more)
    elif isinstance(getattr(metric, "extra_json", None), dict):
        extra.update(metric.extra_json)
    return extra


def _empty_report() -> dict[str, Any]:
    return {"fact_pct": None, "score_pct": None, "contrib_pct": None, "rows": []}


def _as_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def run_generated_pair(mod: Any, ctx: "SourceBundle", metric: "PositionKpiMetric") -> dict[str, Any]:
    """Извлекатель отдаёт rows, калькулятор — готовый KPI. В обход связки не считаем."""
    extra = _merged_extra(mod, ctx, metric)
    if hasattr(ctx, "_metric_extra"):
        ctx._metric_extra = extra
    compute = _find_compute_fn(mod)
    if compute is not None:
        report = compute(ctx, as_of=ctx.as_of, date_from=ctx.date_from, date_to=ctx.date_to)
        if isinstance(report, dict):
            return report
        raise TypeError(f"{getattr(mod, '__name__', 'module')} compute returned {type(report)}")
    score_fn = _find_score_fn(mod)
    if score_fn is None:
        raise RuntimeError(f"{getattr(mod, '__name__', 'module')} has no score_*_kpi")
    load_fn = _find_load_fn(mod)
    if load_fn is not None:
        rows = _as_rows(load_fn(ctx))
    elif hasattr(ctx, "load_for"):
        rows = _as_rows(ctx.load_for(extra))
    else:
        rows = []
    report = score_fn(rows, as_of=ctx.as_of, date_from=ctx.date_from, date_to=ctx.date_to)
    if isinstance(report, dict):
        return report
    raise TypeError(f"{getattr(mod, '__name__', 'module')} score returned {type(report)}")


def _dynamic_scorer(module_name: str) -> Scorer:
    def score(metric: "PositionKpiMetric", ctx: "SourceBundle") -> tuple[dict[str, Any], str]:
        import importlib

        mod = importlib.import_module(module_name)
        report = run_generated_pair(mod, ctx, metric)
        if not isinstance(report, dict):
            report = _empty_report()
        formatter = getattr(mod, "format_report", None)
        evidence = ""
        if callable(formatter):
            try:
                evidence = str(formatter(report) or "").strip().rsplit("\n", 1)[-1]
            except Exception:  # noqa: BLE001
                evidence = ""
        if not evidence:
            fact = report.get("fact_pct")
            evidence = "нет данных" if fact is None else f"факт {fact}%"
        return report, evidence

    return score


def scorer_for(module: str | None) -> Scorer | None:
    if not module:
        return None
    name = str(module).strip()
    if name in SCORERS:
        return SCORERS[name]
    if not name.startswith(_ALLOWED_PREFIXES):
        return None
    try:
        return _dynamic_scorer(name)
    except Exception:  # noqa: BLE001
        return None
