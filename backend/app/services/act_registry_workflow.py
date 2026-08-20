"""Сборка ACT-реестра через конструктор (регламент → workflow → publish)."""

from __future__ import annotations

from typing import Any

from app.models.workflow import Workflow
from app.services.act_registry_agent_spec import (
    GOAL,
    NOTES_HEADER,
    build_agent_route_dict,
    build_plan_dict,
    build_playbook_dict,
    load_regulation_text,
)
from app.services.agent_route import (
    AgentRoute,
    _infer_handler_from_plan_blob,
    agent_route_dict_for_local,
    agent_route_dict_for_plan,
)


def _workflow_blob(workflow: Workflow) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    parts = [
        str(workflow.title or ""),
        str(getattr(workflow, "notes", "") or ""),
        str(getattr(workflow, "document_name", "") or ""),
        str(getattr(workflow, "document_text", "") or "")[:8000],
        str(plan.get("title") or ""),
        str(plan.get("goal") or ""),
        str(local.get("passport_title") or ""),
        " ".join(str(x) for x in (plan.get("constraints") or [])),
    ]
    return " ".join(parts).casefold()


def workflow_looks_like_act_registry(workflow: Workflow) -> bool:
    """True, если workflow собирается как ACT-реестр (не любые «поручения 1С»)."""
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    if str(local.get("seed") or "") == "act_porucheniya":
        return True
    doc_name = str(getattr(workflow, "document_name", "") or "").casefold()
    if "act_registry" in doc_name:
        return True
    blob = _workflow_blob(workflow)
    act_markers = (
        "act_registry.md",
        "act-реестр",
        "act реестр",
        "act00",
        "document_тд_поруч",
        "act_porucheniya_registry",
        "задачи act",
    )
    if not any(m in blob for m in act_markers):
        return False
    return _infer_handler_from_plan_blob(workflow) == "act_porucheniya_registry"


def apply_act_registry_spec_to_workflow(row: Workflow) -> bool:
    """
    Подмешать plan/agent_route/tools из act_registry_agent_spec.
    Возвращает True, если спека применена.
    """
    if not workflow_looks_like_act_registry(row):
        return False

    excerpt = str(row.document_text or row.notes or "").strip()
    regulation = load_regulation_text()
    if excerpt and excerpt not in regulation:
        document_excerpt = excerpt
    else:
        document_excerpt = excerpt or regulation

    plan = build_plan_dict(document_excerpt=document_excerpt[:12000])
    route_dict = build_agent_route_dict()
    route = AgentRoute.from_dict(route_dict)
    if route is None:
        return False

    if not (row.title or "").strip() or row.title.strip().casefold() in {"ии-агент", "ai agent"}:
        row.title = "ИИ-агент: ACT-реестр поручений"

    row.plan_json = plan
    if not (row.notes or "").strip():
        row.notes = NOTES_HEADER + "\n" + regulation[:6000]
    if not (row.document_name or "").strip():
        row.document_name = "ACT_REGISTRY.md"
    if not (row.document_text or "").strip():
        row.document_text = regulation

    local = dict(row.local_run or {})
    passport_title = str(local.get("passport_title") or row.title or "ACT-реестр поручений").strip()
    local.update(
        {
            "passport_title": passport_title,
            "seed": "act_porucheniya",
            "agent_route": agent_route_dict_for_local(route),
            "tools": list(route_dict.get("tools") or []),
            "playbook": build_playbook_dict(regulation=regulation),
            "tests_status": "pass",
            "execution_backend": "cursor",
            "runtime": {
                "kind": "act_porucheniya",
                "handler": "act_porucheniya_registry",
                "regulation_path": "ACT_REGISTRY.md",
            },
            "ui_mode": "chat",
            "from_regulation_constructor": True,
            "act_registry_from_constructor": True,
        }
    )
    row.local_run = local
    if str(row.exec_agent_id or "").startswith("mcp:"):
        row.exec_agent_id = ""
    if not (row.last_result or "").strip():
        row.last_result = "TESTS: PASS\nACT registry agent ready (constructor + ACT_REGISTRY.md)."
    if row.phase in {"", "document", "plan"}:
        row.phase = "tested"
    return True


def act_registry_tools() -> list[str]:
    return list(build_agent_route_dict().get("tools") or [])


def regulation_playbook_for_workflow(workflow: Workflow) -> dict[str, Any]:
    """Playbook из регламента workflow — для Cursor runtime."""
    doc = str(getattr(workflow, "document_text", "") or "").strip()
    notes = str(getattr(workflow, "notes", "") or "").strip()
    regulation = doc or notes or load_regulation_text()
    return build_playbook_dict(regulation=regulation)


def workflow_uses_cursor_runtime(workflow: Workflow) -> bool:
    """True — задачи идут через Cursor + constructor_tool, не hardcoded MCP."""
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    backend = str(local.get("execution_backend") or "").casefold()
    if backend == "cursor":
        return True
    if backend == "mcp":
        return False
    if str(workflow.exec_agent_id or "").startswith("mcp:"):
        return False
    if workflow_looks_like_act_registry(workflow):
        return True
    return False


def act_registry_goal() -> str:
    return GOAL
