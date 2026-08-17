from __future__ import annotations

from app.models.workflow import Workflow
from app.services.agent_runtime import _agent_domain
from app.services.plan_run import ensure_runtime
from app.services.workflow_tool_routing import resolve_workflow_routing
from app.services.workflows.plan_models import WorkflowPlan
from app.services.workflows.service import _tools_for_published_plan


def test_runtime_tools_survive_roundtrip() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Meeting agent",
            "runtime": {
                "kind": "outlook_calendar",
                "tools": ["outlook.read_calendar", "outlook.search_mail"],
            },
        }
    )

    data = plan.to_dict()

    assert data["runtime"]["kind"] == "outlook_calendar"
    assert data["runtime"]["tools"] == ["outlook.read_calendar", "outlook.search_mail"]


def test_shared_routing_prefers_explicit_tools() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Meeting agent",
            "goal": "Read calendar",
            "runtime": {
                "tools": ["outlook.read_calendar"],
            },
        }
    )

    route = resolve_workflow_routing(plan)

    assert route.kind == "outlook_calendar"
    assert route.tools == ["outlook.read_calendar"]


def test_ensure_runtime_fills_site_search_defaults() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Tender search",
            "goal": "Find items",
            "runtime": {
                "kind": "site_search_excel",
                "site_url": "https://example.test",
                "keyword_text": "болты; гайки",
            },
        }
    )

    ensure_runtime(plan)

    assert plan.runtime.kind == "site_search_excel"
    assert plan.runtime.tools == ["site_browser", "web_search"]
    assert plan.runtime.export_format == "xlsx"
    assert plan.runtime.export_destination == "desktop"
    assert plan.runtime.keywords == ["болты", "гайки"]


def test_published_tools_follow_shared_router() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Tender search",
            "goal": "Find items",
            "runtime": {
                "kind": "site_search_excel",
                "site_url": "https://example.test",
                "keywords": ["болты", "гайки"],
            },
        }
    )
    workflow = Workflow(
        id="wf-1",
        user_id="user-1",
        title="Tender search",
        notes="Search by keywords and export to Excel",
        plan_json=plan.to_dict(),
    )

    tools = _tools_for_published_plan(plan, workflow)

    assert tools == ["site_browser", "web_search"]


def test_agent_domain_uses_shared_router() -> None:
    workflow = Workflow(
        id="wf-2",
        user_id="user-1",
        title="1C lookup",
        notes="Need OData access",
        plan_json={
            "title": "1C lookup",
            "goal": "Read documents",
            "runtime": {"tools": ["onec.odata_get"]},
        },
    )

    assert _agent_domain(workflow) == "onec"
