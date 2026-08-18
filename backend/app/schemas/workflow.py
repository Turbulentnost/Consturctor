from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlanStepSchema(BaseModel):
    id: str = ""
    title: str = ""
    action: str = ""
    done_when: str = ""
    depends_on: list[str] = Field(default_factory=list)


class OpenQuestionSchema(BaseModel):
    id: str = ""
    question: str = ""
    why: str = ""
    answer: str = ""
    options: list[str] = Field(default_factory=list)


class WorkflowPlanSchema(BaseModel):
    title: str = ""
    goal: str = ""
    constraints: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    steps: list[PlanStepSchema] = Field(default_factory=list)
    test_criteria: list[str] = Field(default_factory=list)
    open_questions: list[OpenQuestionSchema] = Field(default_factory=list)
    answered_questions: list[OpenQuestionSchema] = Field(default_factory=list)
    raw_text: str = ""
    runtime: dict[str, Any] = Field(default_factory=dict)


class AttachmentMetaSchema(BaseModel):
    name: str
    kind: str = "text"
    mime_type: str = ""
    stored_name: str = ""
    text_preview: str = ""


class WorkflowSchema(BaseModel):
    id: str
    title: str
    phase: str
    notes: str = ""
    document_name: str = ""
    document_text: str = ""
    plan: WorkflowPlanSchema | None = None
    attachments: list[AttachmentMetaSchema] = Field(default_factory=list)
    local_run: dict[str, Any] = Field(default_factory=dict)
    plan_agent_id: str = ""
    plan_run_id: str = ""
    exec_agent_id: str = ""
    exec_run_id: str = ""
    last_result: str = ""
    branch: str = ""
    pr_url: str = ""
    created_at: str = ""
    updated_at: str = ""


class WorkflowListItem(BaseModel):
    id: str
    title: str
    phase: str
    document_name: str = ""
    updated_at: str = ""
    has_local_run: bool = False
    auto_run: bool = False


class AutoRunStopResult(BaseModel):
    ok: bool = True
    stopped: int = 0


class ClarifyRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class ExecuteRequest(BaseModel):
    reexecute: bool = False


class LocalRunUpdate(BaseModel):
    local_run: dict[str, Any] = Field(default_factory=dict)


class ArtifactItem(BaseModel):
    path: str
    size: int | None = None


class ArtifactsDownloadRequest(BaseModel):
    paths: list[str] | None = None


class ArtifactsDownloadResult(BaseModel):
    dest_dir: str
    files: list[str] = Field(default_factory=list)


class WorkflowHealth(BaseModel):
    ok: bool
    who: str = ""
    message: str = ""


class WebSearchRequest(BaseModel):
    query: str
    max_results: int = 5
    fetch_top: bool = False


class WebSearchResultItem(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""


class WebSearchResponse(BaseModel):
    query: str
    results: list[WebSearchResultItem] = Field(default_factory=list)
    extracted_text: str = ""


class AgentToolResultSubmit(BaseModel):
    request_id: str
    ok: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class AgentRunOut(BaseModel):
    id: str
    workflow_id: str
    message: str = ""
    status: str = "started"
    answer: str = ""
    source: str = "chat"
    started_at: str = ""
    finished_at: str = ""


class KpiMeasureSchema(BaseModel):
    kind: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    formula: str = ""


class KpiSideSchema(BaseModel):
    label: str = ""
    value: float | None = None
    unit: str = ""
    description: str = ""


class KpiScheduleSchema(BaseModel):
    kind: str = "interval"
    interval_seconds: int = 3600
    at: str = ""


class KpiMethodSchema(BaseModel):
    how: str = ""
    when: str = ""
    plan_update: str = ""
    fact_update: str = ""
    percent_formula: str = ""
    green_min: float = 90
    yellow_min: float = 70
    schedule: KpiScheduleSchema = Field(default_factory=KpiScheduleSchema)


class KpiTileSchema(BaseModel):
    id: str = ""
    name: str = ""
    plan: KpiSideSchema = Field(default_factory=KpiSideSchema)
    fact: KpiSideSchema = Field(default_factory=KpiSideSchema)
    measure: KpiMeasureSchema = Field(default_factory=KpiMeasureSchema)
    score_percent: float | None = None
    color: str = "none"
    updated_at: str = ""
    next_run_at: str = ""
    evidence: str = ""
    method: KpiMethodSchema = Field(default_factory=KpiMethodSchema)


class AgentKpiSchema(BaseModel):
    status: str = "draft"
    generated_at: str = ""
    summary: str = ""
    tiles: list[KpiTileSchema] = Field(default_factory=list)
    workflow_id: str = ""
    title: str = ""
