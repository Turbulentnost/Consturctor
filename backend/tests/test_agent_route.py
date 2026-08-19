from __future__ import annotations

from app.models.workflow import Workflow
from app.services.agent_route import (
    AgentRoute,
    build_route_from_passport,
    merge_agent_route,
    resolve_agent_route,
    resolve_agent_tool_names,
)


def test_resolve_agent_route_from_local_run() -> None:
    wf = Workflow(
        id="wf1",
        title="ACT",
        plan_json={"goal": "Выгрузи ACT"},
        local_run={
            "agent_route": {
                "handler": "act_porucheniya_registry",
                "default_task": "Выгрузи реестр ACT",
                "source": "api",
            }
        },
    )
    route = resolve_agent_route(wf)
    assert route.handler == "act_porucheniya_registry"
    assert route.default_task == "Выгрузи реестр ACT"


def test_resolve_idempotent_after_execution_backend_mcp() -> None:
    wf = Workflow(
        id="wf2",
        title="ACT",
        plan_json={
            "agent_route": {
                "handler": "act_porucheniya_registry",
                "default_task": "task",
            }
        },
        local_run={"execution_backend": "mcp", "runtime": "mcp"},
    )
    route = resolve_agent_route(wf)
    assert route.handler == "act_porucheniya_registry"


def test_merge_agent_route_patch() -> None:
    wf = Workflow(
        id="wf3",
        title="SMART",
        plan_json={"goal": "SMART check"},
        local_run={"agent_route": {"handler": "assignments_smart", "default_task": "old"}},
    )
    route = merge_agent_route(wf, {"default_task": "new task", "source": "api"})
    assert route.handler == "act_porucheniya_registry"
    assert route.default_task == "new task"


def test_build_route_from_passport_act() -> None:
    route = build_route_from_passport(
        passport_title="Реестр ACT",
        notes="Document_ТД_Поручения ACT00",
        goal="Выгрузи ACT",
    )
    assert route.handler == "act_porucheniya_registry"
    assert route.default_task == "Выгрузи ACT"


def test_resolve_porucheniya_smart_filename_over_seed() -> None:
    wf = Workflow(
        id="wf-smart",
        title="tmpp7ywmzmi_porucheniya_smart.txt",
        notes="SMART Action Tracker: поручения из 1С ERP",
        plan_json={},
        local_run={"seed": "porucheniya"},
    )
    route = resolve_agent_route(wf)
    assert route.handler == "act_porucheniya_registry"


def test_resolve_agent_tool_names_prefers_route_tools() -> None:
    wf = Workflow(
        id="wf-tools",
        title="A",
        plan_json={},
        local_run={
            "tools": ["excel.create_workbook"],
            "agent_route": {
                "handler": "generic",
                "tools": ["web_search", "notify.send"],
            },
        },
    )
    assert resolve_agent_tool_names(wf) == ["web_search", "notify.send"]


def test_resolve_agent_tool_names_act_defaults() -> None:
    wf = Workflow(
        id="wf-act",
        title="ACT",
        plan_json={},
        local_run={"agent_route": {"handler": "act_porucheniya_registry"}},
    )
    names = resolve_agent_tool_names(wf)
    assert "onec.act_porucheniya_registry" in names
    assert "excel.create_workbook" in names
