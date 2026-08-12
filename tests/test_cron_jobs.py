from __future__ import annotations

import pytest

from platform_orchestrator.cron_jobs import (
    build_tool_calls,
    compute_next_run,
    list_templates,
    validate_cron_expr,
)


def test_validate_cron_expr_accepts_daily() -> None:
    assert validate_cron_expr("0 8 * * *") == "0 8 * * *"


def test_validate_cron_expr_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        validate_cron_expr("not a cron")


def test_compute_next_run_future() -> None:
    nxt = compute_next_run("0 8 * * *", "Europe/Moscow")
    assert nxt.tzinfo is not None


def test_daily_tasks_template_builds_onec_call() -> None:
    calls = build_tool_calls("daily_tasks", {"top": 10}, [])
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "onec.com.query_tasks"
    assert calls[0]["payload"]["limit"] == 10
    assert calls[0]["payload"]["mine_only"] is True


def test_daily_mail_template_builds_imap_call() -> None:
    calls = build_tool_calls("daily_mail", {"query": "UNSEEN"}, [])
    assert calls[0]["tool_name"] == "imap.search"
    assert calls[0]["payload"]["query"] == "UNSEEN"


def test_list_templates_includes_daily_jobs() -> None:
    ids = {item.id for item in list_templates()}
    assert "daily_tasks" in ids
    assert "daily_mail" in ids
