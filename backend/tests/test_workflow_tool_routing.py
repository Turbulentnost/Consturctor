from __future__ import annotations

from app.models.workflow import Workflow
from app.services.agent_runtime import _agent_domain, _run_hybrid_task
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


def test_runtime_phases_survive_roundtrip() -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Hybrid agent",
            "runtime": {
                "kind": "hybrid",
                "phases": [
                    {
                        "id": "p1",
                        "kind": "onec",
                        "tools": ["onec.search_documents", "onec.get_document_card"],
                        "handoff": "extract participants and meeting time",
                    },
                    {
                        "id": "p2",
                        "kind": "outlook_calendar",
                        "tools": ["outlook.read_calendar"],
                        "depends_on": ["p1"],
                        "handoff": "check calendar using 1C facts",
                    },
                ],
            },
        }
    )

    data = plan.to_dict()

    assert data["runtime"]["kind"] == "hybrid"
    assert [phase["kind"] for phase in data["runtime"]["phases"]] == [
        "onec",
        "outlook_calendar",
    ]


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


def test_hybrid_executor_runs_onec_then_outlook(monkeypatch) -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Hybrid agent",
            "runtime": {
                "kind": "hybrid",
                "phases": [
                    {
                        "id": "p1",
                        "kind": "onec",
                        "tools": ["onec.search_documents", "onec.get_document_card"],
                        "handoff": "find the service note",
                    },
                    {
                        "id": "p2",
                        "kind": "outlook_calendar",
                        "tools": ["outlook.read_calendar"],
                        "depends_on": ["p1"],
                        "handoff": "use 1C facts to inspect calendar",
                    },
                ],
            },
        }
    )
    workflow = Workflow(
        id="wf-1",
        user_id="user-1",
        title="Hybrid agent",
        plan_json=plan.to_dict(),
    )
    events: list[dict] = []
    calls: list[tuple[str, dict]] = []

    def emit(payload: dict) -> None:
        events.append(payload)

    def fake_request_desktop_tool(
        emit,
        *,
        run_id: str,
        user_id: str,
        workflow_id: str = "",
        tool: str,
        arguments: dict,
        timeout_s: float = 30.0,
    ) -> dict:
        _ = emit, run_id, user_id, workflow_id, timeout_s
        calls.append((tool, dict(arguments)))
        if tool == "onec.search_documents":
            return {
                "documents": [
                    {
                        "ref": "doc-ref-1",
                        "title": "Служебная записка",
                        "status": "На согласовании",
                    }
                ],
                "count": 1,
            }
        if tool == "onec.get_document_card":
            return {
                "document": {
                    "ref": "doc-ref-1",
                    "author": "Иванов И.И.",
                    "responsible": "Петров П.П.",
                    "content_preview": "Нужно проверить календарь и подтвердить слот.",
                }
            }
        if tool == "outlook.read_calendar":
            return {
                "events": [
                    {
                        "subject": "Планерка",
                        "start": "2026-08-18T08:15:00+00:00",
                    }
                ]
            }
        raise AssertionError(f"Unexpected tool: {tool}")

    monkeypatch.setattr("app.services.agent_runtime._request_desktop_tool", fake_request_desktop_tool)

    result = _run_hybrid_task(
        plan=plan,
        workflow=workflow,
        task="Проверь служебную записку 1С и календарь Outlook",
        emit=emit,
        run_id="run-1",
        user_id="user-1",
        workflow_id="wf-1",
    )

    assert [tool for tool, _ in calls] == [
        "onec.search_documents",
        "onec.get_document_card",
        "outlook.read_calendar",
    ]
    assert "1C: данные получены." in result["answer"]
    assert "Outlook" in result["answer"] or "Планерка" in result["answer"]
    assert result["tool"] == "hybrid"
    assert len(result["tool_result"]["phases"]) == 2


def test_hybrid_executor_runs_browser_then_onec(monkeypatch) -> None:
    plan = WorkflowPlan.from_dict(
        {
            "title": "Hybrid agent",
            "runtime": {
                "kind": "hybrid",
                "phases": [
                    {
                        "id": "p1",
                        "kind": "browser_task",
                        "tools": ["web_search"],
                        "handoff": "find the latest page with the schedule",
                    },
                    {
                        "id": "p2",
                        "kind": "onec",
                        "tools": ["onec.search_documents"],
                        "depends_on": ["p1"],
                        "handoff": "use browser findings to search 1C",
                    },
                ],
            },
        }
    )
    workflow = Workflow(
        id="wf-2",
        user_id="user-1",
        title="Hybrid agent",
        plan_json=plan.to_dict(),
    )
    calls: list[str] = []

    def emit(payload: dict) -> None:
        _ = payload

    def fake_request_desktop_tool(
        emit,
        *,
        run_id: str,
        user_id: str,
        workflow_id: str = "",
        tool: str,
        arguments: dict,
        timeout_s: float = 30.0,
    ) -> dict:
        _ = emit, run_id, user_id, workflow_id, timeout_s, arguments
        calls.append(tool)
        if tool == "web_search":
            return {
                "results": [
                    {"title": "Schedule page", "url": "https://example.test/schedule"}
                ]
            }
        if tool == "onec.search_documents":
            return {
                "documents": [{"ref": "doc-ref-2", "title": "Service note"}],
                "count": 1,
            }
        raise AssertionError(f"Unexpected tool: {tool}")

    monkeypatch.setattr("app.services.agent_runtime._request_desktop_tool", fake_request_desktop_tool)

    result = _run_hybrid_task(
        plan=plan,
        workflow=workflow,
        task="Найди расписание и затем проверь 1С",
        emit=emit,
        run_id="run-2",
        user_id="user-1",
        workflow_id="wf-2",
    )

    assert calls == ["web_search", "onec.search_documents"]
    assert result["tool"] == "hybrid"
    assert len(result["tool_result"]["phases"]) == 2
