from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentTaskSpec(BaseModel):
    """Бизнес-задача агента. Не привязана к инструментам платформы."""

    task_id: str
    title: str = ""
    description: str = ""
    evaluation_criteria: dict[str, Any] = Field(default_factory=dict)
    kpi_tags: list[str] = Field(default_factory=list)


class AgentKpiMetricSpec(BaseModel):
    """Метрика оценки работы агента (по task report / review), не по tool invoke."""

    metric_id: str
    title: str = ""
    kind: str = "rate"
    source: str = "agent_task_reports"
    threshold_min: float | None = None
    threshold_max: float | None = None
    weight: float = 1.0
    task_ids: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    """Карточка внешнего агента: его задачи и критерии оценки."""

    agent_id: str
    title: str
    version: str = "1.0"
    description: str = ""
    department: str = ""
    tasks: list[AgentTaskSpec] = Field(default_factory=list)
    kpi_metrics: list[AgentKpiMetricSpec] = Field(default_factory=list)
    interaction_mode: str = "pull"
    callback_url: str | None = None
    enabled: bool = True


class AgentSessionStart(BaseModel):
    """Внешний агент открывает сессию работы с платформой."""

    agent_id: str
    external_session_id: str = ""
    department: str = ""
    user_id: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


class AgentSessionStatus(BaseModel):
    session_id: str
    agent_id: str
    status: str = "active"
    run_id: str | None = None


class AgentTaskReport(BaseModel):
    """Отчёт агента о выполненной бизнес-задаче — основа KPI."""

    agent_id: str
    task_id: str
    status: str
    session_id: str | None = None
    run_id: str | None = None
    quality_score: float | None = None
    summary: str = ""
    outcome: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
