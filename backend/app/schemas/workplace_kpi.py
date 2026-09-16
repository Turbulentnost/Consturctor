from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KpiValueSource = Literal["reference", "computed"]


class WorkplaceModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class WorkplaceKpiCardOut(WorkplaceModel):
    id: str
    label: str
    display_value: str = Field(serialization_alias="displayValue")
    trend: str | None = None
    progress: int | None = None
    ring: bool = True
    tone: str = "blue"
    source: KpiValueSource = "reference"


class WorkplaceKpiAgentRowOut(WorkplaceModel):
    id: str
    code: str
    name: str
    process: str
    completion_pct: int = Field(serialization_alias="completionPct")
    sla_pct: int = Field(serialization_alias="slaPct")
    load_pct: int = Field(serialization_alias="loadPct")
    automation_pct: int = Field(serialization_alias="automationPct")
    status: str
    status_tone: str = Field(serialization_alias="statusTone")
    source: KpiValueSource = "reference"


class WorkplaceKpiEmployeeMetricOut(WorkplaceModel):
    id: str
    title: str
    display_value: str = Field(serialization_alias="displayValue")
    trend_delta: str = Field(serialization_alias="trendDelta", default="")
    trend_up: bool = Field(serialization_alias="trendUp", default=True)
    trend_positive: bool = Field(serialization_alias="trendPositive", default=True)
    footer_text: str = Field(serialization_alias="footerText", default="")
    sparkline_points: list[float] = Field(serialization_alias="sparklinePoints", default_factory=list)
    sparkline_color: str = Field(serialization_alias="sparklineColor", default="#1565c0")
    source: KpiValueSource = "reference"


class WorkplaceKpiProblemZoneOut(WorkplaceModel):
    id: str
    zone: str = ""
    metric: str = ""
    value: str = ""
    severity: str = "orange"
    recommendation: str = ""
    type_id: str = Field(serialization_alias="typeId", default="")
    type_label: str = Field(serialization_alias="typeLabel", default="")
    description: str = ""
    process: str = ""
    indicator: str = ""
    current_value: str = Field(serialization_alias="currentValue", default="")
    target_value: str = Field(serialization_alias="targetValue", default="")
    deviation: str = ""
    status: str = "Требует внимания"
    status_tone: str = Field(serialization_alias="statusTone", default="orange")
    source: KpiValueSource = "reference"


class WorkplaceKpiCompareRowOut(WorkplaceModel):
    id: str
    label: str
    employee: int
    ai: int
    source: KpiValueSource = "reference"


class WorkplaceKpiChartSeriesOut(WorkplaceModel):
    id: str
    label: str
    color: str
    points: list[float]


class WorkplaceKpiDynamicsOut(WorkplaceModel):
    title: str
    x_labels: list[str] = Field(serialization_alias="xLabels")
    y_max: int = Field(serialization_alias="yMax")
    series: list[WorkplaceKpiChartSeriesOut]
    source: KpiValueSource = "reference"


class WorkplaceKpiDailyMetricIn(WorkplaceModel):
    day: str
    tasks_pct: int = Field(alias="tasksPct", ge=0, le=100)
    sla_pct: int = Field(alias="slaPct", ge=0, le=100)


class WorkplaceKpiDailySyncIn(WorkplaceModel):
    metrics: list[WorkplaceKpiDailyMetricIn] = Field(default_factory=list)


class WorkplaceKpiDashboardOut(WorkplaceModel):
    period_from: str = Field(serialization_alias="periodFrom")
    period_to: str = Field(serialization_alias="periodTo")
    period_label: str = Field(serialization_alias="periodLabel")
    cards: list[WorkplaceKpiCardOut]
    agents: list[WorkplaceKpiAgentRowOut]
    employee_kpi: list[WorkplaceKpiEmployeeMetricOut] = Field(
        serialization_alias="employeeKpi", default_factory=list
    )
    problem_zones: list[WorkplaceKpiProblemZoneOut] = Field(serialization_alias="problemZones")
    workload_compare: list[WorkplaceKpiCompareRowOut] = Field(serialization_alias="workloadCompare")
    dynamics: WorkplaceKpiDynamicsOut
    generated_at: str = Field(serialization_alias="generatedAt")
