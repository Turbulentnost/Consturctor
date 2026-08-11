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


_OMTO_MESSAGES = {
    8801: {
        "subject": "[omto] Заявка на согласование спецификации",
        "from": "omto@turbo-don.ru",
        "body_text": "Прошу согласовать спецификацию арматуры DN200 для объекта Ростов.",
    },
    8802: {
        "subject": "Re: [omto] Коммерческое предложение",
        "from": "omto@turbo-don.ru",
        "body_text": "Направляю обновлённое КП с учётом замечаний от 08.08.",
    },
    8803: {
        "subject": "[omto] Статус входящей корреспонденции ВК-000101",
        "from": "omto@turbo-don.ru",
        "body_text": "Документ зарегистрирован в 1С, ожидает ответа контрагента.",
    },
}


def _imap_ready() -> bool:
    return bool(settings.imap_username and settings.imap_password)


def _user_key(user: str, query: str = "") -> str:
    return (user or query or "mailbox").strip().lower()


def _uid_base(user_key: str) -> int:
    return 8800 + (sum(ord(ch) for ch in user_key) % 500)


def _message_for_user(user_key: str, uid: int) -> dict[str, str]:
    if user_key == "omto" and uid in _OMTO_MESSAGES:
        return _OMTO_MESSAGES[uid]
    label = user_key.split("@", 1)[0]
    from_addr = user_key if "@" in user_key else f"{label}@turbo-don.ru"
    return {
        "subject": f"[{label}] Служебное сообщение #{uid}",
        "from": from_addr,
        "body_text": f"Письмо uid={uid} для фильтра {user_key}.",
    }


def _search_result(user_key: str, query: str, limit: int) -> dict[str, Any]:
    base = _uid_base(user_key)
    uids = list(range(base + 1, base + 1 + limit))
    messages = [
        {
            "uid": uid,
            **{k: v for k, v in _message_for_user(user_key, uid).items() if k != "body_text"},
        }
        for uid in uids
    ]
    return {
        "summary": f"found={len(uids)} for user {user_key}",
        "query": query or user_key,
        "user": user_key,
        "uids": uids,
        "messages": messages,
    }


def _stub_list_unread(req: ToolInvokeRequest) -> dict[str, Any]:
    if _imap_ready():
        return _list_unread(req)
    limit = max(1, int(req.payload.get("limit", 2)))
    user_key = _user_key(str(req.payload.get("user", "")), str(req.payload.get("query", "")))
    base = _uid_base(user_key)
    uids = list(range(base + 1, base + 1 + limit))
    return {
        "summary": f"unread={len(uids)}",
        "uids": uids,
        "count": len(uids),
    }


def _stub_fetch_message(req: ToolInvokeRequest) -> dict[str, Any]:
    if _imap_ready():
        return _fetch_message(req)
    uid = int(req.payload.get("uid", 101))
    user_key = _user_key(str(req.payload.get("user", "")), str(req.payload.get("query", "")))
    msg = _message_for_user(user_key, uid)
    return {
        "summary": msg["subject"],
        "uid": uid,
        "user": user_key,
        "subject": msg["subject"],
        "from": msg["from"],
        "body_text": msg["body_text"],
    }


def _stub_fetch_attachments(req: ToolInvokeRequest) -> dict[str, Any]:
    if _imap_ready():
        return _fetch_attachments(req)
    uid = int(req.payload.get("uid", 101))
    user_key = _user_key(str(req.payload.get("user", "")), str(req.payload.get("query", "")))
    label = user_key.split("@", 1)[0]
    return {
        "summary": f"attachments=1 for {label}",
        "uid": uid,
        "attachments": [{"filename": f"{label}_{uid}.pdf", "size": 1234}],
    }


def _stub_search(req: ToolInvokeRequest) -> dict[str, Any]:
    if _imap_ready():
        return _search(req)
    query = str(req.payload.get("query", "")).strip()
    user = str(req.payload.get("user", "")).strip()
    limit = max(1, int(req.payload.get("limit", 50)))
    user_key = _user_key(user, query)
    return _search_result(user_key, query or user, limit)


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
    user = str(req.payload.get("user", "")).strip()
    limit = max(1, int(req.payload.get("limit", 50)))
    client = _connect()
    try:
        client.select_folder(settings.mailbox)
        if user:
            uids = client.search(["FROM", user])
        elif query:
            uids = client.search(["OR", "SUBJECT", query, "FROM", query])
        else:
            uids = client.search(["ALL"])
        uids = list(uids)[-limit:]
        return {"summary": f"found={len(uids)}", "query": query, "user": user, "uids": uids}
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
