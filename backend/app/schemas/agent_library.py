from __future__ import annotations

from pydantic import BaseModel, Field


class AgentLibraryCardOut(BaseModel):
    type: str = "agent_card"
    workflow_id: str = Field(serialization_alias="workflowId")
    title: str = ""
    description: str = ""
    goal: str = ""
    trigger_summary: str = Field(default="", serialization_alias="triggerSummary")
    trigger_kind: str = Field(default="", serialization_alias="triggerKind")
    status: str = "published"
    phase: str = "done"
    tools: list[str] = Field(default_factory=list)
    owner_id: str = Field(default="", serialization_alias="ownerId")
    owner_fio: str = Field(default="", serialization_alias="ownerFio")
    author: str | None = Field(default=None, description="ФИО владельца workflow; null если не найден")
    created_at: str | None = Field(default=None, serialization_alias="createdAt")
    purpose: str = Field(
        default="functional",
        description="functional | positional (долностной)",
    )


class AgentLibraryEntryOut(AgentLibraryCardOut):
    already_added: bool = Field(default=False, serialization_alias="alreadyAdded")
    adopted_workflow_id: str = Field(default="", serialization_alias="adoptedWorkflowId")


class AgentLibraryListOut(BaseModel):
    catalog: list[AgentLibraryEntryOut] = Field(default_factory=list)
    adopted: list[AgentLibraryEntryOut] = Field(default_factory=list)


class AgentLibraryAdoptOut(BaseModel):
    ok: bool = True
    workflow_id: str = Field(serialization_alias="workflowId")
    title: str = ""
    card: AgentLibraryCardOut
