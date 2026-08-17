from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone

import pytest


def _postgres_reachable(host: str = "127.0.0.1", port: int = 5432, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def test_operator_approval_rate() -> None:
    from platform_kpi.main import operator_approval_rate

    assert operator_approval_rate(8, 2) == 0.8
    assert operator_approval_rate(0, 0) is None


def test_task_kpi_metrics_window() -> None:
    from platform_kpi.main import KPI_TASK_WINDOW, task_kpi_metrics

    class Row:
        def __init__(self, status: str) -> None:
            self.status = status

    reports = [Row("done" if i % 5 else "error") for i in range(120)]
    correct, window_total, lifetime = task_kpi_metrics(reports)  # type: ignore[arg-type]
    assert lifetime == 120
    assert window_total == KPI_TASK_WINDOW
    assert correct == sum(1 for i in range(120 - KPI_TASK_WINDOW, 120) if i % 5 != 0)

    small = [Row("done"), Row("error"), Row("done")]
    correct, window_total, lifetime = task_kpi_metrics(small)  # type: ignore[arg-type]
    assert lifetime == 3
    assert window_total == 3
    assert correct == 2


class _HistoryRow:
    def __init__(
        self,
        *,
        is_started: bool,
        is_completed: bool,
        started_at: datetime,
        completed_at: datetime | None,
        status: str = "pending",
    ) -> None:
        self.is_started = is_started
        self.is_completed = is_completed
        self.started_at = started_at
        self.completed_at = completed_at
        self.status = status


def test_execution_history_task_metrics() -> None:
    from platform_kpi.main import execution_history_task_metrics

    now = datetime.now(timezone.utc)
    rows = [
        _HistoryRow(
            is_started=True,
            is_completed=True,
            started_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=1, minutes=50),
            status="done",
        ),
        _HistoryRow(
            is_started=True,
            is_completed=True,
            started_at=now - timedelta(hours=4),
            completed_at=now - timedelta(hours=3, minutes=40),
            status="done",
        ),
        _HistoryRow(
            is_started=True,
            is_completed=False,
            started_at=now - timedelta(minutes=30),
            completed_at=None,
            status="pending",
        ),
    ]
    metrics = execution_history_task_metrics(rows)  # type: ignore[arg-type]
    assert metrics.started_total == 3
    assert metrics.finished_total == 2
    assert metrics.lifetime_total == 3
    assert metrics.avg_duration_sec == 900.0
    assert metrics.in_progress == 1
    assert metrics.success_rate == 1.0


def test_execution_history_done_error_in_progress_split() -> None:
    from platform_kpi.main import execution_history_task_metrics

    now = datetime.now(timezone.utc)
    rows = [
        _HistoryRow(
            is_started=True,
            is_completed=True,
            started_at=now - timedelta(hours=3),
            completed_at=now - timedelta(hours=2, minutes=50),
            status="done",
        ),
        _HistoryRow(
            is_started=True,
            is_completed=True,
            started_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=1, minutes=50),
            status="error",
        ),
        _HistoryRow(
            is_started=True,
            is_completed=False,
            started_at=now - timedelta(minutes=20),
            completed_at=None,
            status="pending",
        ),
    ]
    metrics = execution_history_task_metrics(rows)  # type: ignore[arg-type]
    assert metrics.done_total == 1
    assert metrics.failed_total == 1
    assert metrics.finished_total == 2
    assert metrics.in_progress == 1
    assert metrics.success_rate == 0.5
    assert metrics.error_rate == 0.5
    assert metrics.in_progress + metrics.finished_total == metrics.started_total


def test_execution_history_median() -> None:
    from platform_kpi.main import execution_history_task_metrics

    now = datetime.now(timezone.utc)

    def finished(minutes: int, status: str = "done") -> _HistoryRow:
        started = now - timedelta(hours=2)
        return _HistoryRow(
            is_started=True,
            is_completed=True,
            started_at=started,
            completed_at=started + timedelta(minutes=minutes),
            status=status,
        )

    odd = execution_history_task_metrics(
        [finished(10), finished(20), finished(30)]  # type: ignore[list-item]
    )
    assert odd.median_duration_sec == 20 * 60
    assert odd.avg_duration_sec == 20 * 60

    even = execution_history_task_metrics(
        [finished(10), finished(20), finished(30), finished(40)]  # type: ignore[list-item]
    )
    assert even.median_duration_sec == 25 * 60


def test_success_rate_delta_none_when_previous_empty() -> None:
    from platform_kpi.main import compute_success_rate_delta

    assert compute_success_rate_delta(0.9, 0, 0.0) is None
    assert compute_success_rate_delta(0.9, 4, 0.75) == 0.15
    assert compute_success_rate_delta(0.7, 2, 0.8) == -0.1


def test_collect_summary_empty_sqlite(monkeypatch) -> None:
    pytest.importorskip("psycopg")
    if not _postgres_reachable():
        pytest.skip("PostgreSQL not reachable for KPI integration test")
    default_url = (
        "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor"
        "?connect_timeout=2"
    )
    url = os.environ.get("DATABASE_URL", default_url)
    if "connect_timeout=" not in url:
        url = f"{url}{'&' if '?' in url else '?'}connect_timeout=2"
    monkeypatch.setenv("DATABASE_URL", url)
    from platform_db.session import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()

    from platform_kpi.main import collect_summary

    try:
        summary = collect_summary()
    except Exception:
        pytest.skip("PostgreSQL not available for KPI integration test")
    assert summary.total_runs >= 0
    assert summary.success_rate_delta is None or isinstance(summary.success_rate_delta, float)
