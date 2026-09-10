from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING, Any, Iterable

from app.models.workflow import Workflow

if TYPE_CHECKING:
    from app.services.workflows.plan_models import WorkflowPlan

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

_OUTLOOK_TOOLS = [
    "outlook.read_calendar",
    "outlook.search_mail",
    "outlook.create_event",
    "calendar.show_meetings",
]
_OUTLOOK_MAIL_TOOLS = ["imap.list_unread", "imap.search", "imap.fetch_message"]
_ONEC_TOOLS = [
    "onec.meeting_service_notes",
    "onec.search_documents",
    "onec.get_document_card",
    "onec.erp_assignments",
    "onec.erp_assignments_write",
    "onec.download_artifact",
    "onec.odata_catalog",
    "onec.list_attachments",
    "onec.read_attachment",
    "onec.odata_get",
    "onec.sql_query",
]
_RK_TOOLS = [
    "outlook.read_calendar",
    "calendar.show_meetings",
    "onec.erp_tasks_current",
    "onec.erp_tasks_period",
    "onec.docflow_tasks",
    "onec.meeting_protocols",
    "onec.search_documents",
    "onec.get_document_card",
    "onec.list_attachments",
    "onec.read_attachment",
    "onec.odata_catalog",
    "onec.odata_get",
    "onec.sql_query",
    "excel.list_files",
    "excel.read_workbook",
    "report.build_task_report",
    "report.build_meeting_summary",
    "report.export_document",
    "workspace.powershell_run",
    "users.current",
]
_SD_TOOLS = [
    "outlook.read_calendar",
    "calendar.show_meetings",
    "onec.meeting_service_notes",
    "onec.meeting_protocols",
    "onec.search_documents",
    "onec.get_document_card",
    "onec.list_attachments",
    "onec.read_attachment",
    "onec.odata_catalog",
    "onec.odata_get",
    "onec.sql_query",
    "onec.erp_tasks_current",
    "onec.erp_tasks_period",
    "onec.docflow_tasks",
    "excel.list_files",
    "excel.read_workbook",
    "report.build_meeting_summary",
    "report.export_document",
    "users.current",
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


def _is_board_meeting_blob(blob: str) -> bool:
    from app.services.workflows.sd_meeting_playbook import is_sd_meeting_agent

    return is_sd_meeting_agent(blob)


def _is_revision_commission_blob(blob: str) -> bool:
    from app.services.workflows.rk_meeting_playbook import is_rk_meeting_agent

    return is_rk_meeting_agent(blob)


def infer_kind_from_blob(blob: str) -> str:
    low = blob.casefold()
    if _is_revision_commission_blob(low):
        return "revision_commission"
    if _is_board_meeting_blob(low):
        return "board_meeting"
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
    if kind == "revision_commission":
        return list(_RK_TOOLS)
    if kind == "board_meeting":
        return list(_SD_TOOLS)
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
    "edit": "update",
    "правка": "update",
    "download": "export",
    "report": "export",
    "run": "execute",
    "inspect": "read",
    "review": "read",
    "control": "read",
}

_USER_1C_TASK_HINTS = (
    "задач исполнител",
    "задачи исполнител",
    "мои задач",
    "текущие задач",
    "задачи пользователя",
    "erp_tasks",
    "docflow",
    "документооборот",
    "домашн страниц",
    "начальн страниц",
)
_ASSIGNMENT_STEP_HINTS = (
    "поруч",
    "аст00",
    "аст 00",
    "action tracker",
    "журнал поруч",
)
_TASK_ENTITY_ALIASES = frozenset({"task", "задача", "задачи"})


def wants_user_1c_tasks(blob: str) -> bool:
    """True only for the session user's own executor tasks, not any 'задача'."""
    low = (blob or "").casefold()
    return any(hint in low for hint in _USER_1C_TASK_HINTS)


def _step_blob(step: dict[str, Any]) -> str:
    return " ".join(
        str(step.get(key) or "")
        for key in ("title", "entity", "data_expectation", "done_when", "action")
    ).casefold()


def looks_like_assignment_step(step: dict[str, Any]) -> bool:
    return any(hint in _step_blob(step) for hint in _ASSIGNMENT_STEP_HINTS)


