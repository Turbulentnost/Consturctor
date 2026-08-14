from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from platform_contracts.agent_card import AgentCard, AgentTaskSpec
from platform_contracts.kpi import (
    AgentExecutionHistoryComplete,
    AgentExecutionHistoryOut,
    KpiSummary,
    ReviewEventCreate,
)
from platform_contracts.runs import RunStartRequest, RunStatus, RunStatusEnum
from platform_contracts.tools import ToolInvokeRequest, ToolResult


def test_tool_invoke_request_defaults() -> None:
    req = ToolInvokeRequest()
    assert req.payload == {}
    assert req.department == ""


def test_tool_result_ok() -> None:
    result = ToolResult(ok=True, tool_name="imap.list_unread", data={"count": 1})
    assert result.error is None
    assert result.duration_ms == 0


def test_run_start_request() -> None:
    body = RunStartRequest(agent_id="demo", tools=["imap.list_unread"])
    assert body.agent_id == "demo"
    assert "imap.list_unread" in body.tools


def test_run_status_enum() -> None:
    status = RunStatus(
        run_id=uuid4(),
        agent_id="demo",
        status=RunStatusEnum.PENDING,
        started_at=datetime.now(timezone.utc),
    )
    assert status.status == RunStatusEnum.PENDING


def test_kpi_summary_defaults() -> None:
    summary = KpiSummary()
    assert summary.total_runs == 0
    assert summary.success_rate == 0.0
    assert summary.tasks_total == 0
    assert summary.tasks_lifetime_total == 0
    assert summary.task_success_rate == 0.0
    assert summary.completed_tasks_total == 0
    assert summary.avg_execution_duration_sec == 0.0
    assert summary.tasks_failed == 0
    assert summary.task_error_rate == 0.0
    assert summary.tasks_in_progress == 0
    assert summary.median_execution_duration_sec == 0.0
    assert summary.tasks_per_day == 0.0
    assert summary.success_rate_delta is None


def test_execution_history_complete_default() -> None:
    body = AgentExecutionHistoryComplete()
    assert body.status == "done"
    out = AgentExecutionHistoryOut(
        id=uuid4(),
        agent_id="demo",
        process_seq=1,
        started_at=datetime.now(timezone.utc),
    )
    assert out.status == ""


def test_agent_card_tasks() -> None:
    card = AgentCard(
        agent_id="inbound-mail-v1",
        title="Test",
        tasks=[
            AgentTaskSpec(
                task_id="classify_incoming",
                title="Классификация",
                evaluation_criteria={"requires_category": True},
            )
        ],
    )
    assert card.tasks[0].task_id == "classify_incoming"
    assert "allowed_tools" not in AgentTaskSpec.model_fields


def test_review_event_create() -> None:
    event = ReviewEventCreate(event_type="operator_approve", category="department")
    assert event.actor == "operator"


def test_access_level_specs() -> None:
    from platform_contracts.access import (
        AccessLevelTransitionPolicy,
        DEFAULT_ACCESS_LEVELS,
    )

    assert len(DEFAULT_ACCESS_LEVELS) == 4
    assert DEFAULT_ACCESS_LEVELS[0].level == 1
    policy = AccessLevelTransitionPolicy(promote_threshold=80, demote_threshold=60)
    assert policy.evaluation_window_days == 7
