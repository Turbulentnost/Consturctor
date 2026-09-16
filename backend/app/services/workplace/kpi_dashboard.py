from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.models.workflow import Workflow
from app.services.workplace.kpi_daily import dynamics_from_daily_metrics
from app.schemas.workplace_kpi import (
    WorkplaceKpiAgentRowOut,
    WorkplaceKpiCardOut,
    WorkplaceKpiChartSeriesOut,
    WorkplaceKpiCompareRowOut,
    WorkplaceKpiDashboardOut,
    WorkplaceKpiDynamicsOut,
    WorkplaceKpiEmployeeMetricOut,
    WorkplaceKpiProblemZoneOut,
)

DEFAULT_PERIOD_FROM = "2024-08-12"
DEFAULT_PERIOD_TO = "2024-08-18"

_SUCCESS = frozenset({"ok", "success", "successful", "completed", "done", "ready"})
_FAIL = frozenset({"error", "fail", "failed"})


def _parse_day(value: str | None, fallback: str) -> date:
    raw = (value or "").strip() or fallback
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return date.fromisoformat(fallback)


def _period_bounds(day_from: date, day_to: date) -> tuple[datetime, datetime]:
    start = datetime.combine(min(day_from, day_to), time.min, tzinfo=timezone.utc)
    end = datetime.combine(max(day_from, day_to), time.max, tzinfo=timezone.utc)
    return start, end


def _period_label(day_from: date, day_to: date) -> str:
    months = (
        "янв.",
        "февр.",
        "марта",
        "апр.",
        "мая",
        "июня",
        "июля",
        "авг.",
        "сент.",
        "окт.",
        "ноб.",
        "дек.",
    )
    lo, hi = (day_from, day_to) if day_from <= day_to else (day_to, day_from)
    if lo == hi:
        return f"{lo.day} {months[lo.month - 1]} {lo.year}"
    if lo.year == hi.year and lo.month == hi.month:
        return f"{lo.day}–{hi.day} {months[lo.month - 1]} {lo.year}"
    return f"{lo.day} {months[lo.month - 1]} – {hi.day} {months[hi.month - 1]} {hi.year}"


def _status_for(completion: int) -> tuple[str, str]:
    if completion >= 90:
        return "В норме", "green"
    if completion >= 75:
        return "Внимание", "orange"
    return "Риск", "red"


def _iter_days(day_from: date, day_to: date) -> list[date]:
    lo, hi = (day_from, day_to) if day_from <= day_to else (day_to, day_from)
    out: list[date] = []
    cursor = lo
    while cursor <= hi:
        out.append(cursor)
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return out


def _reference_employee_kpi() -> list[WorkplaceKpiEmployeeMetricOut]:
    return [
        WorkplaceKpiEmployeeMetricOut(
            id="tasks",
            title="Выполнение задач",
            display_value="78%",
            trend_delta="+12%",
            trend_up=True,
            trend_positive=True,
            footer_text="142 из 182 задач",
            sparkline_points=[62, 64, 68, 70, 72, 75, 78],
            sparkline_color="#1565c0",
            source="reference",
        ),
        WorkplaceKpiEmployeeMetricOut(
            id="sla",
            title="Соблюдение сроков",
            display_value="92%",
            trend_delta="+6%",
            trend_up=True,
            trend_positive=True,
            footer_text="168 из 182 задач",
            sparkline_points=[84, 85, 87, 88, 90, 91, 92],
            sparkline_color="#08745f",
            source="reference",
        ),
        WorkplaceKpiEmployeeMetricOut(
            id="quality",
            title="Качество результатов",
            display_value="4.7",
            trend_delta="+0.3",
            trend_up=True,
            trend_positive=True,
            footer_text="из 5.0 (по оценкам)",
            sparkline_points=[4.2, 4.3, 4.4, 4.5, 4.5, 4.6, 4.7],
            sparkline_color="#7b1fa2",
            source="reference",
        ),
        WorkplaceKpiEmployeeMetricOut(
            id="load",
            title="Загрузка",
            display_value="76%",
            trend_delta="+4%",
            trend_up=True,
            trend_positive=False,
            footer_text="30 из 40 часов в неделю",
            sparkline_points=[68, 69, 71, 72, 74, 75, 76],
            sparkline_color="#e8943a",
            source="reference",
        ),
    ]


