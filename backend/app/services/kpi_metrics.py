from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.kpi_metrics import AgentCardKpiOut, KpiMetricTemplate
from platform_contracts.agent_card import AgentKpiMetricSpec

logger = logging.getLogger(__name__)

KPI_METRIC_TEMPLATES: list[KpiMetricTemplate] = [
    KpiMetricTemplate(
        metric_id="task_success_rate",
        title="Доля успешно закрытых задач",
        kind="rate",
        source="agent_task_reports",
        threshold_min=0.8,
        weight=1.0,
        description="Процент задач агента со статусом success за период",
    ),
    KpiMetricTemplate(
        metric_id="avg_quality_score",
        title="Средняя оценка качества",
        kind="score",
        source="agent_task_reports",
        threshold_min=0.75,
        weight=1.0,
        description="Средний quality_score из отчётов агента",
    ),
    KpiMetricTemplate(
        metric_id="operator_keep_rate",
        title="Доля решений без правок оператора",
        kind="rate",
        source="review_events",
        threshold_min=0.85,
        weight=1.0,
        description="HITL: сколько раз оператор подтвердил результат без изменений",
    ),
    KpiMetricTemplate(
        metric_id="tool_failure_rate",
        title="Доля ошибок инструментов",
        kind="rate",
        source="tool_events",
        threshold_max=0.1,
        weight=0.8,
        description="Процент неуспешных вызовов tools за период",
    ),
    KpiMetricTemplate(
        metric_id="hitl_rate",
        title="Доля задач с участием оператора",
        kind="rate",
        source="agent_runs",
        threshold_max=0.3,
        weight=0.6,
        description="Как часто прогоны агента требуют вмешательства человека",
    ),
    KpiMetricTemplate(
        metric_id="run_success_rate",
        title="Успешность прогонов агента",
        kind="rate",
        source="agent_runs",
        threshold_min=0.9,
        weight=1.0,
        description="Доля agent_runs со статусом success",
    ),
    KpiMetricTemplate(
        metric_id="completed_tasks_total",
        title="Выполненные задачи",
        kind="count",
        source="agent_execution_history",
        threshold_min=1.0,
        weight=1.0,
        description="Количество завершённых процессов агента за период",
    ),
    KpiMetricTemplate(
        metric_id="avg_execution_duration_sec",
        title="Среднее время выполнения",
        kind="duration",
        source="agent_execution_history",
        threshold_max=600.0,
        weight=1.0,
        description="Средняя длительность завершённого процесса в секундах",
    ),
]


class KpiMetricsError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def list_metric_templates() -> list[KpiMetricTemplate]:
    return list(KPI_METRIC_TEMPLATES)


def _parse_metrics(raw: str | None) -> list[AgentKpiMetricSpec]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    metrics: list[AgentKpiMetricSpec] = []
    for item in data:
        if isinstance(item, dict):
            metrics.append(AgentKpiMetricSpec.model_validate(item))
    return metrics


def list_agent_cards(db: Session, *, department: str = "") -> list[AgentCardKpiOut]:
    dept = (department or "").strip()
    sql = """
        SELECT agent_id, title, department, kpi_metrics_json
        FROM platform_core.agent_cards
        WHERE enabled = TRUE
    """
    params: dict = {}
    if dept:
        sql += " AND (department = :department OR department = '' OR department IS NULL)"
        params["department"] = dept
    sql += " ORDER BY updated_at DESC, title ASC"
    try:
        rows = db.execute(text(sql), params).fetchall()
    except Exception as exc:
        logger.exception("Failed to list agent cards for KPI")
        raise KpiMetricsError("Таблица agent_cards недоступна. Запустите Postgres платформы.", 503) from exc

    items: list[AgentCardKpiOut] = []
    for row in rows:
        items.append(
            AgentCardKpiOut(
                agent_id=str(row.agent_id),
                title=str(row.title or row.agent_id),
                department=str(row.department or ""),
                kpi_metrics=_parse_metrics(row.kpi_metrics_json),
            )
        )
    return items


def get_agent_card_metrics(db: Session, agent_id: str) -> AgentCardKpiOut:
    row = db.execute(
        text(
            """
            SELECT agent_id, title, department, kpi_metrics_json
            FROM platform_core.agent_cards
            WHERE agent_id = :agent_id
            """
        ),
        {"agent_id": agent_id},
    ).fetchone()
    if row is None:
        raise KpiMetricsError("Карточка агента не найдена", status_code=404)
    return AgentCardKpiOut(
        agent_id=str(row.agent_id),
        title=str(row.title or row.agent_id),
        department=str(row.department or ""),
        kpi_metrics=_parse_metrics(row.kpi_metrics_json),
    )


def update_agent_card_metrics(
    db: Session,
    *,
    agent_id: str,
    metrics: list[AgentKpiMetricSpec],
) -> AgentCardKpiOut:
    if not metrics:
        raise KpiMetricsError("Добавьте хотя бы одну метрику")
    seen: set[str] = set()
    for metric in metrics:
        if metric.metric_id in seen:
            raise KpiMetricsError(f"Дублируется metric_id: {metric.metric_id}")
        seen.add(metric.metric_id)

    payload = json.dumps(
        [item.model_dump(mode="json") for item in metrics],
        ensure_ascii=False,
    )
    result = db.execute(
        text(
            """
            UPDATE platform_core.agent_cards
            SET kpi_metrics_json = :metrics_json, updated_at = NOW()
            WHERE agent_id = :agent_id
            RETURNING agent_id, title, department, kpi_metrics_json
            """
        ),
        {"agent_id": agent_id, "metrics_json": payload},
    ).fetchone()
    if result is None:
        raise KpiMetricsError("Карточка агента не найдена", status_code=404)
    db.commit()
    return AgentCardKpiOut(
        agent_id=str(result.agent_id),
        title=str(result.title or result.agent_id),
        department=str(result.department or ""),
        kpi_metrics=_parse_metrics(result.kpi_metrics_json),
    )


def update_agent_card_title(
    db: Session,
    *,
    agent_id: str,
    title: str,
) -> AgentCardKpiOut:
    cleaned = (title or "").strip()
    if not cleaned:
        raise KpiMetricsError("Имя агента не может быть пустым")
    if len(cleaned) > 120:
        raise KpiMetricsError("Имя агента слишком длинное")

    result = db.execute(
        text(
            """
            UPDATE platform_core.agent_cards
            SET title = :title, updated_at = NOW()
            WHERE agent_id = :agent_id
            RETURNING agent_id, title, department, kpi_metrics_json
            """
        ),
        {"agent_id": agent_id, "title": cleaned},
    ).fetchone()
    if result is None:
        raise KpiMetricsError("Карточка агента не найдена", status_code=404)
    db.commit()
    return AgentCardKpiOut(
        agent_id=str(result.agent_id),
        title=str(result.title or result.agent_id),
        department=str(result.department or ""),
        kpi_metrics=_parse_metrics(result.kpi_metrics_json),
    )
