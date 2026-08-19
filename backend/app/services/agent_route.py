"""Workflow-driven agent routing — single source of truth, idempotent across runs/machines."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.models.workflow import Workflow

# Stable handler ids — API agents set these explicitly on the workflow.
HANDLERS = frozenset(
    {
        "act_porucheniya_registry",
        "assignments_action_tracker",
        "assignments_smart",
        "site_search_excel",
        "outlook_calendar",
        "browser_task",
        "generic",
    }
)

_LEGACY_KIND_TO_HANDLER: dict[str, str] = {
    "act_porucheniya": "act_porucheniya_registry",
    "act_registry": "act_porucheniya_registry",
    "action_tracker": "act_porucheniya_registry",
    "assignments": "act_porucheniya_registry",
    "user_tasks": "act_porucheniya_registry",
    "porucheniya": "act_porucheniya_registry",
    "porucheniya_smart": "act_porucheniya_registry",
    "onec": "act_porucheniya_registry",
    "site_search_excel": "site_search_excel",
    "outlook_calendar": "outlook_calendar",
    "browser_task": "browser_task",
}

_DEPRECATED_ASSIGNMENT_HANDLERS = frozenset(
    {"assignments_action_tracker", "assignments_smart"}
)

_DEFAULT_TASK_BY_HANDLER: dict[str, str] = {
    "act_porucheniya_registry": (
        "Выгрузи реестр поручений ACT (Document_ТД_Поручения) из 1С через OData "
        "и сохрани Excel на рабочий стол с форматированием по каждому ACT00-***"
    ),
    "assignments_action_tracker": (
        "Выгрузи реестр поручений ACT (Document_ТД_Поручения) из 1С через OData "
        "и сохрани Excel на рабочий стол с форматированием по каждому ACT00-***"
    ),
    "assignments_smart": (
        "Выгрузи реестр поручений ACT (Document_ТД_Поручения) из 1С через OData "
        "и сохрани Excel на рабочий стол с форматированием по каждому ACT00-***"
    ),
}


@dataclass
class AgentRoute:
    """Frozen runtime contract for an agent workflow."""

    handler: str = "generic"
    kind: str = ""
    mode: str = ""
    default_task: str = ""
    source: str = ""
    version: int = 1
    tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload.get("tools"):
            payload.pop("tools", None)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AgentRoute | None:
        if not isinstance(data, dict):
            return None
        handler = str(data.get("handler") or "").strip().casefold()
        if not handler:
            return None
        if handler not in HANDLERS:
            handler = _LEGACY_KIND_TO_HANDLER.get(handler, handler)
        handler = _normalize_handler(handler)
        tools_raw = data.get("tools") or []
        tools = [str(x) for x in tools_raw if str(x).strip()] if isinstance(tools_raw, list) else []
        return cls(
            handler=handler if handler in HANDLERS else "generic",
            kind=str(data.get("kind") or handler),
            mode=str(data.get("mode") or "").strip().casefold(),
            default_task=str(data.get("default_task") or "").strip(),
            source=str(data.get("source") or "").strip(),
            version=int(data.get("version") or 1) or 1,
            tools=tools,
        )

    @property
    def agent_kind(self) -> str:
        """Backward-compatible kind for assignments_mode / logging."""
        if self.mode == "smart":
            return "porucheniya_smart"
        mapping = {
            "act_porucheniya_registry": "act_porucheniya",
            "assignments_action_tracker": "porucheniya_smart",
            "assignments_smart": "porucheniya_smart",
        }
        return mapping.get(self.handler, self.kind or self.handler)


def resolve_agent_route(
    workflow: Workflow,
    *,
    override_handler: str = "",
) -> AgentRoute:
    """Resolve route from workflow storage — no task-text heuristics."""
    explicit = (override_handler or "").strip().casefold()
    if explicit:
        mapped = _LEGACY_KIND_TO_HANDLER.get(explicit, explicit)
        mapped = _normalize_handler(mapped)
        if mapped in HANDLERS:
            base = _route_from_storage(workflow) or _infer_legacy_route(workflow)
            return AgentRoute(
                handler=mapped,
                kind=base.kind or mapped,
                mode=_mode_for_handler(mapped, base.mode),
                default_task=base.default_task or _default_task_for_handler(mapped, workflow),
                source="override",
                tools=list(base.tools),
            )

    stored = _route_from_storage(workflow)
    if stored is not None:
        stored.handler = _normalize_handler(stored.handler)
        if not stored.default_task:
            stored.default_task = _default_task_for_handler(stored.handler, workflow)
        return stored

    inferred = _infer_legacy_route(workflow)
    inferred.handler = _normalize_handler(inferred.handler)
    if not inferred.default_task:
        inferred.default_task = _default_task_for_handler(inferred.handler, workflow)
    return inferred


def merge_agent_route(workflow: Workflow, patch: dict[str, Any]) -> AgentRoute:
    """Merge API patch into stored route (for PATCH /agent-route)."""
    current = resolve_agent_route(workflow)
    data = current.to_dict()
    for key, value in (patch or {}).items():
        if key in {"handler", "kind", "mode", "default_task", "source", "version"}:
            data[key] = value
        elif key == "tools" and isinstance(value, list):
            data["tools"] = [str(x) for x in value if str(x).strip()]
    handler = str(data.get("handler") or current.handler).casefold()
    if handler in _LEGACY_KIND_TO_HANDLER:
        handler = _LEGACY_KIND_TO_HANDLER[handler]
    data["handler"] = _normalize_handler(
        handler if handler in HANDLERS else current.handler
    )
    data["source"] = str(patch.get("source") or "api")
    route = AgentRoute.from_dict(data) or current
    if not route.default_task:
        route.default_task = _default_task_for_handler(route.handler, workflow)
    return route


def agent_route_dict_for_plan(route: AgentRoute) -> dict[str, Any]:
    return route.to_dict()


def agent_route_dict_for_local(route: AgentRoute) -> dict[str, Any]:
    payload = route.to_dict()
    payload["source"] = payload.get("source") or "workflow"
    return payload


def _route_from_storage(workflow: Workflow) -> AgentRoute | None:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}

    for bucket, source in (
        (local.get("agent_route"), "local_run"),
        (plan.get("agent_route"), "plan"),
    ):
        route = AgentRoute.from_dict(bucket if isinstance(bucket, dict) else None)
        if route is not None:
            if not route.source:
                route.source = source
            return route

    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    handler_raw = str(runtime.get("handler") or runtime.get("kind") or "").casefold()
    if handler_raw:
        handler = _LEGACY_KIND_TO_HANDLER.get(handler_raw, handler_raw)
        if handler in HANDLERS:
            return AgentRoute(
                handler=handler,
                kind=handler_raw,
                mode=str(runtime.get("mode") or "").casefold(),
                default_task=str(runtime.get("default_task") or plan.get("goal") or "").strip(),
                source="plan.runtime",
            )
    return None


def _infer_legacy_route(workflow: Workflow) -> AgentRoute:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    goal = str(plan.get("goal") or "").strip()

    kind = _legacy_runtime_kind(workflow)
    handler = _LEGACY_KIND_TO_HANDLER.get(kind, "")
    if not handler and kind in HANDLERS:
        handler = kind
    if not handler:
        handler = _infer_handler_from_plan_blob(workflow) or "generic"

    return AgentRoute(
        handler=handler,
        kind=kind or handler,
        mode=_mode_for_handler(handler, ""),
        default_task=goal or _default_task_for_handler(handler, workflow),
        source="legacy",
    )


def _legacy_runtime_kind(workflow: Workflow) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    title_blob = str(workflow.title or "").casefold()
    if "porucheniya_smart" in title_blob or (
        "porucheniya" in title_blob and "smart" in title_blob
    ):
        return "porucheniya_smart"
    rt_plan = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    rt_local = local.get("runtime") if isinstance(local.get("runtime"), dict) else {}
    kind = str(rt_plan.get("kind") or rt_local.get("kind") or "").strip().casefold()
    if kind:
        return kind
    seed = str(local.get("seed") or "").strip().casefold()
    if seed in _LEGACY_KIND_TO_HANDLER:
        if seed in {"porucheniya", "action_tracker"} and "smart" in title_blob:
            return "porucheniya_smart"
        return seed
    if seed in {"porucheniya", "action_tracker"}:
        if "smart" in title_blob:
            return "porucheniya_smart"
        return "action_tracker"
    return ""


def _infer_handler_from_plan_blob(workflow: Workflow) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    blob = " ".join(
        [
            str(workflow.title or ""),
            str(getattr(workflow, "notes", "") or ""),
            str(getattr(workflow, "document_name", "") or ""),
            str(getattr(workflow, "document_text", "") or "")[:8000],
            str(plan.get("title") or ""),
            str(plan.get("goal") or ""),
            str(local.get("passport_title") or ""),
            " ".join(str(x) for x in (plan.get("constraints") or [])),
        ]
    ).casefold()
    if any(h in blob for h in ("outlook", "календар", "совещан", "встреч", "exchange")):
        if not any(h in blob for h in ("act00", "document_тд_поруч", "реестр act")):
            return "outlook_calendar"
    if any(h in blob for h in ("site_browser", "site_search", "этп", "ключевые слова", "тендер")):
        if "excel" in blob or "xlsx" in blob:
            return "site_search_excel"
    if any(h in blob for h in ("http://", "https://", "браузер", "сайт")):
        return "browser_task"
    if any(h in blob for h in ("act00", "аст00", "реестр поручений", "document_тд_поруч")):
        return "act_porucheniya_registry"
    if "porucheniya_smart" in blob or (
        "porucheniya" in blob and "smart" in blob and "action tracker" not in blob
    ):
        return "act_porucheniya_registry"
    if "smart" in blob and "формулиров" in blob:
        return "act_porucheniya_registry"
    if any(h in blob for h in ("action tracker", "decision log", "отслеж", "артефакт")):
        return "act_porucheniya_registry"
    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    rk = str(runtime.get("kind") or "").casefold()
    if rk in _LEGACY_KIND_TO_HANDLER:
        return _LEGACY_KIND_TO_HANDLER[rk]
    if rk == "site_search_excel":
        return "site_search_excel"
    if rk == "outlook_calendar":
        return "outlook_calendar"
    if rk == "browser_task":
        return "browser_task"
    if any(h in blob for h in ("поручен", "1с", "onec")):
        return "act_porucheniya_registry"
    return "generic"


def _normalize_handler(handler: str) -> str:
    h = (handler or "").strip().casefold()
    if h in _DEPRECATED_ASSIGNMENT_HANDLERS:
        return "act_porucheniya_registry"
    if h in _LEGACY_KIND_TO_HANDLER:
        return _LEGACY_KIND_TO_HANDLER[h]
    return h


def _mode_for_handler(handler: str, mode: str) -> str:
    handler = _normalize_handler(handler)
    if handler == "act_porucheniya_registry":
        return ""
    return mode


def _default_task_for_handler(handler: str, workflow: Workflow) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    goal = str(plan.get("goal") or "").strip()
    if goal:
        return goal
    return _DEFAULT_TASK_BY_HANDLER.get(handler, goal)


def build_route_from_passport(
    *,
    passport_title: str = "",
    notes: str = "",
    goal: str = "",
    document_text: str = "",
    document_name: str = "",
) -> AgentRoute:
    """One-time route inference when passport is saved — stored on workflow, not re-run at launch."""
    wf = Workflow(
        id="draft",
        title=passport_title,
        notes=notes,
        document_name=document_name,
        document_text=document_text,
        plan_json={"goal": goal, "title": passport_title},
        local_run={"passport_title": passport_title},
    )
    route = _infer_legacy_route(wf)
    route.source = "passport"
    if goal.strip():
        route.default_task = goal.strip()
    return route


def resolve_agent_tool_names(workflow: Workflow) -> list[str]:
    """Enabled tools for an agent: route → local_run → handler defaults → full catalog."""
    route = resolve_agent_route(workflow)
    if route.tools:
        return list(route.tools)
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    stored = local.get("tools")
    if isinstance(stored, list):
        names = [str(x).strip() for x in stored if str(x).strip()]
        if names:
            return names
    if route.handler == "act_porucheniya_registry":
        from app.services.act_registry_workflow import act_registry_tools

        return act_registry_tools()
    from app.services.local_mcp import list_tools

    return [str(item.get("name") or "").strip() for item in list_tools() if str(item.get("name") or "").strip()]


def execution_backend(local_run: dict[str, Any] | None) -> str:
    """MCP vs legacy execution flag — separate from agent routing."""
    local = local_run if isinstance(local_run, dict) else {}
    backend = str(local.get("execution_backend") or "").strip()
    if backend:
        return backend
    runtime = local.get("runtime")
    if isinstance(runtime, str) and runtime.casefold() == "mcp":
        return "mcp"
    return ""
