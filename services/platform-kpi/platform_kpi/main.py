from __future__ import annotations

import json
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic_settings import BaseSettings, SettingsConfigDict
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from sqlalchemy import func, or_, select

from platform_contracts.agent_card import AgentTaskReport
from platform_contracts.kpi import (
    AgentExecutionHistoryComplete,
    AgentExecutionHistoryListResponse,
    AgentExecutionHistoryOut,
    AgentExecutionHistoryStart,
    KpiSummary,
    ReviewEvent,
    ReviewEventCreate,
)
from platform_db.models import (
    AgentCardRow,
    AgentExecutionHistoryRow,
    AgentRunRow,
    AgentTaskReportRow,
    ReviewEventRow,
    ToolEventRow,
)
from platform_db.session import get_session_factory

SUCCESS_STATUSES = ("done",)
ERROR_STATUSES = ("error",)
HITL_STATUSES = ("hitl",)
TASK_SUCCESS_STATUSES = frozenset({"done", "success", "completed", "ok", "correct"})
COMPLETE_STATUSES = frozenset({"done", "error"})
KPI_TASK_WINDOW = 100
OPERATOR_APPROVE = "operator_approve"
OPERATOR_CHANGE = "operator_change"

GAUGE_SUCCESS_RATE = Gauge("constructor_success_rate", "Agent run success rate")
GAUGE_ERROR_RATE = Gauge("constructor_error_rate", "Agent run error rate")
GAUGE_HITL_RATE = Gauge("constructor_hitl_rate", "Agent run HITL rate")
GAUGE_OPERATOR_KEEP = Gauge("constructor_operator_keep_rate", "Operator keep rate")
GAUGE_TOOL_FAILURE = Gauge("constructor_tool_failure_rate", "Tool failure rate")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor"
    )
    api_host: str = "0.0.0.0"
    api_port: int = 7820


settings = Settings()
app = FastAPI(title="platform-kpi", version="0.1.0")


def operator_approval_rate(saved: int, changed: int) -> float | None:
    total = saved + changed
    if total <= 0:
        return None
    return round(saved / total, 4)


def optional_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    return uuid.UUID(str(value))


def task_kpi_metrics(reports: list[AgentTaskReportRow]) -> tuple[int, int, int]:
    """Return (correct, window_total, lifetime_total) for sliding window KPI."""
    lifetime = len(reports)
    window = reports[-KPI_TASK_WINDOW:] if lifetime > KPI_TASK_WINDOW else reports
    window_total = len(window)
    correct = sum(1 for row in window if row.status.lower() in TASK_SUCCESS_STATUSES)
    return correct, window_total, lifetime


@dataclass(frozen=True)
class ExecutionHistoryMetrics:
    started_total: int
    finished_total: int
    done_total: int
    failed_total: int
    in_progress: int
    lifetime_total: int
    avg_duration_sec: float
    median_duration_sec: float

    @property
    def success_rate(self) -> float:
        if self.finished_total <= 0:
            return 0.0
        return round(self.done_total / self.finished_total, 4)

    @property
    def error_rate(self) -> float:
        if self.finished_total <= 0:
            return 0.0
        return round(self.failed_total / self.finished_total, 4)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _history_status(row: AgentExecutionHistoryRow) -> str:
    return str(getattr(row, "status", "") or "").strip().lower()


def _is_finished(row: AgentExecutionHistoryRow) -> bool:
    return bool(row.is_completed and row.completed_at is not None)


def execution_history_task_metrics(
    rows: list[AgentExecutionHistoryRow],
) -> ExecutionHistoryMetrics:
    """Window metrics: finished = completed rows; in-progress is not a failure."""
    started_rows = [row for row in rows if row.is_started]
    finished_rows = [row for row in started_rows if _is_finished(row)]
    done_total = sum(1 for row in finished_rows if _history_status(row) == "done")
    failed_total = sum(1 for row in finished_rows if _history_status(row) == "error")
    in_progress = sum(1 for row in started_rows if not _is_finished(row))
    durations = [
        (row.completed_at - row.started_at).total_seconds()
        for row in finished_rows
        if row.completed_at is not None
    ]
    avg_sec = round(sum(durations) / len(durations), 2) if durations else 0.0
    median_sec = round(float(statistics.median(durations)), 2) if durations else 0.0
    return ExecutionHistoryMetrics(
        started_total=len(started_rows),
        finished_total=len(finished_rows),
        done_total=done_total,
        failed_total=failed_total,
        in_progress=in_progress,
        lifetime_total=len(rows),
        avg_duration_sec=avg_sec,
        median_duration_sec=median_sec,
    )


