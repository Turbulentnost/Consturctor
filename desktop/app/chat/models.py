from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatThread:
    id: str
    kind: str
    title: str
    position: str = ""
    preview: str = ""
    last_message_at: str = ""
    unread: int = 0
    pinned: bool = False
    peer_id: str = ""
    activity_status: str = ""
    online: bool = False
    ticket_status: str = ""


@dataclass
class ChatAttachment:
    id: str
    filename: str
    mime: str = ""
    size: int = 0


@dataclass
class ChatMessage:
    id: str
    thread_id: str
    sender_id: str
    mine: bool
    text: str
    client_id: str = ""
    created_at: str = ""
    receipt: str = "sending"
    attachments: list[ChatAttachment] = field(default_factory=list)
    agent: dict[str, Any] | None = None


@dataclass
class DirectoryUser:
    id: str
    fio: str
    position: str = ""
    department: str = ""
    activity_status: str = "online"
    online: bool = False
    is_support: bool = False
