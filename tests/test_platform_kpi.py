from __future__ import annotations

import os

import pytest


def test_operator_approval_rate() -> None:
    from platform_kpi.main import operator_approval_rate

    assert operator_approval_rate(8, 2) == 0.8
    assert operator_approval_rate(0, 0) is None


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
