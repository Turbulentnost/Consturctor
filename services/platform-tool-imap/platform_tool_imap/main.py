from __future__ import annotations

import email
import os
import ssl
from email import policy
from typing import Any

from imapclient import IMAPClient
from pydantic import Field
from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app

IMAP_NOT_CONFIGURED = (
    "IMAP not configured: set IMAP_HOST, IMAP_USERNAME, and IMAP_PASSWORD in infra/.env"
)


class ImapSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-imap"
    api_port: int = 7821
    imap_host: str = "imap.yandex.ru"
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = Field(default="INBOX", validation_alias="IMAP_MAILBOX")


settings = ImapSettings()


_OMTO_MESSAGES = {
    8801: {
        "subject": "[omto] Заявка на согласование спецификации",
        "from": "omto@turbo-don.ru",
        "body_text": "Прошу согласовать спецификацию арматуры DN200 для объекта Ростов.",
        "attachments": [{"filename": "spec-dn200.pdf", "size": 20480}],
    },
    8802: {
        "subject": "Re: [omto] Коммерческое предложение",
        "from": "omto@turbo-don.ru",
        "body_text": "Направляю обновлённое КП с учётом замечаний от 08.08.",
        "attachments": [],
    },
    8803: {
        "subject": "[omto] Статус входящей корреспонденции ВК-000101",
        "from": "omto@turbo-don.ru",
        "body_text": "Документ зарегистрирован в 1С, ожидает ответа контрагента.",
        "attachments": [{"filename": "vk-000101.docx", "size": 12288}],
    },
}


def _imap_ready() -> bool:
    return bool(settings.imap_host and settings.imap_username and settings.imap_password)


def _require_imap() -> None:
    if not _imap_ready():
        raise RuntimeError(IMAP_NOT_CONFIGURED)


def _user_key(user: str, query: str = "") -> str:
    return (user or query or "mailbox").strip().lower()


def _uid_base(user_key: str) -> int:
    return 8800 + (sum(ord(ch) for ch in user_key) % 500)


def _message_for_user(user_key: str, uid: int) -> dict[str, Any]:
    if user_key == "omto" and uid in _OMTO_MESSAGES:
        return dict(_OMTO_MESSAGES[uid])
    label = user_key.split("@", 1)[0]
    from_addr = user_key if "@" in user_key else f"{label}@turbo-don.ru"
    return {
        "subject": f"[{label}] Служебное сообщение #{uid}",
        "from": from_addr,
        "body_text": f"Письмо uid={uid} для фильтра {user_key}.",
        "attachments": [],
    }


def _stub_meta() -> dict[str, str]:
    return {
        "mode": "stub",
        "source": "stub",
        "host": settings.imap_host or "stub",
        "mailbox": settings.imap_mailbox,
    }


def _imap_meta() -> dict[str, str]:
    return {
        "mode": "real",
        "source": "imap",
        "host": settings.imap_host,
        "mailbox": settings.imap_mailbox,
    }


def _stub_uids_for_user(user_key: str, limit: int) -> list[int]:
    limit = max(1, min(50, limit))
    if user_key == "omto":
        return sorted(_OMTO_MESSAGES.keys())[:limit]
    base = _uid_base(user_key)
    return list(range(base + 1, base + 1 + limit))


def _stub_list_unread(req: ToolInvokeRequest) -> dict[str, Any]:
    limit = max(1, int(req.payload.get("limit", 2)))
    user_key = _user_key(str(req.payload.get("user", "")), str(req.payload.get("query", "")))
    uids = _stub_uids_for_user(user_key, limit)
    return {
        "summary": f"unread={len(uids)}",
        "uids": uids,
        "count": len(uids),
        **_stub_meta(),
    }


def _stub_search(req: ToolInvokeRequest) -> dict[str, Any]:
    query = str(req.payload.get("query", "")).strip()
    user = str(req.payload.get("user", "")).strip()
    limit = max(1, min(50, int(req.payload.get("limit", 3))))
    user_key = _user_key(user, query)
    uids = _stub_uids_for_user(user_key, limit)
    messages = []
    for uid in uids:
        msg = _message_for_user(user_key, uid)
        messages.append({"uid": uid, "subject": msg["subject"], "from": msg["from"]})
    return {
        "summary": f"found={len(uids)} for user {user_key}",
        "query": query or user_key,
        "user": user_key,
        "uids": uids,
        "messages": messages,
        **_stub_meta(),
    }


def _stub_fetch_message(req: ToolInvokeRequest) -> dict[str, Any]:
    uid = int(req.payload.get("uid", 0))
    if uid <= 0:
        raise ValueError("uid required")
    user_key = _user_key(str(req.payload.get("user", "")), str(req.payload.get("query", "")))
    # Accept omto fixture UIDs even when user omitted
    if uid in _OMTO_MESSAGES:
        user_key = "omto"
    base = _uid_base(user_key)
    allowed = set(range(base + 1, base + 11)) | set(_OMTO_MESSAGES)
    if uid not in allowed and uid not in _OMTO_MESSAGES:
        raise ValueError(f"UID_NOT_FOUND: {uid}")
    msg = _message_for_user(user_key if uid not in _OMTO_MESSAGES else "omto", uid)
    return {
        "summary": msg["subject"],
        "uid": uid,
        "subject": msg["subject"],
        "from": msg["from"],
        "body_text": msg["body_text"][:12000],
        **_stub_meta(),
    }


