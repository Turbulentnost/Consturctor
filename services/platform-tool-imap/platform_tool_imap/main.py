from __future__ import annotations

import email
import ssl
from email import policy
from typing import Any

from imapclient import IMAPClient
from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app


class ImapSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-imap"
    api_port: int = 7821
    imap_host: str = "imap.yandex.ru"
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    mailbox: str = "INBOX"


settings = ImapSettings()


def _stub_list_unread(_: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub unread list",
        "uids": [101, 102],
        "count": 2,
    }


def _stub_fetch_message(req: ToolInvokeRequest) -> dict[str, Any]:
    uid = req.payload.get("uid", 101)
    return {
        "summary": f"stub message uid={uid}",
        "uid": uid,
        "subject": "Stub subject",
        "from": "stub@example.com",
        "body_text": "Stub body",
    }


def _stub_fetch_attachments(req: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub attachments",
        "uid": req.payload.get("uid", 101),
        "attachments": [{"filename": "stub.pdf", "size": 1234}],
    }


def _stub_search(req: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub search",
        "query": req.payload.get("query", ""),
        "uids": [101],
    }


def _connect() -> IMAPClient:
    if not settings.imap_username or not settings.imap_password:
        raise RuntimeError("IMAP credentials not configured")
    context = ssl.create_default_context()
    client = IMAPClient(settings.imap_host, port=settings.imap_port, ssl_context=context)
    client.login(settings.imap_username, settings.imap_password)
    return client


def _list_unread(_: ToolInvokeRequest) -> dict[str, Any]:
    client = _connect()
    try:
        client.select_folder(settings.mailbox)
        uids = client.search(["UNSEEN"])
        return {"summary": f"unread={len(uids)}", "uids": list(uids), "count": len(uids)}
    finally:
        client.logout()


def _fetch_message(req: ToolInvokeRequest) -> dict[str, Any]:
    uid = int(req.payload.get("uid", 0))
    if uid <= 0:
        raise ValueError("uid required")
    client = _connect()
    try:
        client.select_folder(settings.mailbox)
        data = client.fetch([uid], ["RFC822"])[uid]
        msg = email.message_from_bytes(data[b"RFC822"], policy=policy.default)
        body = msg.get_body(preferencelist=("plain",))
        body_text = body.get_content() if body else ""
        return {
            "summary": msg.get("Subject", ""),
            "uid": uid,
            "subject": msg.get("Subject", ""),
            "from": msg.get("From", ""),
            "body_text": body_text[:12000],
        }
    finally:
        client.logout()


def _fetch_attachments(req: ToolInvokeRequest) -> dict[str, Any]:
    uid = int(req.payload.get("uid", 0))
    if uid <= 0:
        raise ValueError("uid required")
    client = _connect()
    try:
        client.select_folder(settings.mailbox)
        data = client.fetch([uid], ["RFC822"])[uid]
        msg = email.message_from_bytes(data[b"RFC822"], policy=policy.default)
        attachments = []
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                attachments.append(
                    {
                        "filename": part.get_filename() or "attachment",
                        "size": len(part.get_payload(decode=True) or b""),
                    }
                )
        return {"summary": f"attachments={len(attachments)}", "uid": uid, "attachments": attachments}
    finally:
        client.logout()


def _search(req: ToolInvokeRequest) -> dict[str, Any]:
    query = str(req.payload.get("query", "")).strip()
    client = _connect()
    try:
        client.select_folder(settings.mailbox)
        if query:
            uids = client.search(["OR", "SUBJECT", query, "FROM", query])
        else:
            uids = client.search(["ALL"])[:50]
        return {"summary": f"found={len(uids)}", "query": query, "uids": list(uids)}
    finally:
        client.logout()


STUB_HANDLERS = {
    "imap.list_unread": _stub_list_unread,
    "imap.fetch_message": _stub_fetch_message,
    "imap.fetch_attachments": _stub_fetch_attachments,
    "imap.search": _stub_search,
}

REAL_HANDLERS = {
    "imap.list_unread": _list_unread,
    "imap.fetch_message": _fetch_message,
    "imap.fetch_attachments": _fetch_attachments,
    "imap.search": _search,
}

app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()
