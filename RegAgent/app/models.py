from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

CardPhase = Literal[
    "intake",
    "review",
    "functions",
    "readiness",
    "passport",
    "design",
    "demo",
    "schedule",
    "published",
    "failed",
]

PHASES: tuple[CardPhase, ...] = (
    "intake",
    "review",
    "functions",
    "readiness",
    "passport",
    "design",
    "demo",
    "schedule",
    "published",
    "failed",
)


class ClarificationQuestion(BaseModel):
    id: str
    question: str
    options: list[str] = Field(default_factory=list)
    allow_free_text: bool = True


class UiAction(BaseModel):
    id: str
    label: str
    hint: str = ""
    prompt: str
    tools_hint: list[str] = Field(default_factory=list)


class ChatCommand(BaseModel):
    command: str
    description: str = ""


class UiSpec(BaseModel):
    version: int = 1
    title: str = "ИИ-агент"
    summary: str = ""
    rules_prompt: str = ""
    needs_clarification: list[ClarificationQuestion] = Field(default_factory=list)
    actions: list[UiAction] = Field(default_factory=list)
    chat_commands: list[ChatCommand] = Field(default_factory=list)


class FunctionGroup(BaseModel):
    id: str
    title: str
    summary: str = ""
    operations: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    system: str = ""
    entity: str = ""


class FunctionsData(BaseModel):
    groups: list[FunctionGroup] = Field(default_factory=list)
    selected_group_id: str = ""
    title: str = ""
    summary: str = ""


class PassportField(BaseModel):
    id: str
    label: str
    value: str = ""
    required: bool = True


class PassportData(BaseModel):
    title: str = ""
    goal: str = ""
    summary: str = ""
    system: str = ""
    entity: str = ""
    operations: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    fields: list[PassportField] = Field(default_factory=list)
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    answered: dict[str, str] = Field(default_factory=dict)


class PlaybookStep(BaseModel):
    id: str
    title: str = ""
    action: str = ""
    tool: str = ""
    done_when: str = ""


class PlaybookDraft(BaseModel):
    status: str = "draft"  # draft | verified | failed
    steps: list[PlaybookStep] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    raw: str = ""
    errors: list[str] = Field(default_factory=list)


class Playbook(BaseModel):
    version: int = 1
    steps: list[PlaybookStep] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    goal: str = ""


class DemoStep(BaseModel):
    id: str
    title: str = ""
    ok: bool = False
    detail: str = ""


class DemoState(BaseModel):
    ok: bool = False
    verified: bool = False
    steps: list[DemoStep] = Field(default_factory=list)
    transcript: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class TriggersConfig(BaseModel):
    enabled: bool = False
    items: list[dict[str, Any]] = Field(default_factory=list)


class KpiConfig(BaseModel):
    enabled: bool = False
    metrics: list[dict[str, Any]] = Field(default_factory=list)


class Card(BaseModel):
    id: str = Field(default_factory=lambda: f"card-{uuid4().hex[:12]}")
    title: str = ""
    summary: str = ""
    regulation_path: str = ""
    regulation_text: str = ""
    ui_spec: UiSpec = Field(default_factory=UiSpec)
    rules_prompt: str = ""
    cursor_agent_id: str = ""
    workspace_dir: str = ""
    phase: CardPhase = "intake"
    functions: FunctionsData = Field(default_factory=FunctionsData)
    passport: PassportData = Field(default_factory=PassportData)
    playbook_draft: PlaybookDraft = Field(default_factory=PlaybookDraft)
    playbook: Playbook = Field(default_factory=Playbook)
    demo: DemoState = Field(default_factory=DemoState)
    triggers: TriggersConfig = Field(default_factory=TriggersConfig)
    kpi: KpiConfig = Field(default_factory=KpiConfig)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    @property
    def is_published(self) -> bool:
        return self.phase == "published"

    @property
    def is_draft(self) -> bool:
        return self.phase not in {"published", "failed"}

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Card:
        import json

        def _load_json(key: str, default: dict[str, Any]) -> dict[str, Any]:
            raw = row.get(key) or "{}"
            if isinstance(raw, str):
                return json.loads(raw) if raw.strip() else default
            return raw if isinstance(raw, dict) else default

        ui_data = _load_json("ui_spec_json", {})
        phase = str(row.get("phase") or "intake")
        if phase not in PHASES:
            phase = "intake"
        return cls(
            id=str(row["id"]),
            title=str(row.get("title") or ""),
            summary=str(row.get("summary") or ""),
            regulation_path=str(row.get("regulation_path") or ""),
            regulation_text=str(row.get("regulation_text") or ""),
            ui_spec=UiSpec.model_validate(ui_data),
            rules_prompt=str(row.get("rules_prompt") or ""),
            cursor_agent_id=str(row.get("cursor_agent_id") or ""),
            workspace_dir=str(row.get("workspace_dir") or ""),
            phase=phase,  # type: ignore[arg-type]
            functions=FunctionsData.model_validate(_load_json("functions_json", {})),
            passport=PassportData.model_validate(_load_json("passport_json", {})),
            playbook_draft=PlaybookDraft.model_validate(_load_json("playbook_draft_json", {})),
            playbook=Playbook.model_validate(_load_json("playbook_json", {})),
            demo=DemoState.model_validate(_load_json("demo_json", {})),
            triggers=TriggersConfig.model_validate(_load_json("triggers_json", {})),
            kpi=KpiConfig.model_validate(_load_json("kpi_json", {})),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )


def can_publish(card: Card) -> bool:
    return card.playbook_draft.status == "verified" and card.demo.ok is True


def phase_page_name(phase: CardPhase) -> str:
    mapping: dict[CardPhase, str] = {
        "intake": "create",
        "review": "review",
        "functions": "process",
        "readiness": "passport",
        "passport": "passport",
        "design": "demo",
        "demo": "demo",
        "schedule": "schedule",
        "published": "workspace",
        "failed": "review",
    }
    return mapping.get(phase, "create")