def _reference_problem_zones() -> list[WorkplaceKpiProblemZoneOut]:
    return [
        WorkplaceKpiProblemZoneOut(
            id="pz1",
            type_id="low_sla",
            type_label="Низкое SLA",
            description="Просрочки в задаче по подготовке отчета",
            process="Отчетность",
            indicator="Соблюдение SLA",
            current_value="76%",
            target_value="≥ 90%",
            deviation="-14%",
            zone="Отчетность",
            metric="Соблюдение SLA",
            value="76%",
            severity="red",
            status="Требует внимания",
            status_tone="orange",
            recommendation="Перераспределить задачи, подключить ИИ-агента",
            source="reference",
        ),
        WorkplaceKpiProblemZoneOut(
            id="pz2",
            type_id="low_automation",
            type_label="Низкая автоматизация",
            description="Высокая доля ручных операций",
            process="Обработка писем",
            indicator="Доля автоматизации",
            current_value="32%",
            target_value="≥ 60%",
            deviation="-28%",
            zone="Обработка писем",
            metric="Доля автоматизации",
            value="32%",
            severity="red",
            status="Требует внимания",
            status_tone="orange",
            recommendation="Настроить правила, добавить сценарии",
            source="reference",
        ),
        WorkplaceKpiProblemZoneOut(
            id="pz3",
            type_id="quality_drop",
            type_label="Падение качества",
            description="Ошибки в данных по проекту",
            process="Подготовка КП",
            indicator="Качество результатов",
            current_value="4.1",
            target_value="≥ 4.5",
            deviation="-0.4",
            zone="Подготовка КП",
            metric="Качество результатов",
            value="4.1",
            severity="orange",
            status="В работе",
            status_tone="blue",
            recommendation="Проверить данные, добавить контроль ИИ",
            source="reference",
        ),
    ]


def _quality_from_completion_pct(pct: int) -> float:
    return round(1 + 4 * (max(0, min(100, pct)) / 100), 1)


def _run_success_pct_by_day(runs: list[AgentRun], days: list[date]) -> list[float]:
    if not days:
        return []
    buckets: list[list[AgentRun]] = [[] for _ in days]
    day_index = {d: i for i, d in enumerate(days)}
    for run in runs:
        started = run.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        day = started.date()
        idx = day_index.get(day)
        if idx is not None:
            buckets[idx].append(run)
    points: list[float] = []
    for bucket in buckets:
        if not bucket:
            points.append(points[-1] if points else 0.0)
            continue
        finished = [r for r in bucket if _is_success(r.status) or (r.status or "").lower() in _FAIL]
        ok = sum(1 for r in finished if _is_success(r.status))
        total = len(finished) or len(bucket)
        points.append(float(round(100 * ok / total)) if total else 0.0)
    return points


def _build_problem_zones_from_agents(
    agents: list[WorkplaceKpiAgentRowOut],
    *,
    waiting_human_wf_ids: frozenset[str],
    quality_score: float,
) -> list[WorkplaceKpiProblemZoneOut]:
    zones: list[WorkplaceKpiProblemZoneOut] = []
    seq = 0
    for agent in agents:
        if agent.sla_pct < 90:
            seq += 1
            dev = agent.sla_pct - 90
            wf_wait = agent.id in waiting_human_wf_ids
            zones.append(
                WorkplaceKpiProblemZoneOut(
                    id=f"sla-{agent.id}-{seq}",
                    type_id="low_sla",
                    type_label="Низкое SLA",
                    description=f"Отклонение SLA по агенту {agent.name}",
                    process=agent.process,
                    indicator="Соблюдение SLA",
                    current_value=f"{agent.sla_pct}%",
                    target_value="≥ 90%",
                    deviation=f"{dev:+d}%",
                    zone=agent.process,
                    metric="Соблюдение SLA",
                    value=f"{agent.sla_pct}%",
                    severity="red" if agent.sla_pct < 80 else "orange",
                    status="В работе" if wf_wait else "Требует внимания",
                    status_tone="blue" if wf_wait else "orange",
                    recommendation="Перераспределить задачи, подключить ИИ-агента",
                    source=agent.source,
                )
            )
        if agent.automation_pct < 60:
            seq += 1
            dev = agent.automation_pct - 60
            wf_wait = agent.id in waiting_human_wf_ids
            zones.append(
                WorkplaceKpiProblemZoneOut(
                    id=f"auto-{agent.id}-{seq}",
                    type_id="low_automation",
                    type_label="Низкая автоматизация",
                    description=f"Низкая автоматизация: {agent.name}",
                    process=agent.process,
                    indicator="Доля автоматизации",
                    current_value=f"{agent.automation_pct}%",
                    target_value="≥ 60%",
                    deviation=f"{dev:+d}%",
                    zone=agent.process,
                    metric="Доля автоматизации",
                    value=f"{agent.automation_pct}%",
                    severity="red" if agent.automation_pct < 45 else "orange",
                    status="В работе" if wf_wait else "Требует внимания",
                    status_tone="blue" if wf_wait else "orange",
                    recommendation="Настроить правила, добавить сценарии",
                    source=agent.source,
                )
            )
    if quality_score < 4.5:
        seq += 1
        dev = round(quality_score - 4.5, 1)
        zones.append(
            WorkplaceKpiProblemZoneOut(
                id=f"quality-{seq}",
                type_id="quality_drop",
                type_label="Падение качества",
                description="Снижение нормализованной оценки по задачам",
                process="Сводно",
                indicator="Качество результатов",
                current_value=str(quality_score),
                target_value="≥ 4.5",
                deviation=f"{dev:+.1f}",
                zone="Сводно",
                metric="Качество результатов",
                value=str(quality_score),
                severity="orange",
                status="Требует внимания",
                status_tone="orange",
                recommendation="Проверить данные, добавить контроль ИИ",
                source="computed",
            )
        )
    return zones[:12]


