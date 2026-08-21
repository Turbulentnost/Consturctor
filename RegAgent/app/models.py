from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


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
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Card:
        ui_raw = row.get("ui_spec_json") or "{}"
        if isinstance(ui_raw, str):
            import json

            ui_data = json.loads(ui_raw) if ui_raw.strip() else {}
        else:
            ui_data = ui_raw
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
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )
