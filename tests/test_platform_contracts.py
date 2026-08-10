from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from platform_contracts.kpi import KpiSummary, ReviewEventCreate
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


def test_review_event_create() -> None:
    event = ReviewEventCreate(event_type="operator_approve", category="department")
    assert event.actor == "operator"
