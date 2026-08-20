"""Единый chat-runtime как в Cursor Composer: регламент + Cursor + constructor_tool."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.services.workflows.service import playbook_of

_CHAT_ESSENTIALS: tuple[str, ...] = (
    "document.write_docx",
    "document.append_docx",
    "files.copy",
    "files.rename",
    "files.inspect",
    "excel.read_workbook",
    "excel.create_workbook",
    "excel.edit_workbook",
    "web_search",
    "site_browser",
    "code.write_python",
    "code.run_python",
)


def resolve_chat_tool_names(workflow: Workflow) -> list[str]:
    """
    Tools для chat-runtime (Composer): полный набор по роли агента,
    без устаревшего урезанного route.tools из старых workflow.
    """
    from app.services.act_registry_workflow import (
        act_registry_tools,
        workflow_looks_like_act_registry,
    )
    from app.services.agent_route import resolve_agent_route
    from app.services.local_mcp import list_tools

    route = resolve_agent_route(workflow)
    if workflow_looks_like_act_registry(workflow) or route.handler == "act_porucheniya_registry":
        return act_registry_tools()

    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    stored = [str(x).strip() for x in (local.get("tools") or []) if str(x).strip()]
    route_tools = [str(x).strip() for x in (route.tools or []) if str(x).strip()]
    merged = list(dict.fromkeys([*route_tools, *stored, *_CHAT_ESSENTIALS]))
    if merged:
        return merged
    return [
        str(item.get("name") or "").strip()
        for item in list_tools()
        if str(item.get("name") or "").strip()
    ]


def _sync_workflow_tools(db: Session, workflow: Workflow, tools: list[str]) -> None:
    """Обновить tools в local_run и plan, чтобы UI и runtime совпадали."""
    local = dict(workflow.local_run or {})
    local["tools"] = tools
    route_local = dict(local.get("agent_route") or {})
    route_local["tools"] = tools
    local["agent_route"] = route_local
    workflow.local_run = local

    plan = dict(workflow.plan_json or {}) if isinstance(workflow.plan_json, dict) else {}
    if plan:
        route_plan = dict(plan.get("agent_route") or {})
        route_plan["tools"] = tools
        plan["agent_route"] = route_plan
        workflow.plan_json = plan
    db.commit()



def resolve_playbook_for_chat(workflow: Workflow) -> dict[str, Any]:
    """Playbook для любого агента: local_run → plan → регламент → эвристика."""
    playbook = playbook_of(workflow)
    if str(playbook.get("instructions") or "").strip():
        return playbook

    from app.services.act_registry_workflow import (
        regulation_playbook_for_workflow,
        workflow_looks_like_act_registry,
    )

    if workflow_looks_like_act_registry(workflow):
        return regulation_playbook_for_workflow(workflow)

    return _generic_playbook_from_workflow(workflow)


def _generic_playbook_from_workflow(workflow: Workflow) -> dict[str, Any]:
    from app.services.workflows import prompts
    from app.services.workflows.plan_models import WorkflowPlan

    doc = str(getattr(workflow, "document_text", "") or "").strip()
    notes = str(getattr(workflow, "notes", "") or "").strip()
    regulation = doc or notes

    plan_data = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    plan = WorkflowPlan.from_dict(plan_data) if plan_data else None

    parts: list[str] = []
    if regulation:
        parts.append(regulation[:12000])
    elif plan and (plan.goal or "").strip():
        parts.append(f"Цель: {plan.goal.strip()}")

    if plan is not None:
        scope = prompts._answered_scope_lines(plan)
        if scope.strip():
            parts.append(f"\nКонтекст из ответов пользователя:\n{scope}")
        if plan.constraints:
            parts.append("\nОграничения:")
            parts.extend(f"- {c}" for c in plan.constraints[:12])
        if plan.steps:
            parts.append("\nШаги:")
            for step in plan.steps[:12]:
                title = str(getattr(step, "title", "") or getattr(step, "action", "") or step)
                parts.append(f"- {title}")

    if not parts:
        title = str(workflow.title or "ИИ-агент").strip()
        parts.append(
            f"Ты агент «{title}». Работаешь как Cursor Composer: понимаешь текущую задачу "
            "и выбираешь tools по смыслу (Word→document.write_docx, Excel→excel.*, "
            "файлы→files.*, ACT→onec+excel). Регламент — экспертиза, не скрипт на каждый запрос."
        )

    example = str(getattr(workflow, "last_result", "") or "").strip()
    if len(example) > 2500:
        example = example[:2500] + "…"

    return {
        "instructions": "\n".join(parts).strip(),
        "example_run": example or "—",
        "name": str(workflow.title or "").strip(),
        "from_regulation": bool(regulation),
    }


def ensure_cursor_chat_runtime(db: Session, workflow: Workflow) -> dict[str, Any]:
    """
    Любой опубликованный агент работает через Cursor + tools (как чат Composer).
    При необходимости мигрирует legacy MCP/hardcoded маршрут.
    """
    from app.services.act_registry_workflow import (
        regulation_playbook_for_workflow,
        workflow_looks_like_act_registry,
    )

    local = dict(workflow.local_run or {})
    changed = False

    backend = str(local.get("execution_backend") or "").casefold()
    legacy_mcp = backend == "mcp" or str(workflow.exec_agent_id or "").startswith("mcp:")
    if backend != "cursor" or legacy_mcp:
        local["execution_backend"] = "cursor"
        changed = True

    if str(workflow.exec_agent_id or "").startswith("mcp:"):
        workflow.exec_agent_id = ""
        changed = True

    playbook = resolve_playbook_for_chat(workflow)
    if workflow_looks_like_act_registry(workflow):
        reg_playbook = regulation_playbook_for_workflow(workflow)
        if reg_playbook.get("instructions"):
            playbook = reg_playbook

    stored = local.get("playbook") if isinstance(local.get("playbook"), dict) else {}
    if playbook.get("instructions") and not stored.get("instructions"):
        local["playbook"] = playbook
        changed = True

    local.setdefault("ui_mode", "chat")

    tools = resolve_chat_tool_names(workflow)
    _sync_workflow_tools(db, workflow, tools)

    if changed:
        workflow.local_run = {**(workflow.local_run or {}), **local}
        db.commit()

    return playbook
