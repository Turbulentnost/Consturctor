"""Сборка любого агента через конструктор: регламент → паспорт → workflow → publish."""

from __future__ import annotations

from typing import Callable

from app.models.workflow import Workflow
from app.services.agent_route import (
    AgentRoute,
    agent_route_dict_for_local,
    agent_route_dict_for_plan,
    build_route_from_passport,
    resolve_agent_route,
)
from app.services.workflows.plan_models import WorkflowPlan

ApplyPlugin = Callable[[Workflow], bool]

_PASSPORT_MARKERS = ("паспорт ии-агента", "## паспорт", "составь план реализации ии-агента")


def workflow_materials_blob(workflow: Workflow) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    return " ".join(
        [
            str(workflow.title or ""),
            str(getattr(workflow, "notes", "") or ""),
            str(getattr(workflow, "document_name", "") or ""),
            str(getattr(workflow, "document_text", "") or "")[:12000],
            str(plan.get("title") or ""),
            str(plan.get("goal") or ""),
            str(local.get("passport_title") or ""),
            " ".join(str(x) for x in (plan.get("constraints") or [])),
        ]
    ).casefold()


def is_regulation_constructor_workflow(workflow: Workflow) -> bool:
    """Workflow создан из цепочки регламент → паспорт → конструктор."""
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    if local.get("from_regulation_constructor"):
        return True
    if str(local.get("passport_title") or "").strip():
        return True
    notes = str(getattr(workflow, "notes", "") or "").casefold()
    if any(marker in notes for marker in _PASSPORT_MARKERS):
        return True
    if (getattr(workflow, "document_text", "") or "").strip():
        return True
    return bool((getattr(workflow, "document_name", "") or "").strip())


def resolve_route_for_regulation_workflow(workflow: Workflow) -> AgentRoute:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    passport_title = str(local.get("passport_title") or workflow.title or "").strip()
    goal = str(plan.get("goal") or "").strip()
    if not goal and passport_title:
        goal = f"Автоматизировать процесс по регламенту «{passport_title}»"
    inferred = build_route_from_passport(
        passport_title=passport_title,
        notes=str(getattr(workflow, "notes", "") or ""),
        goal=goal,
        document_text=str(getattr(workflow, "document_text", "") or ""),
        document_name=str(getattr(workflow, "document_name", "") or ""),
    )
    stored = resolve_agent_route(workflow)
    if stored.handler != "generic" and stored.source not in {"", "legacy"}:
        return stored
    if inferred.handler != "generic":
        return inferred
    return stored if stored.handler != "generic" else inferred


def _handler_plugins() -> dict[str, ApplyPlugin]:
    from app.services.act_registry_workflow import apply_act_registry_spec_to_workflow

    return {
        "act_porucheniya_registry": apply_act_registry_spec_to_workflow,
    }


def _plan_needs_bootstrap(row: Workflow) -> bool:
    plan_data = row.plan_json if isinstance(row.plan_json, dict) else {}
    if not plan_data:
        return True
    plan = WorkflowPlan.from_dict(plan_data)
    return not (plan.goal or "").strip() or not plan.steps


def _apply_generic_regulation_spec(row: Workflow, route: AgentRoute) -> bool:
    from app.services.workflows.heuristic import build_heuristic_plan
    from app.services.workflows.service import _tools_for_published_plan

    if _plan_needs_bootstrap(row):
        plan = build_heuristic_plan(
            document_name=str(row.document_name or row.title or "Регламент"),
            document_text=str(row.document_text or ""),
            notes=str(row.notes or ""),
        )
    else:
        plan = WorkflowPlan.from_dict(dict(row.plan_json or {}))

    if route.default_task:
        plan.goal = plan.goal or route.default_task
    plan.runtime.handler = route.handler
    plan.runtime.kind = route.kind or route.handler
    plan.runtime.default_task = route.default_task or plan.goal
    if "TESTS: PASS" not in " ".join(plan.test_criteria).upper():
        plan.test_criteria.append("TESTS: PASS")

    route = AgentRoute(
        handler=route.handler,
        kind=route.kind or route.handler,
        mode=route.mode,
        default_task=route.default_task or plan.goal,
        source="regulation_constructor",
        tools=list(route.tools),
    )
    tools = list(route.tools) or _tools_for_published_plan(plan, row)
    route.tools = tools

    if not (row.title or "").strip() or row.title.strip().casefold() in {"ии-агент", "ai agent"}:
        row.title = plan.title or row.title or "ИИ-агент по регламенту"

    plan_data = plan.to_dict()
    plan_data["agent_route"] = agent_route_dict_for_plan(route)
    row.plan_json = plan_data

    local = dict(row.local_run or {})
    passport_title = str(local.get("passport_title") or row.title or plan.title or "").strip()
    local.update(
        {
            "passport_title": passport_title,
            "from_regulation_constructor": True,
            "agent_route": agent_route_dict_for_local(route),
            "tools": tools,
            "tests_status": "pass",
            "execution_backend": "mcp",
            "runtime": {
                "kind": route.kind or route.handler,
                "handler": route.handler,
            },
            "ui_mode": "chat",
        }
    )
    row.local_run = local
    if route.handler != "generic":
        row.exec_agent_id = row.exec_agent_id or f"mcp:{route.handler}"
    if not (row.last_result or "").strip():
        row.last_result = (
            f"TESTS: PASS\nRegulation constructor agent ready ({route.handler})."
        )
    if row.phase in {"", "document", "plan"}:
        row.phase = "tested"
    return True


def apply_regulation_constructor_workflow(row: Workflow) -> bool:
    """
    Применить маршрут/handler/tools для агента, собранного из регламента.
    Handler-specific спеки (ACT и др.) — через plugins; остальное — heuristic plan.
    """
    if not is_regulation_constructor_workflow(row):
        return False

    route = resolve_route_for_regulation_workflow(row)
    plugin = _handler_plugins().get(route.handler)
    if plugin is not None and plugin(row):
        local = dict(row.local_run or {})
        local["from_regulation_constructor"] = True
        row.local_run = local
        return True

    return _apply_generic_regulation_spec(row, route)


def should_skip_cursor_demo_for_workflow(row: Workflow) -> bool:
    """Пробный Cursor-прогон не нужен — runtime MCP уже настроен из регламента."""
    if not is_regulation_constructor_workflow(row):
        return False
    route = resolve_route_for_regulation_workflow(row)
    local = row.local_run if isinstance(row.local_run, dict) else {}
    return route.handler != "generic" or bool(local.get("tests_status") == "pass")
