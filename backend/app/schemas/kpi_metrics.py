from __future__ import annotations

from pydantic import BaseModel, Field

from platform_contracts.agent_card import AgentKpiMetricSpec


class KpiMetricTemplate(BaseModel):
    metric_id: str
    title: str
    kind: str = "rate"
    source: str = "agent_task_reports"
    threshold_min: float | None = None
    threshold_max: float | None = None
    weight: float = 1.0
    description: str = ""


class AgentCardKpiOut(BaseModel):
    agent_id: str
    title: str
    department: str = ""
    kpi_metrics: list[AgentKpiMetricSpec] = Field(default_factory=list)


class AgentCardKpiListResponse(BaseModel):
    items: list[AgentCardKpiOut] = Field(default_factory=list)


class KpiMetricTemplateListResponse(BaseModel):
    items: list[KpiMetricTemplate] = Field(default_factory=list)


class UpdateAgentKpiMetricsRequest(BaseModel):
    kpi_metrics: list[AgentKpiMetricSpec] = Field(default_factory=list)


class UpdateAgentCardTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
