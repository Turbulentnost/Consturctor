from __future__ import annotations

from pydantic import BaseModel, Field


class ChatCommandIn(BaseModel):
    type: str
    client_id: str = ""
    thread_id: str = ""
    peer_id: str = ""
    kind: str = ""
    text: str = ""
    file_ids: list[str] = Field(default_factory=list)
    status: str = ""
    ticket_id: str = ""
    assigned_to: str = ""


class ActivityIn(BaseModel):
    status: str