_WRITE_OPS = frozenset({"create", "update"})
_READ_OPS = frozenset({"read", "list", "search", "export", "notify"})
_NON_ONEC_SYSTEMS = frozenset(
    {"excel", "desktop", "outlook", "imap", "web", "constructor", "turboproject"}
)
_WRITE_TEXT_HINTS = (
    "записать в 1",
    "запис в 1",
    "создать поруч",
    "создать документ",
    "новую карточк",
    "новый документ",
    "вернуть исполнител",
    "поменять",
    "сменить",
    "записать коммент",
    "прикрепить",
    "odata_post",
    "odata_patch",
)
_ONEC_WRITE_CONTEXT = (
    "1с",
    "1c",
    "onec",
    "odata",
    "поруч",
    "аст",
    "erp",
    "протокол",
)
_CHANGE_HINTS = (
    ("status", ("статус", "состояни")),
    ("due", ("срок",)),
    ("comment", ("коммент", "вернуть исполнит", "результат выполнения")),
    ("attach", ("прикрепить", "вложен", "приложен")),
    ("create", ("создать", "новая карточ", "новый документ", "новую карточ")),
)
_ODATA_NAME_RE = re.compile(
    r"\b((?:Document|Catalog|Task|BusinessProcess)_[A-Za-zА-Яа-яЁё0-9_]+)"
)
_KNOWN_ODATA_ENTITIES = {
    "assignment": "Document_ТД_Поручения",
    "protocol": "Document_ТД_Протокол",
    "task": "Task_ЗадачаИсполнителя",
}


@dataclass(frozen=True)
class WriteIntent:
    family: str
    entity: str
    operation: str
    change: str
    tool: str
    odata_entity: str = ""
    title: str = ""

    @property
    def key(self) -> str:
        return f"{self.family}:{self.operation}:{self.change}:{self.odata_entity}"

    def to_dict(self) -> dict[str, str]:
        return {
            "family": self.family,
            "entity": self.entity,
            "operation": self.operation,
            "change": self.change,
            "tool": self.tool,
            "odata_entity": self.odata_entity,
            "title": self.title,
            "key": self.key,
        }


def _step_is_onec(step: dict[str, Any]) -> bool:
    system = str(step.get("system") or "").strip().casefold()
    if system in {"onec", "1c", "1с"}:
        return True
    if system in _NON_ONEC_SYSTEMS:
        return False
    candidates = [str(name) for name in (step.get("tool_candidates") or [])]
    if any(name.startswith("onec.") for name in candidates):
        return True
    text = _step_blob(step)
    return any(token in text for token in ("1с", "1c", "odata", "onec"))


def _extract_odata_name(*parts: str) -> str:
    for part in parts:
        match = _ODATA_NAME_RE.search(str(part or ""))
        if match:
            return match.group(1)
    return ""


def _infer_change(step_text: str, operation: str) -> str:
    for change, hints in _CHANGE_HINTS:
        if any(hint in step_text for hint in hints):
            return change
    if operation == "create":
        return "create"
    return "update"


def _intent_family(entity: str, step: dict[str, Any], candidates: Iterable[str]) -> str:
    names = {str(name) for name in candidates}
    step_text = _step_blob(step)
    if "onec.attach_file" in names or entity == "file" or _infer_change(step_text, "") == "attach":
        if entity in {"assignment", "protocol"} or looks_like_assignment_step(step):
            if "прикрепить" in step_text or "файл" in step_text:
                return "file"
        if entity == "file" or "onec.attach_file" in names:
            return "file"
    if entity == "assignment" or looks_like_assignment_step(step):
        return "assignment"
    if entity == "task" or wants_user_1c_tasks(step_text):
        return "task"
    if entity == "protocol" or "протокол" in step_text:
        return "odata"
    return "odata"


def _intent_tool(family: str, operation: str, change: str, candidates: list[str]) -> str:
    from app.services.onec_tools import ONEC_WRITE_TOOLS

    for name in candidates:
        if name in ONEC_WRITE_TOOLS or name.endswith("_write"):
            return name
    if family == "assignment":
        return "onec.erp_assignments_write"
    if family == "file":
        return "onec.attach_file"
    if family == "task":
        return "onec.erp_assignments_write" if change == "comment" else "onec.odata_patch"
    if operation == "create":
        return "onec.odata_post"
    return "onec.odata_patch"


def _odata_entity_for(entity: str, step: dict[str, Any], family: str) -> str:
    named = _extract_odata_name(
        str(step.get("entity") or ""),
        str(step.get("data_expectation") or ""),
        str(step.get("title") or ""),
        " ".join(str(item) for item in (step.get("required_params") or [])),
    )
    if named:
        return named
    if family == "assignment" or entity == "assignment":
        return _KNOWN_ODATA_ENTITIES["assignment"]
    if family == "task" or entity == "task":
        return _KNOWN_ODATA_ENTITIES["task"]
    if entity == "protocol" or "протокол" in _step_blob(step):
        return _KNOWN_ODATA_ENTITIES["protocol"]
    return _KNOWN_ODATA_ENTITIES.get(entity, "")


