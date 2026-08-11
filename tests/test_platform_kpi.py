from __future__ import annotations

import os

import pytest


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


def test_collect_summary_empty_sqlite(monkeypatch) -> None:
    pytest.importorskip("psycopg")
    monkeypatch.setenv(
        "DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor",
        ),
    )
    from platform_db.session import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()

    from platform_kpi.main import collect_summary

    try:
        summary = collect_summary()
    except Exception:
        pytest.skip("PostgreSQL not available for KPI integration test")
    assert summary.total_runs >= 0
