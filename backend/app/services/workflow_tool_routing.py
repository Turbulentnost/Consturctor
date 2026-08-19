from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING, Any

from app.models.workflow import Workflow

if TYPE_CHECKING:
    from app.services.workflows.plan_models import WorkflowPlan

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

_OUTLOOK_TOOLS = ["outlook.read_calendar", "outlook.search_mail"]
_OUTLOOK_MAIL_TOOLS = ["imap.list_unread", "imap.search", "imap.fetch_message"]
_ONEC_TOOLS = [
    "onec.search_documents",
    "onec.get_document_card",
    "onec.odata_get",
    "onec.sql_query",
]
_SITE_SEARCH_TOOLS = ["site_browser", "web_search"]
_BROWSER_TOOLS = ["site_browser", "web_search"]


@dataclass
class WorkflowRouting:
    kind: str = ""
    tools: list[str] = field(default_factory=list)
    source: str = ""


def plan_blob(plan: "WorkflowPlan", workflow: Workflow | None = None) -> str:
    parts = [
        plan.title,
        plan.goal,
        "\n".join(plan.constraints),
        "\n".join(plan.test_criteria),
        "\n".join(plan.out_of_scope),
    ]
    for s in plan.steps:
        parts.append(f"{s.title}\n{s.action}\n{s.done_when}")
    for q in plan.open_questions:
        parts.append(f"{q.question}\n{q.answer}")
    for q in plan.answered_questions:
        parts.append(f"{q.question}\n{q.answer}")
    if workflow is not None:
        parts.extend(
            [
                str(workflow.title or ""),
                str(workflow.notes or ""),
                str(workflow.document_name or ""),
                str(workflow.document_text or ""),
            ]
        )
    return "\n".join(part for part in parts if part)


def extract_url(text: str) -> str:
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(").,;") if m else ""


def expand_keyword_text(block: str) -> list[str]:
    """Split keyword block into queries without market-specific dictionaries."""
    block = (block or "").strip()
    if not block:
        return []
    if ";" in block:
        raw_parts = [p.strip() for p in block.split(";") if p.strip()]
    else:
        raw_parts = [p.strip() for p in re.split(r"[\n]+", block) if p.strip()]

    out: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        pieces = [part] if ";" in block else [c.strip() for c in re.split(r"[,/]", part) if c.strip()]
        if not pieces:
            pieces = [part]
        for q in pieces:
            q = q.strip()
            if not q:
                continue
            key = q.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(q)
    return out


def extract_columns(blob: str) -> list[str]:
    low = blob.casefold()
    m = re.search(
        r"колонк[аи]\s*(?:excel[^:]*|выгрузки)?\s*[:—-]\s*([^\n.]+)",
        low,
        flags=re.IGNORECASE,
    )
    found: list[str] = []
    if m:
        raw = m.group(1)
        found = [p.strip(" «»\"'") for p in re.split(r"[,;/]| и ", raw) if p.strip(" «»\"'")]
    defaults = []
    for name in ("название", "цена", "дата", "ссылка", "ключевые слова"):
        if name in low:
            defaults.append(name)
    cols = found or defaults or ["название", "цена", "дата"]
    for extra in ("ссылка", "ключевые слова"):
        if extra in low and extra not in cols:
            cols.append(extra)
    nice = []
    for c in cols:
        c = c.strip().casefold()
        if not c:
            continue
        if c not in nice:
            nice.append(c)
    return nice