def _employee_kpi_from_runs(
    runs: list[AgentRun],
    day_from: date,
    day_to: date,
    ref: list[WorkplaceKpiEmployeeMetricOut],
) -> list[WorkplaceKpiEmployeeMetricOut]:
    days = _iter_days(day_from, day_to)
    spark_tasks = _run_success_pct_by_day(runs, days)
    if not runs:
        return ref
    finished = [run for run in runs if _is_success(run.status) or (run.status or "").lower() in _FAIL]
    ok = sum(1 for run in finished if _is_success(run.status))
    total = len(finished) or len(runs)
    task_pct = round(100 * ok / total) if total else 0
    quality = _quality_from_completion_pct(task_pct)
    load_pct = min(100, max(10, round(len(runs) * 4)))
    load_hours = round(load_pct * 40 / 100)

    by_id = {m.id: m for m in ref}
    tasks_ref = by_id.get("tasks", ref[0])
    sla_ref = by_id.get("sla", ref[1])
    quality_ref = by_id.get("quality", ref[2])
    load_ref = by_id.get("load", ref[3])

    return [
        tasks_ref.model_copy(
            update={
                "display_value": f"{task_pct}%",
                "footer_text": f"{ok} из {total} запусков",
                "sparkline_points": spark_tasks or tasks_ref.sparkline_points,
                "source": "computed",
            }
        ),
        sla_ref.model_copy(
            update={
                "display_value": f"{task_pct}%",
                "footer_text": f"{ok} из {total} в срок (прокси)",
                "sparkline_points": spark_tasks or sla_ref.sparkline_points,
                "source": "computed",
            }
        ),
        quality_ref.model_copy(
            update={
                "display_value": str(quality),
                "sparkline_points": [_quality_from_completion_pct(int(p)) for p in (spark_tasks or quality_ref.sparkline_points)],
                "source": "computed",
            }
        ),
        load_ref.model_copy(
            update={
                "display_value": f"{load_pct}%",
                "footer_text": f"{load_hours} из 40 часов в неделю",
                "sparkline_points": spark_tasks or load_ref.sparkline_points,
                "source": "computed",
            }
        ),
    ]


def _reference_agents() -> list[WorkplaceKpiAgentRowOut]:
    rows = [
        ("rig-01", "RIG-01", "Контроль регламентов", "Регламентные работы", 91, 96, 82, 68),
        ("rep-03", "REP-03", "Отчётность KPI", "Еженедельный отчёт", 85, 94, 74, 58),
        ("ml-06", "ML-06", "Обработка почты", "Входящие письма", 79, 88, 71, 55),
        ("reg-02", "REG-02", "Согласование договоров", "Закупки", 72, 90, 65, 48),
    ]
    out: list[WorkplaceKpiAgentRowOut] = []
    for rid, code, name, process, completion, sla, load, auto in rows:
        status, tone = _status_for(completion)
        out.append(
            WorkplaceKpiAgentRowOut(
                id=rid,
                code=code,
                name=name,
                process=process,
                completion_pct=completion,
                sla_pct=sla,
                load_pct=load,
                automation_pct=auto,
                status=status,
                status_tone=tone,
                source="reference",
            )
        )
    return out


