from __future__ import annotations

import codecs
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections.abc import Callable
from threading import Thread
from urllib.parse import quote

import httpx

from app.config import backend_url


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class UserProfile:
    id: str
    fio: str
    department: str = ""
    position: str = ""
    avatar_url: str | None = None
    can_change_department: bool = True
    department_change_available_at: datetime | None = None
    activity_status: str = "online"
    is_support: bool = False


@dataclass(frozen=True, slots=True)
class HealthStatus:
    status: str
    erp_reachable: bool
    erp_server: str
    llm_provider: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    access_token: str
    user: UserProfile


@dataclass(frozen=True, slots=True)
class RegulationTable:
    headers: list[str]
    rows: list[list[str]]


@dataclass(frozen=True, slots=True)
class RegulationFragment:
    fragment_id: str
    page: int
    section: str
    kind: str
    text: str
    table: RegulationTable | None
    ocr_confidence: float
    section_path: list[str] | None = None
    block_type: str = "paragraph"
    table_headers: list[str] | None = None
    cells: dict[str, str] | None = None
    row_index: int | None = None
    bbox: list[float] | None = None
    location: dict | None = None
    style: str = ""
    content_hash: str = ""


@dataclass(frozen=True, slots=True)
class RegulationParseResult:
    regulation_id: str
    file_name: str
    page_count: int
    table_count: int
    section_count: int
    recognition_quality: float
    is_scan: bool
    sections: list[str]
    fragments: list[RegulationFragment]


@dataclass(frozen=True, slots=True)
class MatchSignal:
    match_type: str
    confidence: float
    quote: str
    explanation: str


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    fragment_id: str
    quote: str


@dataclass(frozen=True, slots=True)
class ContextLinkedBlock:
    block_id: str
    relation: str
    text: str
    evidence: str
    confidence: float


@dataclass(frozen=True, slots=True)
class FunctionActor:
    text: str
    canonical_position: str
    source_block_id: str


@dataclass(frozen=True, slots=True)
class FunctionDependency:
    type: str
    block_id: str
    description: str


@dataclass(frozen=True, slots=True)
class RoleFunction:
    function_id: str
    target_block_id: str
    is_function: bool
    title: str
    actor: FunctionActor
    action: str
    object: str
    recipient: str
    conditions: list[str]
    dependencies: list[FunctionDependency]
    evidence: list[MatchEvidence]
    proof_chain: list[ContextLinkedBlock]
    explanation: str
    confidence: float
    duplicate_group: str
    requires_confirmation: bool


@dataclass(frozen=True, slots=True)
class RoleMatch:
    match_id: str
    fragment_id: str
    relation: str
    match_types: list[str]
    confidence: float
    model_confidence: float
    explanation: str
    requires_confirmation: bool
    status: str
    fragment: RegulationFragment
    signals: list[MatchSignal]
    function: RoleFunction | None = None


@dataclass(frozen=True, slots=True)
class RoleMatchResult:
    run_id: str
    regulation_id: str
    canonical_title: str
    department: str
    matches: list[RoleMatch]
    functions: list[RoleFunction] | None = None
    audit: dict | None = None


@dataclass(frozen=True, slots=True)
class ReadinessQuestion:
    question_id: str
    function_id: str
    target_field: str
    severity: str
    question: str
    reason: str
    answer_type: str
    options: list[str]
    affected_blocks: list[str]
    answered: bool = False
    answer: str = ""


@dataclass(frozen=True, slots=True)
class ReadinessChange:
    change_id: str
    source: dict
    operation: str
    target_block_id: str
    before: str
    after: str
    reason: str
    affected_functions: list[str]
    affected_blocks: list[str]
    status: str


@dataclass(frozen=True, slots=True)
class AgentReadinessResult:
    readiness_run_id: str
    regulation_id: str
    role_match_run_id: str
    score: int
    blocking: list[str]
    important: list[str]
    optional: list[str]
    questions: list[ReadinessQuestion]
    changes: list[ReadinessChange]
    status: str


@dataclass(frozen=True, slots=True)
class RevisionDiffBlock:
    block_id: str
    section: str
    before: str
    after: str
    page: int
    bbox: list[float] | None
    status: str


@dataclass(frozen=True, slots=True)
class RevisionPreviewPage:
    page: int
    image_url: str


@dataclass(frozen=True, slots=True)
class RegulationRevisionResult:
    revision_id: str
    regulation_id: str
    readiness_run_id: str
    document_path: str
    protocol_path: str
    pdf_path: str
    source_preview_html: str
    revised_preview_html: str
    source_preview_pages: list[RevisionPreviewPage]
    revised_preview_pages: list[RevisionPreviewPage]
    diff_blocks: list[RevisionDiffBlock]
    download_url: str
    pdf_download_url: str
    protocol_url: str
    message: str


@dataclass(frozen=True, slots=True)
class AgentDraft:
    draft_id: str
    regulation_id: str
    role_match_run_id: str
    readiness_run_id: str
    title: str
    position: str
    department: str
    status: str
    progress: int
    readiness: AgentReadinessResult | None = None
    agent_suggestions: list[AgentSuggestion] | None = None
    updated_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AgentSuggestion:
    agent_id: str
    title: str
    description: str
    regulation_id: str
    role_match_run_id: str
    function_id: str
    source_block_id: str


@dataclass(frozen=True, slots=True)
class PassportFunction:
    name: str
    description: str
    action_level: str = "read"
    requires_human_approval: bool = False
    automation_kind: str = "auto"


@dataclass
class AgentPassport:
    name: str = ""
    goal: str = ""
    trigger: str = ""
    receives: str = ""
    checks: str = ""
    decisions: str = ""
    can_autonomous: str = ""
    needs_human_approval: str = ""
    forbidden: str = ""
    result: str = ""
    missing_fields: list[str] | None = None
    questions: list[dict] | None = None
    source: str = "heuristic"
    text: str = ""
    autonomy_level: int = 1
    cursor_agent_id: str = ""

    def to_api_dict(self) -> dict:
        return {
            "name": self.name,
            "goal": self.goal,
            "trigger": self.trigger,
            "receives": self.receives,
            "checks": self.checks,
            "decisions": self.decisions,
            "can_autonomous": self.can_autonomous,
            "needs_human_approval": self.needs_human_approval,
            "forbidden": self.forbidden,
            "result": self.result,
            "missing_fields": list(self.missing_fields or []),
            "questions": list(self.questions or []),
            "source": self.source,
            "text": self.text,
            "autonomy_level": int(self.autonomy_level or 1),
            "cursor_agent_id": self.cursor_agent_id,
        }


