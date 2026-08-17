from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, Field


class AccessLevel(IntEnum):
    """Уровень доступа агента (1 — минимальный, 4 — максимальный)."""

    L1_OBSERVER = 1
    L2_LIMITED_WRITE = 2
    L3_CONTROLLED_AUTONOMY = 3
    L4_FULL = 4


class AccessLevelSpec(BaseModel):
    level: int
    title: str
    summary: str
    capabilities: list[str] = Field(default_factory=list)
    hitl_required: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class AccessLevelTransitionPolicy(BaseModel):
    """Пороги KPI для перехода между уровнями (недельная точность, %)."""

    promote_threshold: float = Field(default=80.0, ge=0, le=100)
    demote_threshold: float = Field(default=60.0, ge=0, le=100)
    evaluation_window_days: int = Field(default=7, ge=1)


class AgentAccessState(BaseModel):
    agent_id: str
    access_level: int = Field(default=1, ge=1, le=4)
    weekly_accuracy_pct: float = Field(default=0.0, ge=0, le=100)
    week_index: int = Field(default=1, ge=1)
    promote_offered: bool = False
    policy: AccessLevelTransitionPolicy = Field(default_factory=AccessLevelTransitionPolicy)


DEFAULT_ACCESS_LEVELS: list[AccessLevelSpec] = [
    AccessLevelSpec(
        level=1,
        title="Уровень 1 — наблюдатель",
        summary="Генерация текста, инструменты чтения и human-in-the-loop.",
        capabilities=["Генерация текста", "Инструменты чтения"],
        hitl_required=["Все остальные операции — только после подтверждения человека"],
    ),
    AccessLevelSpec(
        level=2,
        title="Уровень 2 — ограниченная запись",
        summary="Возможности уровня 1 и разрешённые инструменты записи без подтверждения.",
        capabilities=["Всё из уровня 1", "Разрешённые инструменты записи (без HITL)"],
        forbidden=["Запись, изменение и удаление данных в 1С"],
    ),
    AccessLevelSpec(
        level=3,
        title="Уровень 3 — контролируемая автономия",
        summary="Запись/редактирование/удаление и массовая рассылка; код и PowerShell — с HITL.",
        capabilities=[
            "Всё из уровня 2",
            "Запись, редактирование, удаление",
            "Массовая рассылка",
        ],
        hitl_required=["Написание и запуск кода", "Команды PowerShell"],
    ),
    AccessLevelSpec(
        level=4,
        title="Уровень 4 — полный доступ",
        summary="Все реализованные инструменты без HITL, кроме прав сотрудника и системных политик.",
        capabilities=["Все реализованные инструменты без подтверждения"],
        hitl_required=["Ограничения прав конкретного сотрудника", "Системные политики"],
    ),
]