def _intent_from_step(step: dict[str, Any]) -> WriteIntent | None:
    from app.services.onec_tools import ONEC_WRITE_TOOLS

    if not _step_is_onec(step):
        return None
    operation = normalize_operation(str(step.get("operation") or ""))
    entity = normalize_entity(str(step.get("entity") or ""))
    if entity in _TASK_ENTITY_ALIASES and looks_like_assignment_step(step):
        entity = "assignment"
    candidates = [str(name) for name in (step.get("tool_candidates") or []) if str(name).strip()]
    step_text = _step_blob(step)
    has_write_tool = any(name in ONEC_WRITE_TOOLS or name.endswith("_write") for name in candidates)
    hinted = any(hint in step_text for hint in _WRITE_TEXT_HINTS)
    if operation in _READ_OPS and not has_write_tool:
        return None
    if not has_write_tool and operation not in _WRITE_OPS and not hinted:
        return None
    if not has_write_tool and operation not in _WRITE_OPS and not any(
        token in step_text for token in _ONEC_WRITE_CONTEXT
    ):
        return None
    change = _infer_change(step_text, operation if operation in _WRITE_OPS else "update")
    family = _intent_family(entity, step, candidates)
    if change == "attach":
        family = "file"
    if change == "comment" and family == "assignment":
        family = "task"
    return WriteIntent(
        family=family,
        entity=entity or family,
        operation=operation if operation in _WRITE_OPS else ("create" if change == "create" else "update"),
        change=change,
        tool=_intent_tool(family, operation, change, candidates),
        odata_entity=_odata_entity_for(entity, step, family),
        title=str(step.get("title") or "").strip(),
    )


def collect_write_intents(draft: dict[str, Any], *, blob: str = "") -> list[WriteIntent]:
    """Every 1C mutation the constructor must prove on a throwaway object."""
    found: list[WriteIntent] = []
    seen: set[str] = set()
    for step in draft.get("steps") or []:
        if not isinstance(step, dict):
            continue
        intent = _intent_from_step(step)
        if intent is None or intent.key in seen:
            continue
        seen.add(intent.key)
        found.append(intent)
    if found:
        return found
    text = (blob or "").casefold()
    if not any(hint in text for hint in _WRITE_TEXT_HINTS):
        return []
    if not any(token in text for token in _ONEC_WRITE_CONTEXT):
        return []
    family = "assignment" if any(hint in text for hint in _ASSIGNMENT_STEP_HINTS) else "odata"
    change = _infer_change(text, "update")
    entity = "assignment" if family == "assignment" else "document"
    intent = WriteIntent(
        family=family,
        entity=entity,
        operation="create" if change == "create" else "update",
        change=change,
        tool=_intent_tool(family, "update", change, []),
        odata_entity=_KNOWN_ODATA_ENTITIES.get(entity, ""),
        title="",
    )
    return [intent]


def draft_needs_onec_write(draft: dict[str, Any], *, blob: str = "") -> bool:
    """True when construction must probe a 1C write, for any entity the draft changes."""
    return bool(collect_write_intents(draft, blob=blob))


_ENTITY_ALIASES = {
    "проект": "project",
    "проекты": "project",
    "портфель": "project",
    "portfolio": "project",
    "подчинённый": "subordinate",
    "подчиненный": "subordinate",
    "подчинённые": "subordinate",
    "подчиненные": "subordinate",
    "служебная записка": "service_note",
    "служебные записки": "service_note",
    "сз": "service_note",
    "поручение": "assignment",
    "поручения": "assignment",
    "журнал поручений": "assignment",
    "action tracker": "assignment",
    "аст00": "assignment",
    "аст": "assignment",
    "протокол": "protocol",
    "протоколы": "protocol",
    "задача исполнителя": "task",
    "задачи исполнителя": "task",
    "мои задачи": "task",
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
    if entity in _TASK_ENTITY_ALIASES and looks_like_assignment_step(step):
        entity = "assignment"
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

    names = [str(tool.get("name") or "") for tool in matched if tool.get("name")]
    if entity == "service_note" and "onec.meeting_service_notes" in names:
        names = ["onec.meeting_service_notes"] + [
            name for name in names if name != "onec.meeting_service_notes"
        ]
    if entity == "assignment" and "onec.erp_assignments" in names:
        preferred = ["onec.erp_assignments"]
        if "onec.erp_assignments_write" in names:
            preferred.append("onec.erp_assignments_write")
        names = preferred + [name for name in names if name not in preferred]
    if entity == "protocol" and "onec.meeting_protocols" in names:
        names = ["onec.meeting_protocols"] + [
            name for name in names if name != "onec.meeting_protocols"
        ]
    return names


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