def compute_success_rate_delta(
    current_rate: float,
    previous_finished: int,
    previous_rate: float,
) -> float | None:
    if previous_finished <= 0:
        return None
    return round(current_rate - previous_rate, 4)


def _visible_agent_card_ids(department: str):
    query = select(AgentCardRow.agent_id).where(AgentCardRow.enabled.is_(True))
    dept = (department or "").strip()
    if dept:
        query = query.where(
            or_(
                AgentCardRow.department == dept,
                AgentCardRow.department == "",
                AgentCardRow.department.is_(None),
            )
        )
    return query


def _apply_history_scope(query, *, department: str = "", agent_id: str = ""):
    if agent_id:
        query = query.where(AgentExecutionHistoryRow.agent_id == agent_id)
    if department:
        query = query.where(
            AgentExecutionHistoryRow.agent_id.in_(_visible_agent_card_ids(department))
        )
    return query


def _execution_history_out(row: AgentExecutionHistoryRow) -> AgentExecutionHistoryOut:
    duration_sec: float | None = None
    if row.is_completed and row.completed_at is not None:
        duration_sec = round((row.completed_at - row.started_at).total_seconds(), 2)
    return AgentExecutionHistoryOut(
        id=row.id,
        agent_id=row.agent_id,
        process_seq=row.process_seq,
        started_at=row.started_at,
        completed_at=row.completed_at,
        is_started=row.is_started,
        is_completed=row.is_completed,
        duration_sec=duration_sec,
        status=_history_status(row),
    )


def _next_process_seq(session, agent_id: str) -> int:
    current = session.scalar(
        select(func.max(AgentExecutionHistoryRow.process_seq)).where(
            AgentExecutionHistoryRow.agent_id == agent_id
        )
    )
    return int(current or 0) + 1


