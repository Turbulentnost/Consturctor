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
    if any(tool.startswith("onec.") for tool in toolset):
        return "onec"
    if any(tool.startswith("imap.") or tool.startswith("outlook.") for tool in toolset):
        return "outlook_calendar"
    if "site_browser" in toolset or "web_search" in toolset:
        return "browser_task"
    return ""


def infer_kind_from_blob(blob: str) -> str:
    low = blob.casefold()
    if any(tip in low for tip in ("1с", "1c", "onec", "odata")):
        return "onec"
    if any(
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
    ):
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
    explicit_kind = str(rt.kind or "").strip().casefold()
    explicit_tools = normalize_tools(rt.tools)
    kind = explicit_kind or infer_kind_from_tools(explicit_tools) or infer_kind_from_blob(blob)

    tools = explicit_tools or default_tools_for_kind(kind, blob=blob)
    if not kind and tools:
        kind = infer_kind_from_tools(tools)

    source = "runtime" if explicit_kind or explicit_tools else ""
    if not source and kind:
        source = "inferred"
    return WorkflowRouting(kind=kind, tools=tools, source=source)


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