@dataclass(frozen=True, slots=True)
class PassportSession:
    passport: AgentPassport
    bp_name: str
    excerpt: str
    functions: list[PassportFunction]
    draft_id: str = ""
    reused: bool = False
    llm_error: str = ""
    qa_history: list[tuple[str, str, list[str]]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RegulationCreationMessage:
    message_id: str
    draft_id: str
    role: str
    content: str
    structured: dict


@dataclass(frozen=True, slots=True)
class RegulationCreationSession:
    draft_id: str
    status: str
    cursor_agent_id: str
    latest_run_id: str
    positions: list[str]
    messages: list[RegulationCreationMessage]
    result_regulation: RegulationParseResult | None
    result_document: dict
    result_document_path: str


@dataclass(frozen=True, slots=True)
class QuestionChatMessage:
    message_id: str
    session_id: str
    role: str
    content: str
    structured: dict


@dataclass(frozen=True, slots=True)
class WorkflowPlanStep:
    id: str
    title: str
    action: str
    done_when: str = ""
    depends_on: list[str] | None = None


@dataclass(frozen=True, slots=True)
class WorkflowOpenQuestion:
    id: str
    question: str
    why: str = ""
    answer: str = ""
    options: list[str] | None = None


@dataclass(frozen=True, slots=True)
class WorkflowPlan:
    title: str = ""
    goal: str = ""
    constraints: list[str] | None = None
    out_of_scope: list[str] | None = None
    steps: list[WorkflowPlanStep] | None = None
    test_criteria: list[str] | None = None
    open_questions: list[WorkflowOpenQuestion] | None = None
    raw_text: str = ""

    def unanswered(self) -> list[WorkflowOpenQuestion]:
        return [q for q in (self.open_questions or []) if not (q.answer or "").strip()]


@dataclass(frozen=True, slots=True)
class WorkflowAttachment:
    name: str
    kind: str = "text"
    mime_type: str = ""
    stored_name: str = ""
    text_preview: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowFileItem:
    id: str
    workflow_id: str = ""
    run_id: str = ""
    source: str = "user"
    scope: str = "knowledge"
    origin: str = ""
    filename: str = ""
    mime_type: str = ""
    kind: str = "text"
    size: int = 0
    sha256: str = ""
    summary: str = ""
    text_preview: str = ""
    created_at: str = ""
    updated_at: str = ""
    agent_title: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowFiles:
    user_files: list[WorkflowFileItem] = field(default_factory=list)
    agent_files: list[WorkflowFileItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WorkflowRecord:
    id: str
    title: str
    phase: str
    notes: str = ""
    document_name: str = ""
    document_text: str = ""
    plan: WorkflowPlan | None = None
    attachments: list[WorkflowAttachment] | None = None
    local_run: dict | None = None
    plan_agent_id: str = ""
    plan_run_id: str = ""
    exec_agent_id: str = ""
    exec_run_id: str = ""
    last_result: str = ""
    branch: str = ""
    pr_url: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def name(self) -> str:
        return self.title


@dataclass(frozen=True, slots=True)
class AgentRunHistoryItem:
    id: str
    workflow_id: str
    message: str = ""
    status: str = ""
    answer: str = ""
    source: str = "chat"
    trigger_id: str = ""
    trigger_kind: str = ""
    trigger_reason: str = ""
    started_at: str = ""
    finished_at: str = ""
    events: list[dict] = field(default_factory=list)


@dataclass
class ScheduleTriggerSpec:
    kind: str = "event"
    message: str = ""
    interval_value: float = 0
    interval_unit: str = "hours"
    condition: str = ""
    at: str = ""
    once: bool = True


@dataclass
class ScheduleDraft:
    name: str = ""
    goal: str = ""
    triggers: list[ScheduleTriggerSpec] = field(default_factory=list)


@dataclass
class InboxNotification:
    id: str
    title: str
    body: str = ""
    workflow_id: str = ""
    run_id: str = ""
    sender_fio: str = ""
    unread: bool = True
    created_at: str = ""
    send_at: str = ""
    agent_deleted: bool = False


@dataclass
class KpiSide:
    label: str = ""
    value: float | None = None
    unit: str = ""
    description: str = ""


@dataclass
class KpiMeasure:
    kind: str = ""
    params: dict = field(default_factory=dict)
    formula: str = ""


@dataclass
class KpiSchedule:
    kind: str = "interval"
    interval_seconds: int = 3600
    at: str = ""


@dataclass
class KpiMethod:
    how: str = ""
    when: str = ""
    plan_update: str = ""
    fact_update: str = ""
    percent_formula: str = ""
    plan_explanation: str = ""
    fact_explanation: str = ""
    score_explanation: str = ""
    system: str = ""
    green_min: float = 90
    yellow_min: float = 70
    schedule: KpiSchedule = field(default_factory=KpiSchedule)


@dataclass
class KpiTile:
    id: str = ""
    name: str = ""
    plan: KpiSide = field(default_factory=KpiSide)
    fact: KpiSide = field(default_factory=KpiSide)
    measure: KpiMeasure = field(default_factory=KpiMeasure)
    score_percent: float | None = None
    color: str = "none"
    updated_at: str = ""
    next_run_at: str = ""
    evidence: str = ""
    method: KpiMethod = field(default_factory=KpiMethod)


@dataclass
class AgentKpi:
    status: str = "draft"
    generated_at: str = ""
    summary: str = ""
    tiles: list[KpiTile] = field(default_factory=list)
    workflow_id: str = ""
    title: str = ""


def _interval_seconds(value: float, unit: str) -> int:
    amount = max(0.0, float(value or 0))
    factor = {"minutes": 60, "hours": 3600, "days": 86400}.get((unit or "hours").strip().casefold(), 3600)
    return int(amount * factor)


def _parse_agent_run(data: dict, workflow_id: str = "") -> AgentRunHistoryItem:
    events = [item for item in data.get("events") or [] if isinstance(item, dict)]
    return AgentRunHistoryItem(
        id=str(data.get("id") or ""),
        workflow_id=str(data.get("workflow_id") or workflow_id),
        message=str(data.get("message") or ""),
        status=str(data.get("status") or ""),
        answer=str(data.get("answer") or ""),
        source=str(data.get("source") or "chat"),
        trigger_id=str(data.get("trigger_id") or ""),
        trigger_kind=str(data.get("trigger_kind") or ""),
        trigger_reason=str(data.get("trigger_reason") or ""),
        started_at=str(data.get("started_at") or ""),
        finished_at=str(data.get("finished_at") or ""),
        events=events,
    )


def _parse_schedule_draft(data: dict) -> ScheduleDraft:
    triggers: list[ScheduleTriggerSpec] = []
    for item in data.get("triggers") or []:
        if not isinstance(item, dict):
            continue
        try:
            interval_value = float(item.get("interval_value") or 0)
        except (TypeError, ValueError):
            interval_value = 0.0
        triggers.append(
            ScheduleTriggerSpec(
                kind=str(item.get("kind") or "event"),
                message=str(item.get("message") or ""),
                interval_value=interval_value,
                interval_unit=str(item.get("interval_unit") or "hours"),
                condition=str(item.get("condition") or ""),
                at=str(item.get("at") or ""),
                once=bool(item.get("once", True)),
            )
        )
    return ScheduleDraft(
        name=str(data.get("name") or ""),
        goal=str(data.get("goal") or ""),
        triggers=triggers,
    )


def _parse_kpi_side(data: dict | None) -> KpiSide:
    raw = data if isinstance(data, dict) else {}
    value = raw.get("value")
    parsed: float | None
    if value is None or value == "":
        parsed = None
    else:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = None
    return KpiSide(
        label=str(raw.get("label") or ""),
        value=parsed,
        unit=str(raw.get("unit") or ""),
        description=str(raw.get("description") or ""),
    )


def _parse_kpi_method(data: dict | None) -> KpiMethod:
    raw = data if isinstance(data, dict) else {}
    sched = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
    try:
        interval = int(float(sched.get("interval_seconds") or 3600))
    except (TypeError, ValueError):
        interval = 3600
    try:
        green = float(raw.get("green_min") if raw.get("green_min") is not None else 90)
    except (TypeError, ValueError):
        green = 90.0
    try:
        yellow = float(raw.get("yellow_min") if raw.get("yellow_min") is not None else 70)
    except (TypeError, ValueError):
        yellow = 70.0
    return KpiMethod(
        how=str(raw.get("how") or ""),
        when=str(raw.get("when") or ""),
        plan_update=str(raw.get("plan_update") or ""),
        fact_update=str(raw.get("fact_update") or ""),
        percent_formula=str(raw.get("percent_formula") or ""),
        plan_explanation=str(raw.get("plan_explanation") or ""),
        fact_explanation=str(raw.get("fact_explanation") or ""),
        score_explanation=str(raw.get("score_explanation") or ""),
        system=str(raw.get("system") or ""),
        green_min=green,
        yellow_min=yellow,
        schedule=KpiSchedule(
            kind=str(sched.get("kind") or "interval"),
            interval_seconds=interval,
            at=str(sched.get("at") or ""),
        ),
    )


def _parse_agent_kpi(data: dict) -> AgentKpi:
    tiles: list[KpiTile] = []
    for item in data.get("tiles") or []:
        if not isinstance(item, dict):
            continue
        measure = item.get("measure") if isinstance(item.get("measure"), dict) else {}
        score = item.get("score_percent")
        parsed_score: float | None
        if score is None or score == "":
            parsed_score = None
        else:
            try:
                parsed_score = float(score)
            except (TypeError, ValueError):
                parsed_score = None
        tiles.append(
            KpiTile(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                plan=_parse_kpi_side(item.get("plan") if isinstance(item.get("plan"), dict) else {}),
                fact=_parse_kpi_side(item.get("fact") if isinstance(item.get("fact"), dict) else {}),
                measure=KpiMeasure(
                    kind=str(measure.get("kind") or ""),
                    params=dict(measure.get("params") or {})
                    if isinstance(measure.get("params"), dict)
                    else {},
                    formula=str(measure.get("formula") or ""),
                ),
                score_percent=parsed_score,
                color=str(item.get("color") or "none"),
                updated_at=str(item.get("updated_at") or ""),
                next_run_at=str(item.get("next_run_at") or ""),
                evidence=str(item.get("evidence") or ""),
                method=_parse_kpi_method(item.get("method") if isinstance(item.get("method"), dict) else {}),
            )
        )
    return AgentKpi(
        status=str(data.get("status") or "draft"),
        generated_at=str(data.get("generated_at") or ""),
        summary=str(data.get("summary") or ""),
        tiles=tiles,
        workflow_id=str(data.get("workflow_id") or ""),
        title=str(data.get("title") or ""),
    )


@dataclass(frozen=True, slots=True)
class WorkflowListItem:
    id: str
    title: str
    phase: str
    document_name: str = ""
    updated_at: str = ""
    has_local_run: bool = False
    auto_run: bool = False
    paused: bool = False


@dataclass(frozen=True, slots=True)
class BoardStats:
    active_agents: int = 0
    runs_today: int = 0
    errors_today: int = 0
    needs_attention: int = 0
    next_run_at: str = ""


@dataclass(frozen=True, slots=True)
class BoardAgent:
    id: str
    kind: str = "workflow"
    title: str = ""
    description: str = ""
    status: str = "active"
    last_run_at: str = ""
    last_run_status: str = ""
    next_run_at: str = ""
    next_run_label: str = ""
    trigger_summary: str = ""
    trigger_kind: str = ""
    paused: bool = False
    phase: str = ""
    draft_id: str = ""


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    id: str
    workflow_id: str
    title: str = ""
    subtitle: str = ""
    start_at: str = ""
    status: str = "scheduled"
    source: str = "schedule"
    is_future: bool = False
    run_id: str = ""
    trigger_id: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowBoard:
    stats: BoardStats = field(default_factory=BoardStats)
    agents: list[BoardAgent] = field(default_factory=list)
    events: list[CalendarEvent] = field(default_factory=list)


def _parse_workflow_board(data: dict) -> WorkflowBoard:
    raw_stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    stats = BoardStats(
        active_agents=int(raw_stats.get("active_agents") or 0),
        runs_today=int(raw_stats.get("runs_today") or 0),
        errors_today=int(raw_stats.get("errors_today") or 0),
        needs_attention=int(raw_stats.get("needs_attention") or 0),
        next_run_at=str(raw_stats.get("next_run_at") or ""),
    )
    agents: list[BoardAgent] = []
    for item in data.get("agents") or []:
        if not isinstance(item, dict):
            continue
        agents.append(
            BoardAgent(
                id=str(item.get("id") or ""),
                kind=str(item.get("kind") or "workflow"),
                title=str(item.get("title") or ""),
                description=str(item.get("description") or ""),
                status=str(item.get("status") or "active"),
                last_run_at=str(item.get("last_run_at") or ""),
                last_run_status=str(item.get("last_run_status") or ""),
                next_run_at=str(item.get("next_run_at") or ""),
                next_run_label=str(item.get("next_run_label") or ""),
                trigger_summary=str(item.get("trigger_summary") or ""),
                trigger_kind=str(item.get("trigger_kind") or ""),
                paused=bool(item.get("paused")),
                phase=str(item.get("phase") or ""),
                draft_id=str(item.get("draft_id") or ""),
            )
        )
    events: list[CalendarEvent] = []
    for item in data.get("events") or []:
        if not isinstance(item, dict):
            continue
        events.append(
            CalendarEvent(
                id=str(item.get("id") or ""),
                workflow_id=str(item.get("workflow_id") or ""),
                title=str(item.get("title") or ""),
                subtitle=str(item.get("subtitle") or ""),
                start_at=str(item.get("start_at") or ""),
                status=str(item.get("status") or "scheduled"),
                source=str(item.get("source") or "schedule"),
                is_future=bool(item.get("is_future")),
                run_id=str(item.get("run_id") or ""),
                trigger_id=str(item.get("trigger_id") or ""),
            )
        )
    return WorkflowBoard(stats=stats, agents=agents, events=events)


def without_deleted_workflows(board: WorkflowBoard, deleted_ids: set[str]) -> WorkflowBoard:
    """Hide a locally deleted agent even if a stale live snapshot still contains it."""
    hidden = {item for item in deleted_ids if item}
    if not hidden:
        return board
    agents = [
        item
        for item in board.agents
        if item.kind != "workflow" or item.id not in hidden
    ]
    events = [
        item
        for item in board.events
        if item.workflow_id not in hidden or not item.is_future
    ]
    next_run = ""
    for item in agents:
        if item.kind != "workflow" or item.paused or not item.next_run_at:
            continue
        if not next_run or item.next_run_at < next_run:
            next_run = item.next_run_at
    if not next_run:
        for item in events:
            if item.status != "scheduled" or not item.start_at:
                continue
            if not next_run or item.start_at < next_run:
                next_run = item.start_at
    stats = BoardStats(
        active_agents=sum(1 for item in agents if item.kind == "workflow" and item.status == "active"),
        runs_today=board.stats.runs_today,
        errors_today=board.stats.errors_today,
        needs_attention=sum(1 for item in agents if item.status == "needs_attention"),
        next_run_at=next_run,
    )
    return WorkflowBoard(stats=stats, agents=agents, events=events)


def _parse_workflow_file_item(raw: object) -> WorkflowFileItem:
    data = raw if isinstance(raw, dict) else {}
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return WorkflowFileItem(
        id=str(data.get("id") or ""),
        workflow_id=str(data.get("workflow_id") or ""),
        run_id=str(data.get("run_id") or ""),
        source=str(data.get("source") or "user"),
        scope=str(data.get("scope") or "knowledge"),
        origin=str(data.get("origin") or ""),
        filename=str(data.get("filename") or data.get("name") or ""),
        mime_type=str(data.get("mime_type") or ""),
        kind=str(data.get("kind") or "text"),
        size=size,
        sha256=str(data.get("sha256") or ""),
        summary=str(data.get("summary") or ""),
        text_preview=str(data.get("text_preview") or ""),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
        agent_title=str(data.get("agent_title") or ""),
    )


def _parse_workflow_files(data: dict) -> WorkflowFiles:
    user_raw = data.get("user_files") if isinstance(data.get("user_files"), list) else []
    agent_raw = data.get("agent_files") if isinstance(data.get("agent_files"), list) else []
    return WorkflowFiles(
        user_files=[_parse_workflow_file_item(item) for item in user_raw],
        agent_files=[_parse_workflow_file_item(item) for item in agent_raw],
    )


@dataclass(frozen=True, slots=True)
class WorkflowHealth:
    ok: bool
    who: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactsDownloadResult:
    dest_dir: str
    files: list[str]


@dataclass(frozen=True, slots=True)
class QuestionChatSession:
    session_id: str
    draft_id: str
    readiness_run_id: str
    question_id: str
    function_id: str
    target_field: str
    status: str
    context: dict
    messages: list[QuestionChatMessage]


class ApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = 600.0) -> None:
        self.base_url = (base_url or backend_url()).rstrip("/")
        self._timeout = timeout
        self._token: str | None = None
        self._user_id: str = ""

    @property
    def token(self) -> str | None:
        return self._token

    def set_token(self, token: str | None) -> None:
        self._token = token

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def health(self) -> HealthStatus:
        data = self._request("GET", "/health")
        return HealthStatus(
            status=str(data.get("status", "")),
            erp_reachable=bool(data.get("erp_reachable")),
            erp_server=str(data.get("erp_server", "")),
            llm_provider=str(data.get("llm_provider", "")),
        )

    def search_users(self, search: str = "") -> list[str]:
        from app.chat.test_user import TEST_USER_FIO, matches_test_user_query

        items: list[str] = []
        error: ApiError | None = None
        try:
            params = {"search": search} if search.strip() else None
            data = self._request("GET", "/api/v1/auth/users", params=params)
            items = [str(item) for item in (data.get("items") or [])]
        except ApiError as exc:
            error = exc
        if matches_test_user_query(search) and TEST_USER_FIO not in items:
            items.insert(0, TEST_USER_FIO)
        if items:
            return items
        if error is not None:
            raise error
        return items

    def login(self, fio: str, password: str) -> LoginResult:
        data = self._request(
            "POST",
            "/api/v1/auth/login",
            json={"fio": fio, "password": password},
        )
        user = self._parse_user(data.get("user") or {})
        token = str(data.get("access_token", ""))
        self._token = token
        self._user_id = user.id
        return LoginResult(access_token=token, user=user)

    def me(self) -> UserProfile:
        data = self._request("GET", "/api/v1/auth/me")
        user = self._parse_user(data)
        self._user_id = user.id
        return user

    def fetch_bytes(self, path_or_url: str) -> bytes:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            url = path_or_url
        else:
            url = f"{self.base_url}{path_or_url}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, headers=self._headers())
        except httpx.ConnectError as exc:
            raise ApiError(
                f"Не удалось подключиться к backend ({self.base_url})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время ожидания ответа backend") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc

        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        return response.content

    def upload_avatar(self, file_path: str | Path) -> UserProfile:
        path = Path(file_path)
        if not path.is_file():
            raise ApiError("Файл не найден")
        url = f"{self.base_url}/api/v1/auth/me/avatar"
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(path.suffix.lower(), "application/octet-stream")
        try:
            with httpx.Client(timeout=self._timeout) as client:
                with path.open("rb") as fh:
                    response = client.post(
                        url,
                        headers=self._headers(),
                        files={"file": (path.name, fh, mime)},
                    )
        except httpx.ConnectError as exc:
            raise ApiError(
                f"Не удалось подключиться к backend ({self.base_url})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время ожидания ответа backend") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc

        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        return self._parse_user(response.json())

    def upload_regulation(self, file_path: str | Path) -> RegulationParseResult:
        path = Path(file_path)
        if not path.is_file():
            raise ApiError("Файл не найден")
        url = f"{self.base_url}/api/v1/regulations/upload"
        mime = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pdf": "application/pdf",
            ".md": "text/markdown",
            ".txt": "text/plain",
        }.get(path.suffix.lower(), "application/octet-stream")
        try:
            with httpx.Client(timeout=max(self._timeout, 240.0)) as client:
                with path.open("rb") as fh:
                    response = client.post(
                        url,
                        headers=self._headers(),
                        files={"file": (path.name, fh, mime)},
                    )
        except httpx.ConnectError as exc:
            raise ApiError(
                f"Не удалось подключиться к backend ({self.base_url})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время распознавания регламента") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc

        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        return self._parse_regulation(response.json())

    def start_regulation_creation(self) -> RegulationCreationSession:
        data = self._request(
            "POST",
            "/api/v1/regulation-creation/sessions",
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_creation_session(data)

    def get_regulation_creation_session(self, draft_id: str) -> RegulationCreationSession:
        data = self._request(
            "GET",
            f"/api/v1/regulation-creation/sessions/{draft_id}",
            timeout=max(self._timeout, 30.0),
        )
        return self._parse_creation_session(data)

    def send_regulation_creation_message(self, draft_id: str, message: str) -> RegulationCreationSession:
        data = self._request(
            "POST",
            f"/api/v1/regulation-creation/sessions/{draft_id}/messages",
            json={"message": message},
            timeout=max(self._timeout, 420.0),
        )
        return self._parse_creation_session(data)

    def stream_regulation_creation_message(
        self,
        draft_id: str,
        message: str,
        on_event: Callable[[str, str], None],
        *,
        file_paths: list[str | Path] | None = None,
    ) -> RegulationCreationSession:
        url = f"{self.base_url}/api/v1/regulation-creation/sessions/{draft_id}/messages/stream"
        final_session: RegulationCreationSession | None = None
        paths = [Path(path) for path in (file_paths or []) if Path(path).is_file()]
        handles: list = []
        files: list = []
        data = None
        request_json: dict | None = {"message": message}
        try:
            if paths:
                request_json = None
                data = {"message": message}
                for path in paths:
                    handle = path.open("rb")
                    handles.append(handle)
                    files.append(("files", (path.name, handle, "application/octet-stream")))
            with httpx.Client(timeout=None) as client:
                with client.stream(
                    "POST",
                    url,
                    headers={**self._headers(), "Accept": "text/event-stream"},
                    json=request_json,
                    data=data,
                    files=files or None,
                ) as response:
                    if response.status_code >= 400:
                        body = response.read().decode("utf-8", errors="replace")
                        detail = body
                        try:
                            payload = json.loads(body)
                            value = payload.get("detail")
                            if isinstance(value, str) and value.strip():
                                detail = value
                            elif isinstance(value, list) and value:
                                first = value[0]
                                if isinstance(first, dict):
                                    detail = str(first.get("msg") or first.get("message") or first)
                                else:
                                    detail = str(first)
                        except Exception:
                            pass
                        raise ApiError(detail or "Ошибка создания регламента", status_code=response.status_code)
                    event_name = "message"
                    data_lines: list[str] = []
                    for line in response.iter_lines():
                        if line == "":
                            if data_lines:
                                payload = _parse_sse_payload("\n".join(data_lines))
                                payload_type = str(payload.get("type") or event_name)
                                if payload_type in {"thinking", "assistant"}:
                                    on_event(payload_type, str(payload.get("text") or ""))
                                elif payload_type == "status":
                                    on_event(payload_type, str(payload.get("status") or ""))
                                elif payload_type == "error":
                                    raise ApiError(str(payload.get("message") or "Ошибка Cursor Agent"))
                                elif payload_type == "session" and isinstance(payload.get("session"), dict):
                                    final_session = self._parse_creation_session(payload["session"])
                            event_name = "message"
                            data_lines = []
                            continue
                        if line.startswith("event:"):
                            event_name = line.split(":", 1)[1].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line.split(":", 1)[1].strip())
        except httpx.ConnectError as exc:
            recovered = self._try_recover_creation_session(draft_id)
            if recovered is not None:
                return recovered
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})") from exc
        except httpx.HTTPError as exc:
            recovered = self._try_recover_creation_session(draft_id)
            if recovered is not None:
                return recovered
            raise ApiError(f"Ошибка сети: {exc}") from exc
        finally:
            for handle in handles:
                handle.close()
        if final_session is None:
            recovered = self._try_recover_creation_session(draft_id)
            if recovered is not None:
                return recovered
            raise ApiError("Backend не вернул итоговую сессию создания регламента")
        return final_session

    def _try_recover_creation_session(self, draft_id: str) -> RegulationCreationSession | None:
        try:
            session = self.get_regulation_creation_session(draft_id)
        except ApiError:
            return None
        if session.status == "generating":
            return None
        return session

    def terminate_regulation_creation_sessions(self) -> None:
        if not self._token:
            return
        self._request(
            "POST",
            "/api/v1/regulation-creation/sessions/terminate-active",
            timeout=max(self._timeout, 30.0),
        )

    def get_regulation(self, regulation_id: str) -> RegulationParseResult:
        data = self._request("GET", f"/api/v1/regulations/{regulation_id}")
        return self._parse_regulation(data)

    def create_role_matches(
        self,
        regulation_id: str,
        *,
        position: str,
        department: str,
    ) -> RoleMatchResult:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/role-matches",
            json={"position": position.strip(), "department": department.strip()},
            timeout=max(self._timeout, 300.0),
        )
        return self._parse_role_matches(data)

    def extract_regulation_functions(
        self,
        regulation_id: str,
        *,
        position: str,
        department: str,
    ) -> RoleMatchResult:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/function-extraction",
            json={"position": position.strip(), "department": department.strip()},
            timeout=max(self._timeout, 420.0),
        )
        return self._parse_role_matches(data)

    def decide_role_match(
        self,
        regulation_id: str,
        run_id: str,
        match_id: str,
        status: str,
    ) -> RoleMatchResult:
        data = self._request(
            "PATCH",
            f"/api/v1/regulations/{regulation_id}/role-matches/{run_id}/{match_id}",
            json={"status": status},
            timeout=max(self._timeout, 60.0),
        )
        return self._parse_role_matches(data)

    def create_readiness_run(self, regulation_id: str, role_match_run_id: str) -> AgentReadinessResult:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/role-matches/{role_match_run_id}/readiness",
            timeout=max(self._timeout, 180.0),
        )
        return self._parse_readiness(data)

    def answer_readiness_question(
        self,
        regulation_id: str,
        readiness_run_id: str,
        question_id: str,
        answer: str,
    ) -> AgentReadinessResult:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/readiness/{readiness_run_id}/answers",
            json={"questionId": question_id, "answer": answer},
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_readiness(data)

    def update_readiness_change(
        self,
        regulation_id: str,
        readiness_run_id: str,
        change_id: str,
        status: str,
        after: str = "",
    ) -> AgentReadinessResult:
        data = self._request(
            "PATCH",
            f"/api/v1/regulations/{regulation_id}/readiness/{readiness_run_id}/changes/{change_id}",
            json={"status": status, "after": after},
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_readiness(data)

    def finalize_readiness(
        self,
        regulation_id: str,
        readiness_run_id: str,
    ) -> RegulationRevisionResult:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/readiness/{readiness_run_id}/finalize",
            timeout=max(self._timeout, 180.0),
        )
        return RegulationRevisionResult(
            revision_id=str(data.get("revisionId") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            readiness_run_id=str(data.get("readinessRunId") or ""),
            document_path=str(data.get("documentPath") or ""),
            protocol_path=str(data.get("protocolPath") or ""),
            pdf_path=str(data.get("pdfPath") or ""),
            source_preview_html=str(data.get("sourcePreviewHtml") or ""),
            revised_preview_html=str(data.get("revisedPreviewHtml") or ""),
            source_preview_pages=[
                RevisionPreviewPage(
                    page=int(item.get("page") or 0),
                    image_url=str(item.get("imageUrl") or ""),
                )
                for item in data.get("sourcePreviewPages") or []
                if isinstance(item, dict)
            ],
            revised_preview_pages=[
                RevisionPreviewPage(
                    page=int(item.get("page") or 0),
                    image_url=str(item.get("imageUrl") or ""),
                )
                for item in data.get("revisedPreviewPages") or []
                if isinstance(item, dict)
            ],
            diff_blocks=[
                RevisionDiffBlock(
                    block_id=str(item.get("blockId") or ""),
                    section=str(item.get("section") or ""),
                    before=str(item.get("before") or ""),
                    after=str(item.get("after") or ""),
                    page=int(item.get("page") or 0),
                    bbox=[float(value) for value in item.get("bbox") or []]
                    if isinstance(item.get("bbox"), list)
                    else None,
                    status=str(item.get("status") or ""),
                )
                for item in data.get("diffBlocks") or []
                if isinstance(item, dict)
            ],
            download_url=str(data.get("downloadUrl") or ""),
            pdf_download_url=str(data.get("pdfDownloadUrl") or ""),
            protocol_url=str(data.get("protocolUrl") or ""),
            message=str(data.get("message") or ""),
        )

    def create_agent_draft(self, regulation_id: str, role_match_run_id: str) -> AgentDraft:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/role-matches/{role_match_run_id}/draft",
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_agent_draft(data)

    def list_agent_drafts(self) -> list[AgentDraft]:
        data = self._request("GET", "/api/v1/agents/drafts", timeout=max(self._timeout, 60.0))
        return [self._parse_agent_draft(item) for item in data.get("items") or [] if isinstance(item, dict)]

    def get_agent_draft(self, draft_id: str) -> AgentDraft:
        data = self._request("GET", f"/api/v1/agents/drafts/{draft_id}", timeout=max(self._timeout, 60.0))
        return self._parse_agent_draft(data)

    def delete_agent_draft(self, draft_id: str) -> None:
        self._request("DELETE", f"/api/v1/agents/drafts/{draft_id}", timeout=max(self._timeout, 60.0))

    def delete_agent_draft_suggestion(self, draft_id: str, agent_id: str) -> None:
        safe_agent_id = quote(agent_id, safe="")
        self._request(
            "DELETE",
            f"/api/v1/agents/drafts/{draft_id}/suggestions/{safe_agent_id}",
            timeout=max(self._timeout, 60.0),
        )

    def ensure_draft_readiness(self, draft_id: str) -> AgentDraft:
        data = self._request(
            "POST",
            f"/api/v1/agents/drafts/{draft_id}/readiness",
            timeout=max(self._timeout, 180.0),
        )
        return self._parse_agent_draft(data)

    def update_agent_draft_status(self, draft_id: str, status: str) -> AgentDraft:
        data = self._request(
            "PATCH",
            f"/api/v1/agents/drafts/{draft_id}/status",
            json={"status": status},
            timeout=max(self._timeout, 60.0),
        )
        return self._parse_agent_draft(data)

    def finish_sdk_readiness(
        self,
        draft_id: str,
        *,
        answer: str,
        events: list[dict] | None = None,
    ) -> AgentDraft:
        data = self._request(
            "POST",
            f"/api/v1/agents/drafts/{draft_id}/sdk-readiness",
            json={"answer": answer, "events": events or []},
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_agent_draft(data)

    def reanalyze_revision_document(self, draft_id: str) -> list[AgentSuggestion]:
        data = self._request(
            "POST",
            f"/api/v1/agents/drafts/{draft_id}/reanalyze-revision",
            timeout=max(self._timeout, 420.0),
        )
        return [
            self._parse_agent_suggestion(item)
            for item in data.get("items") or []
            if isinstance(item, dict)
        ]

    def draft_passport_from_suggestion(
        self,
        suggestion: AgentSuggestion,
        *,
        draft_id: str = "",
        agent_id: str = "",
    ) -> PassportSession:
        data = self._request(
            "POST",
            "/api/v1/regulations/passport/draft-from-suggestion",
            json={
                "regulationId": suggestion.regulation_id,
                "roleMatchRunId": suggestion.role_match_run_id,
                "functionId": suggestion.function_id,
                "agentTitle": suggestion.title,
                "agentDescription": suggestion.description,
                "draftId": draft_id,
                "agentId": agent_id,
            },
            timeout=max(self._timeout, 180.0),
        )
        return self._parse_passport_session(data)

    def complete_passport(
        self,
        passport: AgentPassport,
        *,
        answers: dict[str, str],
        bp_name: str,
        excerpt: str,
        functions: list[PassportFunction],
        field_updates: dict[str, str] | None = None,
        draft_id: str = "",
        agent_id: str = "",
        function_id: str = "",
        regulation_id: str = "",
        role_match_run_id: str = "",
        qa_history: list[tuple[str, str, list[str]]] | None = None,
    ) -> PassportSession:
        data = self._request(
            "POST",
            "/api/v1/regulations/passport/complete",
            json={
                "passport": passport.to_api_dict(),
                "answers": answers,
                "field_updates": field_updates or {},
                "bp_name": bp_name,
                "excerpt": excerpt,
                "functions": [
                    {
                        "name": item.name,
                        "description": item.description,
                        "action_level": item.action_level,
                        "requires_human_approval": item.requires_human_approval,
                        "automation_kind": item.automation_kind,
                    }
                    for item in functions
                ],
                "draftId": draft_id,
                "agentId": agent_id,
                "functionId": function_id,
                "regulationId": regulation_id,
                "roleMatchRunId": role_match_run_id,
                "qaHistory": [
                    {"prompt": prompt, "answer": answer, "files": list(files or [])}
                    for prompt, answer, files in (qa_history or [])
                ],
            },
            timeout=max(self._timeout, 180.0),
        )
        return self._parse_passport_session(data)

    @staticmethod
    def _parse_passport_session(data: dict) -> PassportSession:
        passport_raw = data.get("passport") if isinstance(data.get("passport"), dict) else {}
        functions = [
            PassportFunction(
                name=str(item.get("name") or ""),
                description=str(item.get("description") or ""),
                action_level=str(item.get("action_level") or "read"),
                requires_human_approval=bool(item.get("requires_human_approval")),
                automation_kind=str(item.get("automation_kind") or "auto"),
            )
            for item in data.get("functions") or []
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        qa_history: list[tuple[str, str, list[str]]] = []
        for item in data.get("qaHistory") or []:
            if not isinstance(item, dict):
                continue
            qa_history.append(
                (
                    str(item.get("prompt") or ""),
                    str(item.get("answer") or ""),
                    [str(path) for path in (item.get("files") or []) if str(path).strip()],
                )
            )
        return PassportSession(
            passport=AgentPassport(
                name=str(passport_raw.get("name") or ""),
                goal=str(passport_raw.get("goal") or ""),
                trigger=str(passport_raw.get("trigger") or ""),
                receives=str(passport_raw.get("receives") or ""),
                checks=str(passport_raw.get("checks") or ""),
                decisions=str(passport_raw.get("decisions") or ""),
                can_autonomous=str(passport_raw.get("can_autonomous") or ""),
                needs_human_approval=str(passport_raw.get("needs_human_approval") or ""),
                forbidden=str(passport_raw.get("forbidden") or ""),
                result=str(passport_raw.get("result") or ""),
                missing_fields=[str(x) for x in passport_raw.get("missing_fields") or []],
                questions=[item for item in passport_raw.get("questions") or [] if isinstance(item, dict)],
                source=str(passport_raw.get("source") or "heuristic"),
                text=str(passport_raw.get("text") or ""),
                autonomy_level=int(passport_raw.get("autonomy_level") or 1) or 1,
                cursor_agent_id=str(passport_raw.get("cursor_agent_id") or ""),
            ),
            bp_name=str(data.get("bp_name") or ""),
            excerpt=str(data.get("excerpt") or ""),
            functions=functions,
            draft_id=str(data.get("draftId") or ""),
            reused=bool(data.get("reused")),
            llm_error=str(data.get("llmError") or passport_raw.get("llm_error") or ""),
            qa_history=qa_history,
        )

    @staticmethod
    def _parse_agent_suggestion(data: dict) -> AgentSuggestion:
        return AgentSuggestion(
            agent_id=str(data.get("agentId") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            role_match_run_id=str(data.get("roleMatchRunId") or ""),
            function_id=str(data.get("functionId") or ""),
            source_block_id=str(data.get("sourceBlockId") or ""),
        )

    def create_question_chat(self, draft_id: str, question_id: str) -> QuestionChatSession:
        data = self._request(
            "POST",
            f"/api/v1/agents/drafts/{draft_id}/questions/{question_id}/chat",
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_question_chat(data)

    def latest_question_chat(self, draft_id: str) -> QuestionChatSession:
        data = self._request(
            "GET",
            f"/api/v1/agents/drafts/{draft_id}/chat/latest",
            timeout=max(self._timeout, 60.0),
        )
        return self._parse_question_chat(data)

    def send_question_chat_message(
        self,
        draft_id: str,
        question_id: str,
        message: str,
    ) -> QuestionChatSession:
        data = self._request(
            "POST",
            f"/api/v1/agents/drafts/{draft_id}/questions/{question_id}/chat/messages",
            json={"message": message},
            timeout=max(self._timeout, 180.0),
        )
        return self._parse_question_chat(data)

    def list_departments(self) -> list[str]:
        data = self._request("GET", "/api/v1/auth/departments")
        items = data.get("items") or []
        return [str(x) for x in items]

    def update_department(self, department: str) -> UserProfile:
        data = self._request(
            "PATCH",
            "/api/v1/auth/me/department",
            json={"department": department},
        )
        return self._parse_user(data)

    def workflow_health(self) -> WorkflowHealth:
        data = self._request("GET", "/api/v1/workflows/health", timeout=30.0)
        return WorkflowHealth(
            ok=bool(data.get("ok")),
            who=str(data.get("who") or ""),
            message=str(data.get("message") or ""),
        )

    def list_workflows(self) -> list[WorkflowListItem]:
        data = self._request("GET", "/api/v1/workflows", timeout=60.0)
        items = data if isinstance(data, list) else []
        return [
            WorkflowListItem(
                id=str(x.get("id") or ""),
                title=str(x.get("title") or ""),
                phase=str(x.get("phase") or ""),
                document_name=str(x.get("document_name") or ""),
                updated_at=str(x.get("updated_at") or ""),
                has_local_run=bool(x.get("has_local_run")),
                auto_run=bool(x.get("auto_run")),
                paused=bool(x.get("paused")),
            )
            for x in items
            if isinstance(x, dict)
        ]

    def get_workflow_board(
        self,
        *,
        window_from: str = "",
        window_to: str = "",
        workflow_id: str = "",
    ) -> WorkflowBoard:
        params: dict[str, str] = {}
        if window_from:
            params["window_from"] = window_from
        if window_to:
            params["window_to"] = window_to
        if workflow_id:
            params["workflow_id"] = workflow_id
        data = self._request("GET", "/api/v1/workflows/board", params=params or None, timeout=60.0)
        if not isinstance(data, dict):
            return WorkflowBoard()
        return _parse_workflow_board(data)

    def get_workflow(self, workflow_id: str) -> WorkflowRecord:
        data = self._request("GET", f"/api/v1/workflows/{workflow_id}", timeout=60.0)
        return self._parse_workflow(data)

    def create_workflow(self, *, notes: str, file_paths: list[str | Path]) -> WorkflowRecord:
        import tempfile

        url = f"{self.base_url}/api/v1/workflows"
        files: list = []
        handles = []
        temp_notes: Path | None = None
        try:
            paths = [Path(p) for p in file_paths if Path(p).is_file()]
            if not paths and (notes or "").strip():
                tmp = tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".txt",
                    delete=False,
                    encoding="utf-8",
                )
                tmp.write(notes)
                tmp.close()
                temp_notes = Path(tmp.name)
                paths = [temp_notes]
            for path in paths:
                fh = path.open("rb")
                handles.append(fh)
                name = "notes.txt" if temp_notes and path == temp_notes else path.name
                files.append(("files", (name, fh, "application/octet-stream")))
            data_form = {"notes": notes or ""}
            with httpx.Client(timeout=max(self._timeout, 180.0)) as client:
                response = client.post(
                    url,
                    headers=self._headers(),
                    data=data_form,
                    files=files,
                )
        except httpx.ConnectError as exc:
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})") from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время создания workflow") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc
        finally:
            for fh in handles:
                fh.close()
            if temp_notes is not None:
                try:
                    temp_notes.unlink(missing_ok=True)
                except OSError:
                    pass
        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        return self._parse_workflow(response.json())

    def delete_workflow(self, workflow_id: str) -> None:
        self._request("DELETE", f"/api/v1/workflows/{workflow_id}", timeout=60.0)

    def stop_workflow_auto_run(self, workflow_id: str) -> int:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/stop-auto-run",
            timeout=30.0,
        )
        if isinstance(data, dict):
            try:
                return int(data.get("stopped") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def resume_workflow_auto_run(self, workflow_id: str) -> int:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/resume-auto-run",
            timeout=30.0,
        )
        if isinstance(data, dict):
            try:
                return int(data.get("stopped") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def plan_workflow(self, workflow_id: str) -> WorkflowRecord:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/plan",
            timeout=900.0,
        )
        return self._parse_workflow(data)

    def stream_plan_workflow(
        self,
        workflow_id: str,
        on_event: Callable[[str, str], None],
    ) -> WorkflowRecord:
        return self._stream_workflow(
            "POST",
            f"/api/v1/workflows/{workflow_id}/plan/stream",
            on_event=on_event,
        )

    def local_design_prompt(self, workflow_id: str) -> str:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/design/local-context",
            timeout=60.0,
        )
        if not isinstance(data, dict):
            raise ApiError("Backend не вернул промпт проектирования")
        return str(data.get("prompt") or "")

    def finish_local_design_workflow(
        self,
        workflow_id: str,
        *,
        answer: str,
        events: list[dict] | None = None,
    ) -> WorkflowRecord:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/design/local-finish",
            json={"answer": answer, "events": events or []},
            timeout=120.0,
        )
        if not isinstance(data, dict):
            raise ApiError("Backend не вернул итоговый workflow")
        return self._parse_workflow(data)

    def stream_demo_workflow(
        self,
        workflow_id: str,
        on_event: Callable[[str, str], None],
    ) -> WorkflowRecord:
        return self._stream_workflow(
            "POST",
            f"/api/v1/workflows/{workflow_id}/demo/stream",
            on_event=on_event,
        )

    def finish_local_demo_workflow(
        self,
        workflow_id: str,
        *,
        answer: str,
        events: list[dict] | None = None,
    ) -> WorkflowRecord:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/demo/local-finish",
            json={"answer": answer, "events": events or []},
            timeout=120.0,
        )
        if not isinstance(data, dict):
            raise ApiError("Backend не вернул итоговый workflow")
        return self._parse_workflow(data)

    def clarify_workflow(
        self,
        workflow_id: str,
        answers: dict[str, str],
        *,
        file_paths: list[str | Path] | None = None,
        file_question_ids: list[str] | None = None,
    ) -> WorkflowRecord:
        paths = [Path(p) for p in (file_paths or []) if Path(p).is_file()]
        if not paths:
            data = self._request(
                "POST",
                f"/api/v1/workflows/{workflow_id}/clarify",
                json={"answers": answers},
                timeout=900.0,
            )
            return self._parse_workflow(data)

        import json as _json

        url = f"{self.base_url}/api/v1/workflows/{workflow_id}/clarify"
        files: list = []
        handles = []
        try:
            qids = list(file_question_ids or [])
            while len(qids) < len(paths):
                qids.append("")
            for path in paths:
                fh = path.open("rb")
                handles.append(fh)
                files.append(("files", (path.name, fh, "application/octet-stream")))
            form = {
                "answers": _json.dumps(answers or {}, ensure_ascii=False),
                "file_question_ids": _json.dumps(qids[: len(paths)], ensure_ascii=False),
            }
            with httpx.Client(timeout=max(self._timeout, 900.0)) as client:
                response = client.post(
                    url,
                    headers=self._headers(),
                    data=form,
                    files=files,
                )
        except httpx.ConnectError as exc:
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})") from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время уточнения плана") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc
        finally:
            for fh in handles:
                fh.close()
        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        return self._parse_workflow(response.json())

    def stream_clarify_workflow(
        self,
        workflow_id: str,
        answers: dict[str, str],
        on_event: Callable[[str, str], None],
        *,
        file_paths: list[str | Path] | None = None,
        file_question_ids: list[str] | None = None,
    ) -> WorkflowRecord:
        return self._stream_workflow(
            "POST",
            f"/api/v1/workflows/{workflow_id}/clarify/stream",
            on_event=on_event,
            answers=answers,
            file_paths=file_paths,
            file_question_ids=file_question_ids,
        )

    def execute_workflow(self, workflow_id: str, *, reexecute: bool = False) -> WorkflowRecord:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/execute",
            json={"reexecute": reexecute},
            timeout=900.0,
        )
        return self._parse_workflow(data)

    def stream_execute_workflow(
        self,
        workflow_id: str,
        on_event: Callable[[str, str], None],
        *,
        reexecute: bool = False,
    ) -> WorkflowRecord:
        return self._stream_workflow(
            "POST",
            f"/api/v1/workflows/{workflow_id}/execute/stream",
            on_event=on_event,
            json_body={"reexecute": reexecute},
        )

    def list_agent_tools(self) -> list[dict]:
        data = self._request("GET", "/api/v1/workflows/agent-tools", timeout=60.0)
        return [item for item in (data.get("tools") or []) if isinstance(item, dict)]

    def _handle_sse_tool_request(self, payload: dict, *, fallback_run_id: str = "") -> None:
        from app.tools import ToolHostError, invoke_tool
        from app.tools.hitl import HUMAN_REJECTED, confirm_level1_tool

        req_run = str(payload.get("run_id") or fallback_run_id)
        request_id = str(payload.get("request_id") or "")
        tool = str(payload.get("tool") or "")
        arguments = (
            dict(payload.get("arguments")) if isinstance(payload.get("arguments"), dict) else {}
        )
        workflow_id = str(
            arguments.get("workflow_id")
            or arguments.get("agent_id")
            or payload.get("workflow_id")
            or ""
        )
        if workflow_id and not isinstance(arguments.get("runtime_context"), dict):
            arguments["runtime_context"] = {"workflow_id": workflow_id, "agent_id": workflow_id}
        if workflow_id:
            arguments.setdefault("workflow_id", workflow_id)
            arguments.setdefault("agent_id", workflow_id)
        try:
            if not confirm_level1_tool(tool, arguments):
                self.post_agent_tool_result(
                    req_run,
                    request_id=request_id,
                    ok=False,
                    error=HUMAN_REJECTED,
                )
                return
            if payload.get("confirm_only"):
                self.post_agent_tool_result(
                    req_run,
                    request_id=request_id,
                    ok=True,
                    result={"confirmed": True},
                )
                return
            tool_result = invoke_tool(tool, arguments)
            from app.tools.result_files import publish_result_files

            publish_result_files(
                tool_result,
                tool=tool,
                workflow_id=workflow_id,
            )
            self.post_agent_tool_result(
                req_run,
                request_id=request_id,
                ok=True,
                result=tool_result,
            )
        except ToolHostError as exc:
            from app.tools.result_files import publish_answer_files

            publish_answer_files(
                workflow_id=workflow_id,
                arguments=arguments,
                tool=tool,
            )
            try:
                self.post_agent_tool_result(
                    req_run,
                    request_id=request_id,
                    ok=False,
                    error=str(exc),
                )
            except ApiError:
                raise ApiError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            err = f"Ошибка инструмента {tool}: {exc}"
            try:
                self.post_agent_tool_result(
                    req_run,
                    request_id=request_id,
                    ok=False,
                    error=err,
                )
            except ApiError:
                raise ApiError(err) from exc

    def post_agent_tool_result(
        self,
        run_id: str,
        *,
        request_id: str,
        ok: bool,
        result: dict | None = None,
        error: str = "",
    ) -> None:
        try:
            self._request(
                "POST",
                f"/api/v1/workflows/agent-runs/{run_id}/tool-results",
                json={
                    "request_id": request_id,
                    "ok": ok,
                    "result": result or {},
                    "error": error or "",
                },
                timeout=120.0,
            )
        except ApiError as exc:
            if exc.status_code == 404:
                return
            raise

    def stream_workflow_agent_run(
        self,
        workflow_id: str,
        message: str,
        on_event: Callable[[dict], None],
        *,
        source: str = "chat",
        trigger_id: str = "",
        evidence: str = "",
    ) -> dict:
        url = f"{self.base_url}/api/v1/workflows/{workflow_id}/agent-runs/stream"
        final_result: dict | None = None
        run_id = ""
        try:
            with httpx.Client(timeout=None) as client:
                with client.stream(
                    "POST",
                    url,
                    headers={**self._headers(), "Accept": "text/event-stream"},
                    json={
                        "message": message,
                        "source": source or "chat",
                        "trigger_id": trigger_id or "",
                        "evidence": evidence or "",
                    },
                ) as response:
                    if response.status_code >= 400:
                        body = response.read().decode("utf-8", errors="replace")
                        raise ApiError(body or "Ошибка запуска агента", status_code=response.status_code)
                    data_lines: list[str] = []
                    for line in response.iter_lines():
                        if line == "":
                            if data_lines:
                                payload = _parse_sse_payload("\n".join(data_lines))
                                payload_type = str(payload.get("type") or "")
                                if payload_type == "run":
                                    run_id = str(payload.get("run_id") or "")
                                    on_event(payload)
                                elif payload_type == "tool_request":
                                    tool = str(payload.get("tool") or "")
                                    on_event(
                                        {
                                            "type": "status",
                                            "text": f"Выполняю на этом компьютере: {tool}…",
                                        }
                                    )
                                    Thread(
                                        target=self._handle_sse_tool_request,
                                        kwargs={
                                            "payload": payload,
                                            "fallback_run_id": run_id,
                                        },
                                        daemon=True,
                                    ).start()
                                elif payload_type in {"heartbeat", "ping"}:
                                    continue
                                elif payload_type == "error":
                                    raise ApiError(str(payload.get("message") or "Ошибка запуска агента"))
                                elif payload_type == "done":
                                    final_result = (
                                        payload.get("result")
                                        if isinstance(payload.get("result"), dict)
                                        else {}
                                    )
                                else:
                                    on_event(payload)
                            data_lines = []
                            continue
                        if line.startswith("data:"):
                            data_lines.append(line.split(":", 1)[1].strip())
        except httpx.ConnectError as exc:
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc
        return final_result or {}

    def list_inbox(self) -> tuple[list[InboxNotification], int]:
        data = self._request("GET", "/api/v1/notifications", timeout=20.0)
        raw = data if isinstance(data, dict) else {}
        items: list[InboxNotification] = []
        for item in raw.get("items") or []:
            if not isinstance(item, dict):
                continue
            items.append(
                InboxNotification(
                    id=str(item.get("id") or ""),
                    title=str(item.get("title") or "Уведомление"),
                    body=str(item.get("body") or ""),
                    workflow_id=str(item.get("workflow_id") or ""),
                    run_id=str(item.get("run_id") or ""),
                    sender_fio=str(item.get("sender_fio") or ""),
                    unread=bool(item.get("unread", item.get("read_at") in (None, ""))),
                    created_at=str(item.get("created_at") or ""),
                    send_at=str(item.get("send_at") or ""),
                    agent_deleted=bool(item.get("agent_deleted")),
                )
            )
        try:
            unread = int(raw.get("unread_count") or sum(1 for item in items if item.unread))
        except (TypeError, ValueError):
            unread = sum(1 for item in items if item.unread)
        return items, unread

    def create_inbox_notification(
        self,
        *,
        title: str,
        body: str = "",
        workflow_id: str = "",
        recipient_user_id: str = "",
    ) -> dict:
        user_id = (recipient_user_id or self._user_id).strip()
        if not user_id:
            user_id = self.me().id
        return self._request(
            "POST",
            "/api/v1/notifications",
            json={
                "recipient_user_id": user_id,
                "title": title,
                "body": body,
                "workflow_id": workflow_id,
            },
            timeout=20.0,
        )

    def unread_notification_count(self) -> int:
        data = self._request("GET", "/api/v1/notifications/unread-count", timeout=15.0)
        if isinstance(data, dict):
            try:
                return int(data.get("count") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def mark_notification_read(self, notification_id: str) -> None:
        self._request("POST", f"/api/v1/notifications/{notification_id}/read", timeout=15.0)

    def mark_all_notifications_read(self) -> None:
        self._request("POST", "/api/v1/notifications/read-all", timeout=15.0)

    def clear_notifications(self) -> int:
        data = self._request("POST", "/api/v1/notifications/clear", timeout=20.0)
        if isinstance(data, dict):
            try:
                return int(data.get("deleted") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def propose_schedule_draft(self, workflow_id: str) -> ScheduleDraft:
        data = self._request("POST", f"/api/v1/workflows/{workflow_id}/schedule-draft", timeout=90.0)
        return _parse_schedule_draft(data if isinstance(data, dict) else {})

    def create_trigger(
        self,
        workflow_id: str,
        spec: ScheduleTriggerSpec,
        *,
        message: str = "",
    ) -> dict:
        payload: dict = {
            "workflow_id": workflow_id,
            "message": (message or spec.message or "").strip(),
            "once": bool(spec.once),
        }
        if spec.kind == "interval":
            payload["interval_seconds"] = _interval_seconds(spec.interval_value, spec.interval_unit)
            payload["once"] = False
        elif spec.kind == "event":
            payload["condition"] = spec.condition.strip()
        elif spec.kind == "datetime":
            payload["at"] = spec.at.strip()
        return self._request("POST", "/api/v1/triggers", json=payload, timeout=30.0)

    def create_timed_trigger(self, workflow_id: str, *, at: str, message: str = "") -> dict:
        return self._request(
            "POST",
            "/api/v1/triggers",
            json={
                "workflow_id": workflow_id,
                "at": at,
                "once": True,
                "message": (message or "").strip(),
            },
            timeout=30.0,
        )

    def cancel_trigger(self, trigger_id: str) -> None:
        self._request("POST", f"/api/v1/triggers/{trigger_id}/cancel", timeout=30.0)

    def list_triggers(self) -> list[dict]:
        data = self._request("GET", "/api/v1/triggers", timeout=30.0)
        if isinstance(data, dict):
            items = data.get("items") or []
            return [item for item in items if isinstance(item, dict)]
        return []

    def list_agent_runs(self, workflow_id: str) -> list[AgentRunHistoryItem]:
        data = self._request("GET", f"/api/v1/workflows/{workflow_id}/runs", timeout=60.0)
        items = data if isinstance(data, list) else []
        return [
            _parse_agent_run(item, workflow_id)
            for item in items
            if isinstance(item, dict)
        ]

    def start_local_agent_run(
        self,
        workflow_id: str,
        *,
        message: str,
        source: str = "chat",
        trigger_id: str = "",
        evidence: str = "",
    ) -> AgentRunHistoryItem:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/runs/local",
            json={
                "message": message,
                "source": source or "chat",
                "trigger_id": trigger_id or "",
                "evidence": evidence or "",
            },
            timeout=30.0,
        )
        if not isinstance(data, dict):
            raise ApiError("Не удалось создать запуск агента")
        return _parse_agent_run(data, workflow_id)

    def update_local_agent_run_events(
        self,
        workflow_id: str,
        run_id: str,
        events: list[dict],
    ) -> None:
        self._request(
            "PATCH",
            f"/api/v1/workflows/{workflow_id}/runs/{run_id}/events",
            json={"events": events},
            timeout=30.0,
        )

    def finish_local_agent_run(
        self,
        workflow_id: str,
        run_id: str,
        *,
        status: str,
        answer: str = "",
        events: list[dict] | None = None,
        message: str = "",
    ) -> AgentRunHistoryItem:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/runs/{run_id}/finish",
            json={
                "status": status,
                "answer": answer,
                "events": events or [],
                "message": message,
            },
            timeout=30.0,
        )
        if not isinstance(data, dict):
            raise ApiError("Не удалось завершить запуск агента")
        return _parse_agent_run(data, workflow_id)

    def get_agent_run(self, workflow_id: str, run_id: str) -> AgentRunHistoryItem:
        data = self._request("GET", f"/api/v1/workflows/{workflow_id}/runs/{run_id}", timeout=60.0)
        if not isinstance(data, dict):
            raise ApiError("Не удалось загрузить ход выполнения")
        return _parse_agent_run(data, workflow_id)

    def stream_trigger_check(
        self,
        trigger_id: str,
        on_event: Callable[[dict], None] | None = None,
    ) -> dict:
        url = f"{self.base_url}/api/v1/triggers/{trigger_id}/check/stream"
        final_result: dict | None = None
        run_id = ""
        try:
            with httpx.Client(timeout=None) as client:
                with client.stream(
                    "POST",
                    url,
                    headers={**self._headers(), "Accept": "text/event-stream"},
                    json={},
                ) as response:
                    if response.status_code >= 400:
                        body = response.read().decode("utf-8", errors="replace")
                        raise ApiError(body or "Ошибка проверки триггера", status_code=response.status_code)
                    data_lines: list[str] = []
                    for line in response.iter_lines():
                        if line == "":
                            if data_lines:
                                payload = _parse_sse_payload("\n".join(data_lines))
                                payload_type = str(payload.get("type") or "")
                                if payload_type == "run":
                                    run_id = str(payload.get("run_id") or "")
                                    if on_event:
                                        on_event(payload)
                                elif payload_type == "tool_request":
                                    if on_event:
                                        on_event(
                                            {
                                                "type": "status",
                                                "text": f"Проверяю условие: {payload.get('tool') or ''}…",
                                            }
                                        )
                                    Thread(
                                        target=self._handle_sse_tool_request,
                                        kwargs={
                                            "payload": payload,
                                            "fallback_run_id": run_id,
                                        },
                                        daemon=True,
                                    ).start()
                                elif payload_type in {"heartbeat", "ping"}:
                                    continue
                                elif payload_type == "error":
                                    raise ApiError(str(payload.get("message") or "Ошибка проверки триггера"))
                                elif payload_type == "done":
                                    final_result = (
                                        payload.get("result")
                                        if isinstance(payload.get("result"), dict)
                                        else {}
                                    )
                                elif on_event:
                                    on_event(payload)
                            data_lines = []
                            continue
                        if line.startswith("data:"):
                            data_lines.append(line.split(":", 1)[1].strip())
        except httpx.ConnectError as exc:
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc
        return final_result or {}

    def ack_trigger_fired(self, trigger_id: str, *, evidence: str = "") -> None:
        self._request(
            "POST",
            f"/api/v1/triggers/{trigger_id}/ack-fired",
            json={"evidence": evidence or ""},
            timeout=30.0,
        )

    def _stream_workflow(
        self,
        method: str,
        path: str,
        *,
        on_event: Callable[[str, str], None],
        json_body: dict | None = None,
        answers: dict[str, str] | None = None,
        file_paths: list[str | Path] | None = None,
        file_question_ids: list[str] | None = None,
    ) -> WorkflowRecord:
        url = f"{self.base_url}{path}"
        final_record: WorkflowRecord | None = None
        run_id = ""
        files: list = []
        handles = []
        data = None
        request_json = json_body
        paths = [Path(p) for p in (file_paths or []) if Path(p).is_file()]
        if answers is not None:
            if paths:
                qids = list(file_question_ids or [])
                while len(qids) < len(paths):
                    qids.append("")
                for file_path in paths:
                    fh = file_path.open("rb")
                    handles.append(fh)
                    files.append(("files", (file_path.name, fh, "application/octet-stream")))
                data = {
                    "answers": json.dumps(answers or {}, ensure_ascii=False),
                    "file_question_ids": json.dumps(qids[: len(paths)], ensure_ascii=False),
                }
                request_json = None
            else:
                request_json = {"answers": answers}
        last_connect: httpx.ConnectError | None = None
        try:
            for attempt in range(3):
                try:
                    with httpx.Client(timeout=None) as client:
                        with client.stream(
                            method,
                            url,
                            headers={**self._headers(), "Accept": "text/event-stream"},
                            json=request_json,
                            data=data,
                            files=files or None,
                        ) as response:
                            if response.status_code >= 400:
                                body = response.read().decode("utf-8", errors="replace")
                                raise ApiError(body or "Ошибка workflow", status_code=response.status_code)
                            for payload in _iter_sse_payloads(response):
                                payload_type = str(payload.get("type") or "")
                                if payload_type == "run":
                                    run_id = str(payload.get("run_id") or "")
                                elif payload_type == "tool_request":
                                    tool = str(payload.get("tool") or "")
                                    on_event("decision", f"Выполняю на этом компьютере: {tool}…")
                                    Thread(
                                        target=self._handle_sse_tool_request,
                                        kwargs={
                                            "payload": payload,
                                            "fallback_run_id": run_id,
                                        },
                                        daemon=True,
                                    ).start()
                                elif payload_type == "tool_result":
                                    tool = str(payload.get("tool") or "").strip()
                                    text = str(payload.get("text") or "").strip() or "Готово"
                                    on_event("tool_result", f"{tool}\n{text}" if tool else text)
                                elif payload_type in {
                                    "thinking",
                                    "assistant",
                                    "message",
                                    "decision",
                                    "system",
                                    "progress",
                                    "status",
                                }:
                                    on_event(payload_type, str(payload.get("text") or ""))
                                elif payload_type in {"heartbeat", "ping"}:
                                    continue
                                elif payload_type == "error":
                                    err = str(payload.get("message") or "Ошибка workflow")
                                    on_event("error", err)
                                    raise ApiError(err)
                                elif payload_type == "workflow" and isinstance(payload.get("workflow"), dict):
                                    final_record = self._parse_workflow(payload["workflow"])
                    last_connect = None
                    break
                except httpx.ConnectError as exc:
                    last_connect = exc
                    if attempt == 2:
                        raise ApiError(
                            f"Не удалось подключиться к backend ({self.base_url})"
                        ) from exc
                    time.sleep(0.4 * (attempt + 1))
            if last_connect is not None:
                raise ApiError(
                    f"Не удалось подключиться к backend ({self.base_url})"
                ) from last_connect
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc
        finally:
            for handle in handles:
                handle.close()
        if final_record is None:
            raise ApiError("Backend не вернул итоговый workflow")
        return final_record

    def download_workflow_artifacts(self, workflow_id: str) -> ArtifactsDownloadResult:
        import zipfile

        from app.config import DESKTOP_ROOT

        url = f"{self.base_url}/api/v1/workflows/{workflow_id}/artifacts/download"
        dest = DESKTOP_ROOT / "data" / "outputs" / workflow_id
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with httpx.Client(timeout=300.0) as client:
                response = client.post(url, headers=self._headers(), json={})
        except httpx.ConnectError as exc:
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})") from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время скачивания артефактов") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)

        zip_path = dest / "artifacts.zip"
        zip_path.write_bytes(response.content)
        extracted: list[str] = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(dest)
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    if name.lower() == "readme.txt":
                        continue
                    extracted.append(str(dest / name))
        except zipfile.BadZipFile as exc:
            raise ApiError("Backend вернул некорректный zip артефактов") from exc
        return ArtifactsDownloadResult(dest_dir=str(dest), files=extracted)

    def list_platform_files(self) -> list[WorkflowFileItem]:
        data = self._request("GET", "/api/v1/workflows/files", timeout=20.0)
        raw = data.get("files") if isinstance(data, dict) else []
        return [_parse_workflow_file_item(item) for item in raw if isinstance(item, dict)]

    def list_workflow_files(self, workflow_id: str, *, run_id: str = "") -> WorkflowFiles:
        params = {"run_id": run_id} if run_id else None
        data = self._request(
            "GET",
            f"/api/v1/workflows/{workflow_id}/files",
            params=params,
            timeout=60.0,
        )
        return _parse_workflow_files(data if isinstance(data, dict) else {})

    def upload_workflow_files(
        self,
        workflow_id: str,
        file_paths: list[str | Path],
    ) -> WorkflowFiles:
        return self._upload_workflow_files(
            f"/api/v1/workflows/{workflow_id}/files",
            file_paths,
        )

    def register_workflow_run_files(
        self,
        workflow_id: str,
        run_id: str,
        file_paths: list[str | Path],
    ) -> WorkflowFiles:
        rid = (run_id or "").strip() or "local"
        return self._upload_workflow_files(
            f"/api/v1/workflows/{workflow_id}/runs/{rid}/files",
            file_paths,
        )

    def _upload_workflow_files(self, path: str, file_paths: list[str | Path]) -> WorkflowFiles:
        url = f"{self.base_url}{path}"
        files: list = []
        handles = []
        try:
            for raw_path in file_paths:
                local = Path(raw_path)
                if not local.is_file():
                    continue
                fh = local.open("rb")
                handles.append(fh)
                files.append(("files", (local.name, fh, "application/octet-stream")))
            with httpx.Client(timeout=max(self._timeout, 180.0)) as client:
                response = client.post(url, headers=self._headers(), files=files)
        except httpx.ConnectError as exc:
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})") from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время загрузки файлов") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc
        finally:
            for handle in handles:
                handle.close()
        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        return _parse_workflow_files(response.json())

    def workflow_file_text(self, workflow_id: str, file_id: str) -> dict[str, str]:
        data = self._request(
            "GET",
            f"/api/v1/workflows/{workflow_id}/files/{file_id}/text",
            timeout=60.0,
        )
        if not isinstance(data, dict):
            return {"text": "", "summary": ""}
        return {"text": str(data.get("text") or ""), "summary": str(data.get("summary") or "")}

    def download_workflow_file_to(
        self,
        workflow_id: str,
        file_id: str,
        destination: str | Path,
    ) -> str:
        dest = Path(destination)
        url = f"{self.base_url}/api/v1/workflows/{workflow_id}/files/{file_id}/download"
        try:
            with httpx.Client(timeout=300.0) as client:
                response = client.get(url, headers=self._headers())
        except httpx.ConnectError as exc:
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})") from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время скачивания файла") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
        return str(dest)

    def update_workflow_local_run(self, workflow_id: str, local_run: dict) -> WorkflowRecord:
        data = self._request(
            "PATCH",
            f"/api/v1/workflows/{workflow_id}/local-run",
            json={"local_run": local_run},
            timeout=60.0,
        )
        return self._parse_workflow(data)

    def publish_workflow(self, workflow_id: str) -> WorkflowRecord:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/publish",
            timeout=180.0,
        )
        return self._parse_workflow(data)

    def stream_generate_workflow_kpi(
        self,
        workflow_id: str,
        on_event: Callable[[str, str], None],
    ) -> WorkflowRecord:
        return self._stream_workflow(
            "POST",
            f"/api/v1/workflows/{workflow_id}/kpi/generate/stream",
            on_event=on_event,
        )

    def get_workflow_kpi(self, workflow_id: str) -> AgentKpi:
        data = self._request("GET", f"/api/v1/workflows/{workflow_id}/kpi", timeout=60.0)
        return _parse_agent_kpi(data if isinstance(data, dict) else {})

    def confirm_workflow_kpi(self, workflow_id: str) -> WorkflowRecord:
        data = self._request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/kpi/confirm",
            timeout=180.0,
        )
        return self._parse_workflow(data)

    def _parse_workflow(self, data: dict) -> WorkflowRecord:
        plan_data = data.get("plan")
        plan = None
        if isinstance(plan_data, dict):
            steps = [
                WorkflowPlanStep(
                    id=str(s.get("id") or ""),
                    title=str(s.get("title") or ""),
                    action=str(s.get("action") or ""),
                    done_when=str(s.get("done_when") or ""),
                    depends_on=[str(x) for x in (s.get("depends_on") or [])],
                )
                for s in (plan_data.get("steps") or [])
                if isinstance(s, dict)
            ]
            questions = [
                WorkflowOpenQuestion(
                    id=str(q.get("id") or ""),
                    question=str(q.get("question") or ""),
                    why=str(q.get("why") or ""),
                    answer=str(q.get("answer") or ""),
                    options=[str(x) for x in q.get("options") or []],
                )
                for q in (plan_data.get("open_questions") or [])
                if isinstance(q, dict)
            ]
            plan = WorkflowPlan(
                title=str(plan_data.get("title") or ""),
                goal=str(plan_data.get("goal") or ""),
                constraints=[str(x) for x in (plan_data.get("constraints") or [])],
                out_of_scope=[str(x) for x in (plan_data.get("out_of_scope") or [])],
                steps=steps,
                test_criteria=[str(x) for x in (plan_data.get("test_criteria") or [])],
                open_questions=questions,
                raw_text=str(plan_data.get("raw_text") or ""),
            )
        attachments = [
            WorkflowAttachment(
                name=str(a.get("name") or ""),
                kind=str(a.get("kind") or "text"),
                mime_type=str(a.get("mime_type") or ""),
                stored_name=str(a.get("stored_name") or ""),
                text_preview=str(a.get("text_preview") or ""),
            )
            for a in (data.get("attachments") or [])
            if isinstance(a, dict)
        ]
        return WorkflowRecord(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or "Без названия"),
            phase=str(data.get("phase") or "document"),
            notes=str(data.get("notes") or ""),
            document_name=str(data.get("document_name") or ""),
            document_text=str(data.get("document_text") or ""),
            plan=plan,
            attachments=attachments,
            local_run=dict(data.get("local_run") or {}),
            plan_agent_id=str(data.get("plan_agent_id") or ""),
            plan_run_id=str(data.get("plan_run_id") or ""),
            exec_agent_id=str(data.get("exec_agent_id") or ""),
            exec_run_id=str(data.get("exec_run_id") or ""),
            last_result=str(data.get("last_result") or ""),
            branch=str(data.get("branch") or ""),
            pr_url=str(data.get("pr_url") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )

    @staticmethod
    def _parse_user(data: dict) -> UserProfile:
        avatar = data.get("avatar_url")
        available_raw = data.get("department_change_available_at")
        available_at: datetime | None = None
        if isinstance(available_raw, str) and available_raw.strip():
            try:
                available_at = datetime.fromisoformat(available_raw.replace("Z", "+00:00"))
            except ValueError:
                available_at = None
        return UserProfile(
            id=str(data.get("id", "")),
            fio=str(data.get("fio", "")),
            department=str(data.get("department", "")),
            position=str(data.get("position", "")),
            avatar_url=str(avatar) if avatar else None,
            can_change_department=bool(data.get("can_change_department", True)),
            department_change_available_at=available_at,
            activity_status=str(data.get("activity_status") or "online"),
            is_support=bool(data.get("is_support")),
        )

    def invoke_server_tool(
        self,
        name: str,
        arguments: dict | None = None,
        *,
        timeout: float = 90.0,
    ) -> dict:
        data = self._request(
            "POST",
            f"/api/v1/tools/{name}/invoke",
            json={"arguments": arguments or {}},
            timeout=timeout,
        )
        if not isinstance(data, dict):
            return {}
        result = data.get("result")
        return result if isinstance(result, dict) else {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        timeout: float | None = None,
    ):
        url = f"{self.base_url}{path}"
        last_connect: httpx.ConnectError | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=timeout or self._timeout) as client:
                    response = client.request(
                        method,
                        url,
                        json=json,
                        params=params,
                        headers=self._headers(),
                    )
                last_connect = None
                break
            except httpx.ConnectError as exc:
                last_connect = exc
                if attempt == 2:
                    raise ApiError(
                        f"Не удалось подключиться к backend ({self.base_url})"
                    ) from exc
                time.sleep(0.4 * (attempt + 1))
            except httpx.TimeoutException as exc:
                raise ApiError("Превышено время ожидания ответа backend") from exc
            except httpx.HTTPError as exc:
                raise ApiError(f"Ошибка сети: {exc}") from exc
        if last_connect is not None:
            raise ApiError(
                f"Не удалось подключиться к backend ({self.base_url})"
            ) from last_connect

        if response.status_code >= 400:
            detail = _extract_detail(response)
            raise ApiError(detail, status_code=response.status_code)

        if not response.content:
            return {}
        return response.json()

    @staticmethod
    def _parse_regulation(data: dict) -> RegulationParseResult:
        fragments: list[RegulationFragment] = []
        for item in data.get("fragments") or []:
            table_data = item.get("table") if isinstance(item, dict) else None
            table = None
            if isinstance(table_data, dict):
                table = RegulationTable(
                    headers=[str(x) for x in table_data.get("headers") or []],
                    rows=[
                        [str(cell) for cell in row]
                        for row in table_data.get("rows") or []
                        if isinstance(row, list)
                    ],
                )
            fragments.append(
                RegulationFragment(
                    fragment_id=str(item.get("fragmentId", "")),
                    page=int(item.get("page") or 1),
                    section=str(item.get("section") or ""),
                    kind=str(item.get("kind") or "text"),
                    text=str(item.get("text") or ""),
                    table=table,
                    ocr_confidence=float(item.get("ocrConfidence") or 0.0),
                    section_path=[str(x) for x in item.get("sectionPath") or []],
                    block_type=str(item.get("blockType") or "paragraph"),
                    table_headers=[str(x) for x in item.get("tableHeaders") or []],
                    cells={str(k): str(v) for k, v in (item.get("cells") or {}).items()},
                    row_index=int(item["rowIndex"]) if item.get("rowIndex") is not None else None,
                    bbox=[float(x) for x in item.get("bbox") or []] or None,
                    location=item.get("location") if isinstance(item.get("location"), dict) else {},
                    style=str(item.get("style") or ""),
                    content_hash=str(item.get("contentHash") or ""),
                )
            )
        return RegulationParseResult(
            regulation_id=str(data.get("regulationId", "")),
            file_name=str(data.get("fileName", "")),
            page_count=int(data.get("pageCount") or 0),
            table_count=int(data.get("tableCount") or 0),
            section_count=int(data.get("sectionCount") or 0),
            recognition_quality=float(data.get("recognitionQuality") or 0.0),
            is_scan=bool(data.get("isScan")),
            sections=[str(x) for x in data.get("sections") or []],
            fragments=fragments,
        )

    @staticmethod
    def _parse_creation_session(data: dict) -> RegulationCreationSession:
        result_raw = data.get("resultRegulation")
        return RegulationCreationSession(
            draft_id=str(data.get("draftId") or ""),
            status=str(data.get("status") or ""),
            cursor_agent_id=str(data.get("cursorAgentId") or ""),
            latest_run_id=str(data.get("latestRunId") or ""),
            positions=[str(item) for item in data.get("positions") or []],
            messages=[
                RegulationCreationMessage(
                    message_id=str(item.get("messageId") or ""),
                    draft_id=str(item.get("draftId") or ""),
                    role=str(item.get("role") or ""),
                    content=str(item.get("content") or ""),
                    structured=item.get("structured") if isinstance(item.get("structured"), dict) else {},
                )
                for item in data.get("messages") or []
                if isinstance(item, dict)
            ],
            result_regulation=ApiClient._parse_regulation(result_raw) if isinstance(result_raw, dict) else None,
            result_document=data.get("resultDocument") if isinstance(data.get("resultDocument"), dict) else {},
            result_document_path=str(data.get("resultDocumentPath") or ""),
        )

    @staticmethod
    def _parse_fragment(item: dict) -> RegulationFragment:
        table_data = item.get("table") if isinstance(item, dict) else None
        table = None
        if isinstance(table_data, dict):
            table = RegulationTable(
                headers=[str(x) for x in table_data.get("headers") or []],
                rows=[
                    [str(cell) for cell in row]
                    for row in table_data.get("rows") or []
                    if isinstance(row, list)
                ],
            )
        return RegulationFragment(
            fragment_id=str(item.get("fragmentId", "")),
            page=int(item.get("page") or 1),
            section=str(item.get("section") or ""),
            kind=str(item.get("kind") or "text"),
            text=str(item.get("text") or ""),
            table=table,
            ocr_confidence=float(item.get("ocrConfidence") or 0.0),
            section_path=[str(x) for x in item.get("sectionPath") or []],
            block_type=str(item.get("blockType") or "paragraph"),
            table_headers=[str(x) for x in item.get("tableHeaders") or []],
            cells={str(k): str(v) for k, v in (item.get("cells") or {}).items()},
            row_index=int(item["rowIndex"]) if item.get("rowIndex") is not None else None,
            bbox=[float(x) for x in item.get("bbox") or []] or None,
            location=item.get("location") if isinstance(item.get("location"), dict) else {},
            style=str(item.get("style") or ""),
            content_hash=str(item.get("contentHash") or ""),
        )

    @staticmethod
    def _parse_role_matches(data: dict) -> RoleMatchResult:
        matches: list[RoleMatch] = []
        for item in data.get("matches") or []:
            fragment = ApiClient._parse_fragment(item.get("fragment") or {})
            signals = [
                MatchSignal(
                    match_type=str(signal.get("matchType") or ""),
                    confidence=float(signal.get("confidence") or 0.0),
                    quote=str(signal.get("quote") or ""),
                    explanation=str(signal.get("explanation") or ""),
                )
                for signal in item.get("signals") or []
                if isinstance(signal, dict)
            ]
            function = ApiClient._parse_role_function(item.get("function"))
            matches.append(
                RoleMatch(
                    match_id=str(item.get("matchId") or ""),
                    fragment_id=str(item.get("fragmentId") or ""),
                    relation=str(item.get("relation") or "none"),
                    match_types=[str(x) for x in item.get("matchTypes") or []],
                    confidence=float(item.get("confidence") or 0.0),
                    model_confidence=float(item.get("modelConfidence") or 0.0),
                    explanation=str(item.get("explanation") or ""),
                    requires_confirmation=bool(item.get("requiresUserConfirmation")),
                    status=str(item.get("status") or "pending"),
                    fragment=fragment,
                    signals=signals,
                    function=function,
                )
            )
        profile = data.get("profile") or {}
        return RoleMatchResult(
            run_id=str(data.get("runId") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            canonical_title=str(profile.get("canonicalTitle") or ""),
            department=str(profile.get("department") or ""),
            matches=matches,
            functions=[
                parsed
                for parsed in (ApiClient._parse_role_function(item) for item in data.get("functions") or [])
                if parsed is not None
            ],
            audit=data.get("audit") if isinstance(data.get("audit"), dict) else {},
        )

    @staticmethod
    def _parse_role_function(data: object) -> RoleFunction | None:
        if not isinstance(data, dict):
            return None
        actor_data = data.get("actor") if isinstance(data.get("actor"), dict) else {}
        actor = FunctionActor(
            text=str(actor_data.get("text") or ""),
            canonical_position=str(actor_data.get("canonicalPosition") or ""),
            source_block_id=str(actor_data.get("sourceBlockId") or ""),
        )
        dependencies = [
            FunctionDependency(
                type=str(item.get("type") or ""),
                block_id=str(item.get("blockId") or ""),
                description=str(item.get("description") or ""),
            )
            for item in data.get("dependencies") or []
            if isinstance(item, dict)
        ]
        evidence = [
            MatchEvidence(
                fragment_id=str(item.get("fragmentId") or item.get("blockId") or ""),
                quote=str(item.get("quote") or ""),
            )
            for item in data.get("evidence") or []
            if isinstance(item, dict)
        ]
        proof_chain = [
            ContextLinkedBlock(
                block_id=str(item.get("blockId") or ""),
                relation=str(item.get("relation") or ""),
                text=str(item.get("text") or ""),
                evidence=str(item.get("evidence") or ""),
                confidence=float(item.get("confidence") or 0.0),
            )
            for item in data.get("proofChain") or []
            if isinstance(item, dict)
        ]
        return RoleFunction(
            function_id=str(data.get("functionId") or ""),
            target_block_id=str(data.get("targetBlockId") or ""),
            is_function=bool(data.get("isFunction")),
            title=str(data.get("title") or ""),
            actor=actor,
            action=str(data.get("action") or ""),
            object=str(data.get("object") or ""),
            recipient=str(data.get("recipient") or ""),
            conditions=[str(x) for x in data.get("conditions") or []],
            dependencies=dependencies,
            evidence=evidence,
            proof_chain=proof_chain,
            explanation=str(data.get("explanation") or ""),
            confidence=float(data.get("confidence") or 0.0),
            duplicate_group=str(data.get("duplicateGroup") or ""),
            requires_confirmation=bool(data.get("requiresUserConfirmation")),
        )

    @staticmethod
    def _parse_readiness(data: dict) -> AgentReadinessResult:
        questions = [
            ReadinessQuestion(
                question_id=str(item.get("questionId") or ""),
                function_id=str(item.get("functionId") or ""),
                target_field=str(item.get("targetField") or ""),
                severity=str(item.get("severity") or ""),
                question=str(item.get("question") or ""),
                reason=str(item.get("reason") or ""),
                answer_type=str(item.get("answerType") or "text"),
                options=[str(x) for x in item.get("options") or []],
                affected_blocks=[str(x) for x in item.get("affectedBlocks") or []],
                answered=bool(item.get("answered")),
                answer=str(item.get("answer") or ""),
            )
            for item in data.get("questions") or []
            if isinstance(item, dict)
        ]
        changes = [
            ReadinessChange(
                change_id=str(item.get("changeId") or ""),
                source=item.get("source") if isinstance(item.get("source"), dict) else {},
                operation=str(item.get("operation") or ""),
                target_block_id=str(item.get("targetBlockId") or ""),
                before=str(item.get("before") or ""),
                after=str(item.get("after") or ""),
                reason=str(item.get("reason") or ""),
                affected_functions=[str(x) for x in item.get("affectedFunctions") or []],
                affected_blocks=[str(x) for x in item.get("affectedBlocks") or []],
                status=str(item.get("status") or "pending"),
            )
            for item in data.get("changes") or []
            if isinstance(item, dict)
        ]
        return AgentReadinessResult(
            readiness_run_id=str(data.get("readinessRunId") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            role_match_run_id=str(data.get("roleMatchRunId") or ""),
            score=int(data.get("score") or 0),
            blocking=[str(x) for x in data.get("blocking") or []],
            important=[str(x) for x in data.get("important") or []],
            optional=[str(x) for x in data.get("optional") or []],
            questions=questions,
            changes=changes,
            status=str(data.get("status") or ""),
        )

    @staticmethod
    def _parse_agent_draft(data: dict) -> AgentDraft:
        readiness_raw = data.get("readiness")
        updated_at = _parse_datetime(data.get("updatedAt"))
        created_at = _parse_datetime(data.get("createdAt"))
        suggestions = [
            ApiClient._parse_agent_suggestion(item)
            for item in data.get("agentSuggestions") or []
            if isinstance(item, dict)
        ]
        return AgentDraft(
            draft_id=str(data.get("draftId") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            role_match_run_id=str(data.get("roleMatchRunId") or ""),
            readiness_run_id=str(data.get("readinessRunId") or ""),
            title=str(data.get("title") or ""),
            position=str(data.get("position") or ""),
            department=str(data.get("department") or ""),
            status=str(data.get("status") or "draft"),
            progress=int(data.get("progress") or 0),
            readiness=ApiClient._parse_readiness(readiness_raw) if isinstance(readiness_raw, dict) else None,
            agent_suggestions=suggestions,
            updated_at=updated_at,
            created_at=created_at,
        )

    @staticmethod
    def _parse_question_chat(data: dict) -> QuestionChatSession:
        messages = [
            QuestionChatMessage(
                message_id=str(item.get("messageId") or ""),
                session_id=str(item.get("sessionId") or ""),
                role=str(item.get("role") or ""),
                content=str(item.get("content") or ""),
                structured=item.get("structured") if isinstance(item.get("structured"), dict) else {},
            )
            for item in data.get("messages") or []
            if isinstance(item, dict)
        ]
        return QuestionChatSession(
            session_id=str(data.get("sessionId") or ""),
            draft_id=str(data.get("draftId") or ""),
            readiness_run_id=str(data.get("readinessRunId") or ""),
            question_id=str(data.get("questionId") or ""),
            function_id=str(data.get("functionId") or ""),
            target_field=str(data.get("targetField") or ""),
            status=str(data.get("status") or ""),
            context=data.get("context") if isinstance(data.get("context"), dict) else {},
            messages=messages,
        )


def _extract_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                msg = first.get("msg") or first.get("message")
                if msg:
                    return str(msg)
            return str(first)
        if isinstance(detail, dict):
            msg = detail.get("msg") or detail.get("message")
            if msg:
                return str(msg)
    except Exception:
        body = response.text.strip()
        if body:
            return body
    if response.status_code == 401:
        return "Неверный логин или пароль"
    return f"Ошибка сервера ({response.status_code})"


def _iter_sse_payloads(response: httpx.Response):
    """Разбирать SSE по байтам, чтобы think не ждал конца ответа."""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    data_lines: list[str] = []
    carry = ""

    def feed(text: str):
        nonlocal data_lines, carry
        carry += text
        while "\n" in carry:
            line, carry = carry.split("\n", 1)
            line = line.rstrip("\r")
            if line == "":
                if data_lines:
                    yield _parse_sse_payload("\n".join(data_lines))
                data_lines = []
                continue
            if line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())

    for raw in response.iter_bytes(chunk_size=4096):
        if not raw:
            continue
        yield from feed(decoder.decode(raw, final=False))
    yield from feed(decoder.decode(b"", final=True))
    if data_lines:
        yield _parse_sse_payload("\n".join(data_lines))


def _parse_sse_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"type": "message", "text": raw}
    return payload if isinstance(payload, dict) else {"type": "message", "text": raw}


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
