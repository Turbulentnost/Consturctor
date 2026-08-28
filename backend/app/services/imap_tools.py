"""Server-side IMAP tools (ported from jalko platform-tool-imap).

Runs in-process inside the Constructor backend. Desktop must not execute imap.*.
When IMAP_HOST/USERNAME/PASSWORD are set → real mailbox; otherwise → stub fixtures.
"""

from __future__ import annotations

import email
import os
import ssl
from email import policy
from typing import Any

from app.config import settings

IMAP_NOT_CONFIGURED = (
    "IMAP not configured: set IMAP_HOST, IMAP_USERNAME, and IMAP_PASSWORD in backend/.env"
)

_OMTO_MESSAGES: dict[int, dict[str, Any]] = {
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


class ImapToolError(RuntimeError):
    pass


def imap_configured() -> bool:
    return bool(settings.imap_host and settings.imap_username and settings.imap_password)


def invoke_imap(tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    handlers = REAL_HANDLERS if imap_configured() else STUB_HANDLERS
    handler = handlers.get(tool)
    if handler is None:
        raise ImapToolError(f"Неизвестный IMAP-инструмент: {tool}")
    try:
        return handler(args)
    except ImapToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImapToolError(str(exc)) from exc


def _uid(args: dict[str, Any]) -> int:
    raw = args.get("uid", args.get("message_id", 0))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ImapToolError("uid / message_id обязателен") from exc
    if value <= 0:
        raise ImapToolError("uid / message_id обязателен")
    return value


def _user_key(user: str, query: str = "") -> str:
    return (user or query or "mailbox").strip().lower()


def _uid_base(user_key: str) -> int:
    return 8800 + (sum(ord(ch) for ch in user_key) % 500)


def _message_for_user(user_key: str, uid: int) -> dict[str, Any]:
    if user_key == "omto" and uid in _OMTO_MESSAGES:
        return dict(_OMTO_MESSAGES[uid])
    label = user_key.split("@", 1)[0]
    from_addr = user_key if "@" in user_key else f"{label}@example.local"
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


def _stub_list_unread(args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, int(args.get("limit", 2)))
    user_key = _user_key(str(args.get("user", "")), str(args.get("query", "")))
    uids = _stub_uids_for_user(user_key, limit)
    return {
        "summary": f"unread={len(uids)}",
        "uids": uids,
        "count": len(uids),
        **_stub_meta(),
    }


def _stub_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    user = str(args.get("user", "")).strip()
    limit = max(1, min(50, int(args.get("limit", 3))))
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


def _stub_fetch_message(args: dict[str, Any]) -> dict[str, Any]:
    uid = _uid(args)
    user_key = _user_key(str(args.get("user", "")), str(args.get("query", "")))
    if uid in _OMTO_MESSAGES:
        user_key = "omto"
    base = _uid_base(user_key)
    allowed = set(range(base + 1, base + 11)) | set(_OMTO_MESSAGES)
    if uid not in allowed and uid not in _OMTO_MESSAGES:
        raise ImapToolError(f"UID_NOT_FOUND: {uid}")
    msg = _message_for_user(user_key if uid not in _OMTO_MESSAGES else "omto", uid)
    return {
        "summary": msg["subject"],
        "uid": uid,
        "subject": msg["subject"],
        "from": msg["from"],
        "body_text": msg["body_text"][:12000],
        **_stub_meta(),
    }


def _stub_fetch_attachments(args: dict[str, Any]) -> dict[str, Any]:
    uid = _uid(args)
    user_key = _user_key(str(args.get("user", "")), str(args.get("query", "")))
    if uid in _OMTO_MESSAGES:
        user_key = "omto"
    allowed = set(_stub_uids_for_user(user_key, 10)) | set(_OMTO_MESSAGES)
    if uid not in allowed:
        raise ImapToolError(f"UID_NOT_FOUND: {uid}")
    msg = _message_for_user(user_key, uid)
    attachments = list(msg.get("attachments") or [])
    return {
        "summary": f"attachments={len(attachments)}",
        "uid": uid,
        "attachments": attachments,
        **_stub_meta(),
    }


def _connect():
    try:
        from imapclient import IMAPClient
    except ImportError as exc:
        raise ImapToolError(
            "Пакет imapclient не установлен. В backend: pip install imapclient"
        ) from exc
    if not imap_configured():
        raise ImapToolError(IMAP_NOT_CONFIGURED)
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


def _list_unread(_: dict[str, Any]) -> dict[str, Any]:
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


def _fetch_message(args: dict[str, Any]) -> dict[str, Any]:
    uid = _uid(args)
    client = _connect()
    try:
        client.select_folder(settings.imap_mailbox)
        fetched = client.fetch([uid], ["RFC822"])
        if uid not in fetched:
            raise ImapToolError(f"UID_NOT_FOUND: {uid}")
        data = fetched[uid]
        raw = data.get(b"RFC822")
        if not raw:
            raise ImapToolError(f"UID_NOT_FOUND: {uid}")
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
        raise ImapToolError(f"UID_NOT_FOUND: {uid}") from exc
    finally:
        client.logout()


def _fetch_attachments(args: dict[str, Any]) -> dict[str, Any]:
    uid = _uid(args)
    client = _connect()
    try:
        client.select_folder(settings.imap_mailbox)
        fetched = client.fetch([uid], ["RFC822"])
        if uid not in fetched:
            raise ImapToolError(f"UID_NOT_FOUND: {uid}")
        data = fetched[uid]
        raw = data.get(b"RFC822")
        if not raw:
            raise ImapToolError(f"UID_NOT_FOUND: {uid}")
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
        raise ImapToolError(f"UID_NOT_FOUND: {uid}") from exc
    finally:
        client.logout()


def _search_criteria(user: str, query: str) -> list[Any]:
    # Avoid TEXT (full-body) — times out on large mailboxes.
    needle = (user or query).strip()
    if not needle:
        return ["ALL"]
    if "@" in needle:
        return ["FROM", needle]
    return ["OR", "FROM", needle, "SUBJECT", needle]


def _search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    user = str(args.get("user", "")).strip()
    limit = max(1, int(args.get("limit", 50)))
    client = _connect()
    try:
        client.select_folder(settings.imap_mailbox)
        criteria = _search_criteria(user, query)
        needle = (user or query).strip()
        charset = "UTF-8" if any(ord(ch) > 127 for ch in needle) else None
        try:
            uids = list(client.search(criteria, charset=charset))[-limit:]
        except Exception:
            # mail.turbo-don.ru принимает только US-ASCII в SEARCH.
            uids = list(client.search(["ALL"]))[-limit:]
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