def normalize_tools(tools: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tool in tools or []:
        item = str(tool or "").strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def infer_kind_from_tools(tools: list[str]) -> str:
    toolset = {tool.casefold() for tool in tools}
    has_onec = any(tool.startswith("onec.") for tool in toolset)
    has_outlook = any(tool.startswith("imap.") or tool.startswith("outlook.") for tool in toolset)
    if has_onec and has_outlook:
        return "hybrid"
    if has_onec:
        return "onec"
    if has_outlook:
        return "outlook_calendar"
    if "site_browser" in toolset or "web_search" in toolset:
        return "browser_task"
    return ""


def infer_kind_from_blob(blob: str) -> str:
    low = blob.casefold()
    has_onec = any(tip in low for tip in ("1с", "1c", "onec", "odata"))
    has_outlook = any(
        tip in low
        for tip in (
            "outlook",
            "календар",
            "совещан",
            "встреч",
            "занятост",
            "confirm_slot",
            "win32com",
            "outlook.application",
        )
    )
    if has_onec and has_outlook:
        return "hybrid"
    if has_onec:
        return "onec"
    if has_outlook:
        return "outlook_calendar"
    if ("excel" in low or "xlsx" in low or "выгрузк" in low) and (
        "ключев" in low or "этп" in low or "сайт" in low
    ):
        return "site_search_excel"
    if _extract_site_url_from_blob(low) or "брауз" in low or "browser" in low:
        return "browser_task"
    return ""


def _extract_site_url_from_blob(blob: str) -> str:
    return extract_url(blob)


def default_tools_for_kind(kind: str, *, blob: str = "") -> list[str]:
    low = blob.casefold()
    if kind == "onec":
        return list(_ONEC_TOOLS)
    if kind == "outlook_calendar":
        tools = list(_OUTLOOK_TOOLS)
        if any(tip in low for tip in ("почт", "письм", "imap", "email", "mail")):
            tools.extend(_OUTLOOK_MAIL_TOOLS)
        return normalize_tools(tools)
    if kind == "site_search_excel":
        return list(_SITE_SEARCH_TOOLS)
    if kind == "browser_task":
        return list(_BROWSER_TOOLS)
    return []


def resolve_workflow_routing(plan: "WorkflowPlan", workflow: Workflow | None = None) -> WorkflowRouting:
    blob = plan_blob(plan, workflow)
    rt = getattr(plan, "runtime", None)
    if rt is None:
        rt = type("Runtime", (), {"kind": "", "tools": []})()
    phases = list(getattr(rt, "phases", []) or [])
    explicit_kind = str(rt.kind or "").strip().casefold()
    explicit_tools = normalize_tools(rt.tools)
    phase_tools = normalize_tools([tool for phase in phases for tool in getattr(phase, "tools", []) or []])
    if phases:
        kind = "hybrid"
        tools = normalize_tools(explicit_tools + phase_tools) or phase_tools or explicit_tools
        source = "runtime"
        if not tools:
            tools = phase_tools
        return WorkflowRouting(kind=kind, tools=tools, source=source)

    kind = explicit_kind or infer_kind_from_tools(explicit_tools) or infer_kind_from_blob(blob)

    tools = explicit_tools or default_tools_for_kind(kind, blob=blob)
    if not kind and tools:
        kind = infer_kind_from_tools(tools)

    source = "runtime" if explicit_kind or explicit_tools else ""
    if not source and kind:
        source = "inferred"
    return WorkflowRouting(kind=kind, tools=tools, source=source)


_WEB_TOOL_PREFIXES = ("web_search", "site_browser", "browser.")
_WEB_ALLOWED_HINTS = (
    "сайт",
    "интернет",
    "веб",
    "web",
    "http://",
    "https://",
    "этп",
    "площадк",
    "поисковик",
)


def regulation_allows_web(blob: str) -> bool:
    """Веб-инструменты нужны, только если регламент прямо про сайт/интернет."""
    low = (blob or "").casefold()
    return any(hint in low for hint in _WEB_ALLOWED_HINTS)


def _is_web_tool(name: str) -> bool:
    low = (name or "").strip().casefold()
    return any(low == prefix or low.startswith(prefix) for prefix in _WEB_TOOL_PREFIXES)


_OPERATION_SYNONYMS = {
    "fetch": "read",
    "get": "read",
    "load": "read",
    "find": "search",
    "query": "search",
    "enumerate": "list",
    "send": "notify",
    "write": "create",
    "save": "create",
    "post": "create",
    "modify": "update",
    "patch": "update",
    "download": "export",
    "report": "export",
    "run": "execute",
    "inspect": "read",
    "review": "read",
    "control": "read",
}

_ENTITY_ALIASES = {
    "проект": "project",
    "проекты": "project",
    "портфель": "project",
    "portfolio": "project",
    "подчинённый": "subordinate",
    "подчиненный": "subordinate",
    "подчинённые": "subordinate",
    "подчиненные": "subordinate",
}

_PROJECT_OPERATIONS = frozenset({"", "search", "read", "list"})


def normalize_operation(operation: str) -> str:
    low = (operation or "").strip().casefold()
    return _OPERATION_SYNONYMS.get(low, low)


def normalize_entity(entity: str) -> str:
    low = (entity or "").strip().casefold()
    return _ENTITY_ALIASES.get(low, low)


def select_candidates(
    step: dict[str, Any],
    *,
    next_step: dict[str, Any] | None = None,
    allow_web: bool = False,
) -> list[str]:
    """Инструменты, совместимые с шагом черновика: система, сущность, операция, фильтры."""
    from app.services.local_mcp import candidates_for, contract_vocabulary

    system = str(step.get("system") or "").strip().casefold()
    operation = normalize_operation(str(step.get("operation") or ""))
    entity = normalize_entity(str(step.get("entity") or ""))
    matched = candidates_for(
        system=system,
        entity=entity,
        operation=operation,
    )
    if entity == "project" and operation in _PROJECT_OPERATIONS:
        for tool in candidates_for(
            system="turboproject",
            entity="project",
            operation=operation or "search",
        ):
            if tool not in matched and str(tool.get("name") or "") not in {
                str(item.get("name") or "") for item in matched
            }:
                matched.append(tool)
    if not matched:
        known_entities = {str(item).casefold() for item in contract_vocabulary()["entities"]}
        # Известная сущность не подменяем чужой (project → карточки 1С).
        if entity and entity in known_entities:
            matched = []
        else:
            matched = candidates_for(system=system, operation=operation)

    if system and system != "web" and not allow_web:
        matched = [tool for tool in matched if not _is_web_tool(str(tool.get("name") or ""))]

    known_params = {
        str(param).strip().casefold()
        for param in (step.get("required_params") or [])
        if str(param).strip()
    }
    covered = [
        tool
        for tool in matched
        if not known_params
        or all(
            str(flt).strip().casefold() in known_params
            for flt in (tool.get("required_filters") or [])
        )
    ]
    if covered:
        matched = covered

    if next_step:
        needs = {
            str(param).strip().casefold()
            for param in (next_step.get("required_params") or [])
            if str(param).strip()
        }
        if needs:
            useful = [tool for tool in matched if tool.get("result_fields")]
            if useful:
                matched = useful

    return [str(tool.get("name") or "") for tool in matched if tool.get("name")]


def apply_routing_to_runtime(plan: "WorkflowPlan", workflow: Workflow | None = None) -> "WorkflowPlan":
    route = resolve_workflow_routing(plan, workflow)
    rt = plan.runtime
    if route.kind:
        rt.kind = route.kind
    if not rt.tools and route.tools:
        rt.tools = list(route.tools)
    else:
        rt.tools = normalize_tools(rt.tools)
    return plan

