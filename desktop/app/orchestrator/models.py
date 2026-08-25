from __future__ import annotations

from dataclasses import dataclass, field

READY = "READY"
ACTIVE = "ACTIVE"
WAITING_HUMAN = "WAITING_HUMAN"
PAUSED = "PAUSED"
COMPLETED = "COMPLETED"
ERROR = "ERROR"

STATUS_LABELS = {
    READY: "Готов к запуску",
    ACTIVE: "Выполняется",
    WAITING_HUMAN: "Ждёт решения",
    PAUSED: "Пауза",
    COMPLETED: "Завершён",
    ERROR: "Ошибка",
}

REVISION_ID = "revision_commission"
MEETING_ID = "meeting_prep"


@dataclass(frozen=True)
class ProcessDefinition:
    id: str
    title: str


DEFINITIONS: tuple[ProcessDefinition, ...] = (
    ProcessDefinition(REVISION_ID, "Работа ревизионной комиссии"),
    ProcessDefinition(MEETING_ID, "Подготовка совещания"),
)


@dataclass
class ProcessInstance:
    id: str
    definition_id: str
    status: str
    waiting: int = 0
    updated_at: str = ""
    events: list[dict] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)