def collect_summary(*, department: str = "", agent_id: str = "", hours: int = 24) -> KpiSummary:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    factory = get_session_factory()

    with factory() as session:
        runs_q = select(AgentRunRow).where(AgentRunRow.started_at >= start)
        if department:
            runs_q = runs_q.where(AgentRunRow.department == department)
        if agent_id:
            runs_q = runs_q.where(AgentRunRow.agent_id == agent_id)

        runs = session.scalars(runs_q).all()
        total_runs = len(runs)
        success = sum(1 for r in runs if r.status in SUCCESS_STATUSES)
        errors = sum(1 for r in runs if r.status in ERROR_STATUSES)
        hitl = sum(1 for r in runs if r.status in HITL_STATUSES)

        saved_q = select(func.count()).select_from(ReviewEventRow).where(
            ReviewEventRow.created_at >= start,
            ReviewEventRow.event_type == OPERATOR_APPROVE,
        )
        changed_q = select(func.count()).select_from(ReviewEventRow).where(
            ReviewEventRow.created_at >= start,
            ReviewEventRow.event_type == OPERATOR_CHANGE,
        )
        tool_inv_q = select(func.count()).select_from(ToolEventRow).where(
            ToolEventRow.created_at >= start
        )
        tool_fail_q = select(func.count()).select_from(ToolEventRow).where(
            ToolEventRow.created_at >= start,
            ToolEventRow.status == "error",
        )
        if department:
            saved_q = saved_q.where(ReviewEventRow.department == department)
            changed_q = changed_q.where(ReviewEventRow.department == department)
            tool_inv_q = tool_inv_q.where(ToolEventRow.department == department)
            tool_fail_q = tool_fail_q.where(ToolEventRow.department == department)

        saved = session.scalar(saved_q) or 0
        changed = session.scalar(changed_q) or 0
        tool_invocations = session.scalar(tool_inv_q) or 0
        tool_failures = session.scalar(tool_fail_q) or 0

        tasks_correct = 0
        tasks_total = 0
        tasks_lifetime_total = 0
        completed_tasks_total = 0
        avg_execution_duration_sec = 0.0
        tasks_failed = 0
        task_error_rate = 0.0
        tasks_in_progress = 0
        median_execution_duration_sec = 0.0
        tasks_per_day = 0.0
        success_rate_delta = None

        lifetime_q = _apply_history_scope(
            select(func.count()).select_from(AgentExecutionHistoryRow),
            department=department,
            agent_id=agent_id,
        )
        tasks_lifetime_total = int(session.scalar(lifetime_q) or 0)

        if tasks_lifetime_total > 0:
            prev_start = start - timedelta(hours=hours)
            history_q = _apply_history_scope(
                select(AgentExecutionHistoryRow),
                department=department,
                agent_id=agent_id,
            ).where(AgentExecutionHistoryRow.started_at >= prev_start)
            history_rows = session.scalars(history_q).all()
            current_rows = [row for row in history_rows if _as_utc(row.started_at) >= start]
            previous_rows = [row for row in history_rows if _as_utc(row.started_at) < start]
            current = execution_history_task_metrics(current_rows)
            previous = execution_history_task_metrics(previous_rows)
            tasks_correct = current.done_total
            tasks_total = current.finished_total
            completed_tasks_total = current.finished_total
            avg_execution_duration_sec = current.avg_duration_sec
            tasks_failed = current.failed_total
            task_error_rate = current.error_rate
            tasks_in_progress = current.in_progress
            median_execution_duration_sec = current.median_duration_sec
            days = hours / 24.0
            tasks_per_day = round(current.finished_total / days, 2) if days else 0.0
            success_rate_delta = compute_success_rate_delta(
                current.success_rate,
                previous.finished_total,
                previous.success_rate,
            )
        else:
            reports_q = select(AgentTaskReportRow).order_by(AgentTaskReportRow.created_at.asc())
            if agent_id:
                reports_q = reports_q.where(AgentTaskReportRow.agent_id == agent_id)
            if department:
                reports_q = reports_q.where(
                    AgentTaskReportRow.agent_id.in_(_visible_agent_card_ids(department))
                )
            reports = session.scalars(reports_q).all()
            tasks_correct, tasks_total, tasks_lifetime_total = task_kpi_metrics(reports)

    def rate(n: int, d: int) -> float:
        return round(n / d, 4) if d else 0.0

    summary = KpiSummary(
        period_start=start,
        period_end=end,
        total_runs=total_runs,
        success_rate=rate(success, total_runs),
        error_rate=rate(errors, total_runs),
        hitl_rate=rate(hitl, total_runs),
        operator_keep_rate=operator_approval_rate(int(saved), int(changed)),
        tool_failure_rate=rate(int(tool_failures), int(tool_invocations)),
        operator_saved=int(saved),
        operator_changed=int(changed),
        tool_invocations=int(tool_invocations),
        tool_failures=int(tool_failures),
        tasks_correct=int(tasks_correct),
        tasks_total=int(tasks_total),
        tasks_lifetime_total=int(tasks_lifetime_total),
        task_success_rate=rate(int(tasks_correct), int(tasks_total)),
        completed_tasks_total=int(completed_tasks_total),
        avg_execution_duration_sec=float(avg_execution_duration_sec),
        tasks_failed=int(tasks_failed),
        task_error_rate=float(task_error_rate),
        tasks_in_progress=int(tasks_in_progress),
        median_execution_duration_sec=float(median_execution_duration_sec),
        tasks_per_day=float(tasks_per_day),
        success_rate_delta=success_rate_delta,
    )

    GAUGE_SUCCESS_RATE.set(summary.success_rate)
    GAUGE_ERROR_RATE.set(summary.error_rate)
    GAUGE_HITL_RATE.set(summary.hitl_rate)
    GAUGE_OPERATOR_KEEP.set(summary.operator_keep_rate or 0.0)
    GAUGE_TOOL_FAILURE.set(summary.tool_failure_rate)
    return summary


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "platform-kpi"}


