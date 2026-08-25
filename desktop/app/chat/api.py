from __future__ import annotations

from pathlib import Path

import httpx
import mimetypes

from app.api_client import ApiClient, ApiError
from app.chat.crypto import decrypt_text
from app.chat.models import ChatAttachment, ChatMessage, ChatThread, DirectoryUser

_MIME_BY_EXT = {
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".zip": "application/zip",
}


def guess_mime(path: Path) -> str:
    mapped = _MIME_BY_EXT.get(path.suffix.lower())
    if mapped:
        return mapped
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


class ChatApi:
    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def threads(self, search: str = "") -> list[ChatThread]:
        data = self._api._request("GET", "/api/v1/chat/threads", params={"search": search} if search else None)
        return [_thread(item) for item in data.get("items") or []]

    def messages(self, thread_id: str) -> list[ChatMessage]:
        data = self._api._request("GET", f"/api/v1/chat/threads/{thread_id}/messages")
        return [_message(item) for item in data.get("items") or []]

    def directory(self, search: str = "") -> list[DirectoryUser]:
        params = {"search": search} if search.strip() else None
        merged: dict[str, DirectoryUser] = {}
        last_error: ApiError | None = None
        for path in (
            "/api/v1/auth/directory",
            "/api/v1/chat/directory",
            "/api/v1/notifications/users",
            "/api/v1/auth/users",
        ):
            try:
                data = self._api._request("GET", path, params=params)
            except ApiError as exc:
                last_error = exc
                continue
            for user in _directory_users(data):
                key = user.id or user.fio.casefold()
                prev = merged.get(key) or merged.get(user.fio.casefold())
                if prev is None:
                    merged[key] = user
                    continue
                if not prev.id and user.id:
                    merged[key] = user
        from app.chat.shared_bus import roster_list
        from app.chat.test_user import TEST_USER_ID, test_directory_user

        for user in roster_list():
            key = user.id or user.fio.casefold()
            merged.setdefault(key, user)
        anna = test_directory_user()
        merged.setdefault(anna.id, anna)
        merged.setdefault(TEST_USER_ID, anna)
        if merged:
            return sorted(merged.values(), key=lambda item: item.fio.casefold())
        if last_error is not None:
            raise last_error
        return [anna]

    def support_shelf(self, name: str) -> list[dict]:
        data = self._api._request("GET", f"/api/v1/chat/support/{name}")
        return list(data.get("items") or [])

    def command(self, payload: dict) -> str:
        data = self._api._request("POST", "/api/v1/chat/commands", json=payload)
        return str(data.get("client_id") or "")

    def upload(self, path: str) -> dict:
        file_path = Path(path)
        with httpx.Client(timeout=60) as client, file_path.open("rb") as handle:
            response = client.post(
                f"{self._api.base_url}/api/v1/chat/files",
                headers=self._api._headers(),
                files={"file": (file_path.name, handle, guess_mime(file_path))},
            )
        if response.status_code >= 400:
            raise ApiError(response.text, status_code=response.status_code)
        return response.json()

    def set_activity(self, status: str) -> str:
        data = self._api._request("PATCH", "/api/v1/auth/me/activity", json={"status": status})
        return str(data.get("client_id") or "")


def _thread(item: dict) -> ChatThread:
    return ChatThread(
        id=str(item.get("id") or ""),
        kind=str(item.get("kind") or "dm"),
        title=str(item.get("title") or "Диалог"),
        position=str(item.get("position") or ""),
        preview=decrypt_text(str(item.get("preview") or "")),
        last_message_at=str(item.get("last_message_at") or ""),
        unread=int(item.get("unread") or 0),
        pinned=bool(item.get("pinned")),
        peer_id=str(item.get("peer_id") or ""),
        activity_status=str(item.get("activity_status") or ""),
        online=bool(item.get("online")),
        ticket_status=str(item.get("ticket_status") or ""),
        avatar_url=str(item.get("avatar_url") or ""),
    )


def _message(item: dict) -> ChatMessage:
    files = [
        ChatAttachment(
            id=str(row.get("id") or ""),
            filename=str(row.get("filename") or ""),
            mime=str(row.get("mime") or ""),
            size=int(row.get("size") or 0),
        )
        for row in item.get("attachments") or []
    ]
    return ChatMessage(
        id=str(item.get("id") or ""),
        thread_id=str(item.get("thread_id") or ""),
        sender_id=str(item.get("sender_id") or ""),
        mine=bool(item.get("mine")),
        text=decrypt_text(str(item.get("text") or "")),
        client_id=str(item.get("client_id") or ""),
        created_at=str(item.get("created_at") or ""),
        receipt=str(item.get("receipt") or "delivered"),
        attachments=files,
        agent=item.get("agent") if isinstance(item.get("agent"), dict) else None,
    )


def _directory_users(data: object) -> list[DirectoryUser]:
    raw = data.get("items") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    users: list[DirectoryUser] = []
    for item in raw:
        if isinstance(item, str):
            fio = item.strip()
            if fio:
                users.append(DirectoryUser(id="", fio=fio))
            continue
        if not isinstance(item, dict):
            continue
        fio = str(item.get("fio") or item.get("name") or "").strip()
        if not fio:
            continue
        users.append(
            DirectoryUser(
                id=str(item.get("id") or "").strip(),
                fio=fio,
                position=str(item.get("position") or ""),
                department=str(item.get("department") or ""),
                activity_status=str(item.get("activity_status") or "online"),
                online=bool(item.get("online")),
                is_support=bool(item.get("is_support")),
            )
        )
    return users