def _stub_fetch_attachments(req: ToolInvokeRequest) -> dict[str, Any]:
    uid = int(req.payload.get("uid", 0))
    if uid <= 0:
        raise ValueError("uid required")
    user_key = _user_key(str(req.payload.get("user", "")), str(req.payload.get("query", "")))
    if uid in _OMTO_MESSAGES:
        user_key = "omto"
    allowed = set(_stub_uids_for_user(user_key, 10)) | set(_OMTO_MESSAGES)
    if uid not in allowed:
        raise ValueError(f"UID_NOT_FOUND: {uid}")
    msg = _message_for_user(user_key, uid)
    attachments = list(msg.get("attachments") or [])
    return {
        "summary": f"attachments={len(attachments)}",
        "uid": uid,
        "attachments": attachments,
        **_stub_meta(),
    }


def _connect() -> IMAPClient:
    _require_imap()
    context = ssl.create_default_context()
    timeout = float(os.environ.get("IMAP_CONNECT_TIMEOUT_SEC", "120"))
    client = IMAPClient(
        settings.imap_host,
        port=settings.imap_port,
        ssl_context=context,
        timeout=timeout,
    )
    client.login(settings.imap_username, settings.imap_password)
    return client


def _list_unread(_: ToolInvokeRequest) -> dict[str, Any]:
    client = _connect()
    try:
        client.select_folder(settings.imap_mailbox)
        uids = client.search(["UNSEEN"])
        return {
            "summary": f"unread={len(uids)}",
            "uids": list(uids),
            "count": len(uids),
            **_imap_meta(),
        }
    finally:
        client.logout()


def _fetch_message(req: ToolInvokeRequest) -> dict[str, Any]:
    uid = int(req.payload.get("uid", 0))
    if uid <= 0:
        raise ValueError("uid required")
    client = _connect()
    try:
        client.select_folder(settings.imap_mailbox)
        fetched = client.fetch([uid], ["RFC822"])
        if uid not in fetched:
            raise ValueError(f"UID_NOT_FOUND: {uid}")
        data = fetched[uid]
        raw = data.get(b"RFC822")
        if not raw:
            raise ValueError(f"UID_NOT_FOUND: {uid}")
        msg = email.message_from_bytes(raw, policy=policy.default)
        body = msg.get_body(preferencelist=("plain",))
        body_text = body.get_content() if body else ""
        return {
            "summary": msg.get("Subject", ""),
            "uid": uid,
            "subject": msg.get("Subject", ""),
            "from": msg.get("From", ""),
            "body_text": str(body_text)[:12000],
            **_imap_meta(),
        }
    except KeyError as exc:
        raise ValueError(f"UID_NOT_FOUND: {uid}") from exc
    finally:
        client.logout()


def _fetch_attachments(req: ToolInvokeRequest) -> dict[str, Any]:
    uid = int(req.payload.get("uid", 0))
    if uid <= 0:
        raise ValueError("uid required")
    client = _connect()
    try:
        client.select_folder(settings.imap_mailbox)
        fetched = client.fetch([uid], ["RFC822"])
        if uid not in fetched:
            raise ValueError(f"UID_NOT_FOUND: {uid}")
        data = fetched[uid]
        raw = data.get(b"RFC822")
        if not raw:
            raise ValueError(f"UID_NOT_FOUND: {uid}")
        msg = email.message_from_bytes(raw, policy=policy.default)
        attachments = []
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                attachments.append(
                    {
                        "filename": part.get_filename() or "attachment",
                        "size": len(part.get_payload(decode=True) or b""),
                    }
                )
        return {
            "summary": f"attachments={len(attachments)}",
            "uid": uid,
            "attachments": attachments,
            **_imap_meta(),
        }
    except KeyError as exc:
        raise ValueError(f"UID_NOT_FOUND: {uid}") from exc
    finally:
        client.logout()


def _search_criteria(user: str, query: str) -> list[Any]:
    # Exchange: avoid TEXT (full-body) — times out on large mailboxes.
    # IMAP OR is binary; only FROM/SUBJECT keeps searches interactive.
    needle = (user or query).strip()
    if not needle:
        return ["ALL"]
    if "@" in needle:
        return ["FROM", needle]
    return ["OR", "FROM", needle, "SUBJECT", needle]


def _search(req: ToolInvokeRequest) -> dict[str, Any]:
    query = str(req.payload.get("query", "")).strip()
    user = str(req.payload.get("user", "")).strip()
    limit = max(1, int(req.payload.get("limit", 50)))
    client = _connect()
    try:
        client.select_folder(settings.imap_mailbox)
        uids = list(client.search(_search_criteria(user, query)))[-limit:]
        return {
            "summary": f"found={len(uids)}",
            "query": query,
            "user": user,
            "uids": uids,
            **_imap_meta(),
        }
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

# Credentials configured → always hit real mailbox (even if USE_STUBS=true for demos).
_http_stub_handlers = REAL_HANDLERS if _imap_ready() else STUB_HANDLERS
app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=_http_stub_handlers)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()