def _reference_dashboard(day_from: date, day_to: date) -> WorkplaceKpiDashboardOut:
    label = _period_label(day_from, day_to)
    x_labels = []
    cursor = day_from if day_from <= day_to else day_to
    end = day_to if day_from <= day_to else day_from
    while cursor <= end:
        x_labels.append(f"{cursor.day:02d}.{cursor.month:02d}")
        cursor = date.fromordinal(cursor.toordinal() + 1)

    return WorkplaceKpiDashboardOut(
        period_from=day_from.isoformat(),
        period_to=day_to.isoformat(),
        period_label=label,
        cards=[
            WorkplaceKpiCardOut(
                id="tasks",
                label="Выполнение задач",
                display_value="78%",
                trend="(+12%)",
                progress=78,
                tone="orange",
                source="reference",
            ),
            WorkplaceKpiCardOut(
                id="sla",
                label="SLA",
                display_value="92%",
                progress=92,
                tone="blue",
                source="reference",
            ),
            WorkplaceKpiCardOut(
                id="load",
                label="Загрузка",
                display_value="76%",
                progress=76,
                tone="purple",
                source="reference",
            ),
            WorkplaceKpiCardOut(
                id="ai",
                label="Эффективность ИИ",
                display_value="94%",
                progress=94,
                tone="green",
                source="reference",
            ),
            WorkplaceKpiCardOut(
                id="auto",
                label="Доля автоматизации",
                display_value="62%",
                progress=62,
                tone="yellow",
                source="reference",
            ),
            WorkplaceKpiCardOut(
                id="quality",
                label="Качество",
                display_value="4.7",
                trend="из 5",
                ring=False,
                tone="lilac",
                source="reference",
            ),
        ],
        agents=_reference_agents(),
        employee_kpi=_reference_employee_kpi(),
        problem_zones=_reference_problem_zones(),
        workload_compare=[
            WorkplaceKpiCompareRowOut(id="c1", label="Регламенты", employee=12, ai=28, source="reference"),
            WorkplaceKpiCompareRowOut(id="c2", label="Отчётность", employee=18, ai=22, source="reference"),
            WorkplaceKpiCompareRowOut(id="c3", label="Почта", employee=24, ai=16, source="reference"),
            WorkplaceKpiCompareRowOut(id="c4", label="Задачи 1С", employee=32, ai=14, source="reference"),
        ],
        dynamics=WorkplaceKpiDynamicsOut(
            title="Динамика показателей",
            x_labels=x_labels or ["12.08", "13.08", "14.08", "15.08", "16.08", "17.08", "18.08"],
            y_max=100,
            series=[
                WorkplaceKpiChartSeriesOut(
                    id="tasks",
                    label="Выполнение задач",
                    color="#e8943a",
                    points=[66, 68, 70, 72, 74, 76, 78],
                ),
                WorkplaceKpiChartSeriesOut(
                    id="ai",
                    label="Эффективность ИИ",
                    color="#08745f",
                    points=[88, 89, 90, 91, 92, 93, 94],
                ),
            ],
            source="reference",
        ),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _is_success(status: str) -> bool:
    value = (status or "").lower()
    return any(token in value for token in _SUCCESS)


def _workflow_code(workflow: Workflow, index: int) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    raw = str(plan.get("agent_code") or plan.get("code") or "").strip()
    if raw:
        return raw.upper()
    title = (workflow.title or "").strip()
    if title:
        slug = "".join(ch for ch in title.upper() if ch.isalnum())[:6]
        if slug:
            return slug
    return f"WF-{index + 1:02d}"


def _overlay_from_db(
    db: Session,
    *,
    user_id: str,
    dashboard: WorkplaceKpiDashboardOut,
    start: datetime,
    end: datetime,
    day_from: date,
    day_to: date,
) -> WorkplaceKpiDashboardOut:
    runs = list(
        db.execute(
            select(AgentRun).where(
                AgentRun.user_id == user_id,
                AgentRun.started_at >= start,
                AgentRun.started_at <= end,
            )
        )
        .scalars()
        .all()
    )
    workflows = list(
        db.execute(
            select(Workflow).where(Workflow.user_id == user_id, Workflow.phase == "done").order_by(Workflow.title)
        )
        .scalars()
        .all()
    )

    cards = list(dashboard.cards)
    agents = list(dashboard.agents)

    if runs:
        finished = [run for run in runs if _is_success(run.status) or (run.status or "").lower() in _FAIL]
        ok = sum(1 for run in finished if _is_success(run.status))
        total = len(finished) or len(runs)
        task_pct = round(100 * ok / total) if total else 78
        cards[0] = cards[0].model_copy(
            update={
                "display_value": f"{task_pct}%",
                "progress": task_pct,
                "source": "computed",
            }
        )
        sla_pct = task_pct if total >= 3 else cards[1].progress or 92
        cards[1] = cards[1].model_copy(
            update={"display_value": f"{sla_pct}%", "progress": sla_pct, "source": "computed"}
        )
        load_pct = min(100, max(10, round(len(runs) * 4)))
        cards[2] = cards[2].model_copy(
            update={"display_value": f"{load_pct}%", "progress": load_pct, "source": "computed"}
        )

    if workflows:
        by_wf: dict[str, list[AgentRun]] = {}
        for run in runs:
            by_wf.setdefault(run.workflow_id, []).append(run)
        computed_agents: list[WorkplaceKpiAgentRowOut] = []
        for index, wf in enumerate(workflows[:8]):
            wf_runs = by_wf.get(wf.id, [])
            finished = [r for r in wf_runs if _is_success(r.status) or (r.status or "").lower() in _FAIL]
            ok = sum(1 for r in finished if _is_success(r.status))
            total = len(finished) or len(wf_runs)
            completion = round(100 * ok / total) if total else dashboard.agents[min(index, len(dashboard.agents) - 1)].completion_pct
            ref = dashboard.agents[min(index, len(dashboard.agents) - 1)]
            sla = completion if total else ref.sla_pct
            load = min(100, len(wf_runs) * 8) if wf_runs else ref.load_pct
            auto = ref.automation_pct if not total else min(99, max(40, completion - 10))
            status, tone = _status_for(completion)
            computed_agents.append(
                WorkplaceKpiAgentRowOut(
                    id=wf.id,
                    code=_workflow_code(wf, index),
                    name=wf.title or ref.name,
                    process=ref.process,
                    completion_pct=completion,
                    sla_pct=sla,
                    load_pct=load,
                    automation_pct=auto,
                    status=status,
                    status_tone=tone,
                    source="computed" if wf_runs else "reference",
                )
            )
        if computed_agents:
            agents = computed_agents

    employee_kpi = _employee_kpi_from_runs(runs, day_from, day_to, dashboard.employee_kpi or _reference_employee_kpi())
    quality_score = float(employee_kpi[2].display_value) if len(employee_kpi) > 2 else 4.7
    waiting_human = frozenset(
        run.workflow_id
        for run in runs
        if (run.status or "").lower() in {"waiting_human", "waiting", "paused", "human"}
    )
    problem_zones = dashboard.problem_zones
    if agents and any(a.source == "computed" for a in agents):
        built = _build_problem_zones_from_agents(agents, waiting_human_wf_ids=waiting_human, quality_score=quality_score)
        if built:
            problem_zones = built

    dynamics = dynamics_from_daily_metrics(
        db,
        user_id=user_id,
        day_from=day_from,
        day_to=day_to,
        fallback=dashboard.dynamics,
    )

    return dashboard.model_copy(
        update={
            "cards": cards,
            "agents": agents,
            "employee_kpi": employee_kpi,
            "problem_zones": problem_zones,
            "dynamics": dynamics,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def build_workplace_kpi_dashboard(
    db: Session,
    *,
    user_id: str,
    period_from: str | None = None,
    period_to: str | None = None,
) -> WorkplaceKpiDashboardOut:
    day_from = _parse_day(period_from, DEFAULT_PERIOD_FROM)
    day_to = _parse_day(period_to, DEFAULT_PERIOD_TO)
    start, end = _period_bounds(day_from, day_to)
    base = _reference_dashboard(day_from, day_to)
    return _overlay_from_db(
        db, user_id=user_id, dashboard=base, start=start, end=end, day_from=day_from, day_to=day_to
    )
