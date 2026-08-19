from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DirectoryUser(BaseModel):
    id: str
    fio: str
    position: str = ""
    department: str = ""


class DirectoryUserList(BaseModel):
    items: list[DirectoryUser] = Field(default_factory=list)


class NotificationCreate(BaseModel):
    recipient_user_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=256)
    body: str = ""
    send_at: datetime | None = None
    workflow_id: str = ""


class NotificationOut(BaseModel):
    id: str
    sender_user_id: str
    recipient_user_id: str
    title: str
    body: str = ""
    workflow_id: str = ""
    send_at: datetime
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    created_at: datetime | None = None
    sender_fio: str = ""
    unread: bool = True
    agent_deleted: bool = False


class NotificationInbox(BaseModel):
    items: list[NotificationOut] = Field(default_factory=list)
    unread_count: int = 0