@app.get("/metrics")
def metrics() -> Response:
    collect_summary()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/kpi/summary", response_model=KpiSummary)
def kpi_summary(
    department: str = Query(default=""),
    agent_id: str = Query(default=""),
    hours: int = Query(default=24, ge=1, le=24 * 30),
) -> KpiSummary:
    return collect_summary(
        department=department.strip(),
        agent_id=agent_id.strip(),
        hours=hours,
    )


@app.post("/api/v1/kpi/agent-tasks/report")
def agent_task_report(body: AgentTaskReport) -> dict:
    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    row = AgentTaskReportRow(
        id=uuid.uuid4(),
        agent_id=body.agent_id,
        session_id=optional_uuid(body.session_id),
        run_id=optional_uuid(body.run_id),
        task_id=body.task_id,
        status=body.status,
        quality_score=body.quality_score,
        summary=body.summary,
        outcome_json=json.dumps(body.outcome, ensure_ascii=False),
        metadata_json=json.dumps(body.metadata, ensure_ascii=False),
        created_at=now,
    )
    with factory() as session:
        session.add(row)
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "id": str(row.id),
        "agent_id": row.agent_id,
        "task_id": row.task_id,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


@app.post("/api/v1/kpi/review", response_model=ReviewEvent)
def kpi_review(body: ReviewEventCreate) -> ReviewEvent:
    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    row = ReviewEventRow(
        id=uuid.uuid4(),
        run_id=body.run_id,
        category=body.category,
        event_type=body.event_type,
        actor=body.actor,
        source=body.source,
        department=body.department,
        old_value=body.old_value,
        new_value=body.new_value,
        created_at=now,
    )
    with factory() as session:
        session.add(row)
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ReviewEvent(
        id=row.id,
        run_id=row.run_id,
        actor=row.actor,
        event_type=row.event_type,
        category=row.category,
        old_value=row.old_value,
        new_value=row.new_value,
        source=row.source,
        department=row.department,
        created_at=row.created_at,
    )


@app.get("/api/v1/kpi/execution-history", response_model=AgentExecutionHistoryListResponse)
def list_execution_history(
    agent_id: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=500),
) -> AgentExecutionHistoryListResponse:
    factory = get_session_factory()
    with factory() as session:
        query = select(AgentExecutionHistoryRow).order_by(
            AgentExecutionHistoryRow.started_at.desc()
        )
        agent = agent_id.strip()
        if agent:
            query = query.where(AgentExecutionHistoryRow.agent_id == agent)
        rows = session.scalars(query.limit(limit)).all()
    return AgentExecutionHistoryListResponse(items=[_execution_history_out(row) for row in rows])


@app.post("/api/v1/kpi/execution-history/start", response_model=AgentExecutionHistoryOut)
def start_execution_history(body: AgentExecutionHistoryStart) -> AgentExecutionHistoryOut:
    agent_id = body.agent_id.strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id обязателен")

    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    row = AgentExecutionHistoryRow(
        id=uuid.uuid4(),
        agent_id=agent_id,
        process_seq=0,
        started_at=now,
        completed_at=None,
        is_started=True,
        is_completed=False,
        status="pending",
    )
    with factory() as session:
        row.process_seq = _next_process_seq(session, agent_id)
        session.add(row)
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        session.refresh(row)
    return _execution_history_out(row)


@app.post(
    "/api/v1/kpi/execution-history/{history_id}/complete",
    response_model=AgentExecutionHistoryOut,
)
def complete_execution_history(
    history_id: uuid.UUID,
    body: AgentExecutionHistoryComplete | None = Body(default=None),
) -> AgentExecutionHistoryOut:
    status = (body.status if body is not None else "done").strip().lower()
    if status not in COMPLETE_STATUSES:
        raise HTTPException(status_code=400, detail="status должен быть done или error")

    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    with factory() as session:
        row = session.get(AgentExecutionHistoryRow, history_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Запись истории не найдена")
        if row.is_completed:
            return _execution_history_out(row)
        row.is_completed = True
        row.completed_at = now
        row.status = status
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        session.refresh(row)
    return _execution_history_out(row)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
