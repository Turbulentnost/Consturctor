"""Server-side IMAP tools (ported from jalko platform-tool-imap).

Runs in-process inside the Constructor backend. Desktop must not execute imap.*.
When IMAP_HOST/USERNAME/PASSWORD are set → real mailbox; otherwise → stub fixtures.
"""

from __future__ import annotations

import email
import os
import ssl
from datetime import datetime, timedelta
from email import policy
from typing import Any

from app.config import settings

_IMAP_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

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


def _parse_ymd(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt, size in (("%Y-%m-%d", 10), ("%d.%m.%Y", 10)):
        chunk = text[:size]
        try:
            return datetime.strptime(chunk, fmt)
        except ValueError:
            continue
    return None


def imap_date_token(raw: str) -> str | None:
    """IMAP date atom (English month). Do not use locale-dependent %b."""
    dt = _parse_ymd(raw)
    if dt is None:
        return None
    return f"{dt.day}-{_IMAP_MONTHS[dt.month - 1]}-{dt.year}"


def _date_window(args: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    date_only = str(args.get("date") or "").strip()
    since_raw = str(args.get("since") or args.get("date_from") or "").strip()
    before_raw = str(args.get("before") or args.get("date_to") or "").strip()
    if date_only and not since_raw and not before_raw:
        since = _parse_ymd(date_only)
        if since is None:
            return None, None
        return since, since + timedelta(days=1)
    since = _parse_ymd(since_raw or date_only)
    before = _parse_ymd(before_raw)
    if before is not None:
        before = before + timedelta(days=1)
    return since, before


def _stub_in_window(since: datetime | None, before: datetime | None) -> bool:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if since is not None and today < since.replace(hour=0, minute=0, second=0, microsecond=0):
        return False
    if before is not None and today >= before.replace(hour=0, minute=0, second=0, microsecond=0):
        return False
    return True


def _stub_message_row(user_key: str, uid: int) -> dict[str, Any]:
    msg = _message_for_user(user_key, uid)
    stamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    return {
        "uid": uid,
        "subject": msg["subject"],
        "from": msg["from"],
        "date": stamp,
        "message_id": f"<stub-{uid}@constructor.local>",
        "unread": True,
    }


def _stub_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    user = str(args.get("user", "")).strip()
    limit = max(1, min(50, int(args.get("limit", 3))))
    user_key = _user_key(user, query)
    since, before = _date_window(args)
    if not _stub_in_window(since, before):
        return {
            "summary": f"found=0 for user {user_key}",
            "query": query or user_key,
            "user": user_key,
            "uids": [],
            "messages": [],
            **_stub_meta(),
        }
    uids = _stub_uids_for_user(user_key, limit)
    messages = [_stub_message_row(user_key, uid) for uid in uids]
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


def _list_unread(args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(80, int(args.get("limit", 50))))
    client = _connect()
    try:
        client.select_folder(settings.imap_mailbox)
        uids = list(client.search(["UNSEEN"]))[-limit:]
        messages = _messages_for_uids(client, uids)
        return {
            "summary": f"unread={len(uids)}",
            "uids": uids,
            "count": len(uids),
            "messages": messages,
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


def _imap_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip()


def _fetch_field(data: dict[Any, Any], name: str) -> Any:
    key_b = name.encode("ascii")
    if key_b in data:
        return data[key_b]
    return data.get(name)


def _addr_list_to_str(addrs: Any) -> str:
    if not addrs:
        return ""
    first = addrs[0]
    name = _imap_text(getattr(first, "name", None))
    mailbox = _imap_text(getattr(first, "mailbox", None))
    host = _imap_text(getattr(first, "host", None))
    email_addr = f"{mailbox}@{host}" if mailbox and host else mailbox
    if name and email_addr:
        return f"{name} <{email_addr}>"
    return email_addr or name


def _flags_unseen(flags: Any) -> bool:
    if not flags:
        return True
    for flag in flags:
        token = _imap_text(flag).upper().lstrip("\\")
        if token == "SEEN":
            return False
    return True


def envelope_to_message(uid: int, env: Any, flags: Any = None) -> dict[str, Any]:
    date_val = getattr(env, "date", None) if env is not None else None
    if hasattr(date_val, "isoformat"):
        date_iso = date_val.isoformat()
    else:
        date_iso = _imap_text(date_val)
    return {
        "uid": int(uid),
        "message_id": _imap_text(getattr(env, "message_id", "") if env is not None else ""),
        "subject": _imap_text(getattr(env, "subject", "") if env is not None else ""),
        "from": _addr_list_to_str(getattr(env, "from_", None) if env is not None else None),
        "date": date_iso,
        "unread": _flags_unseen(flags),
    }


def _messages_for_uids(client: Any, uids: list[Any]) -> list[dict[str, Any]]:
    if not uids:
        return []
    fetched = client.fetch(uids, ["ENVELOPE", "FLAGS"])
    out: list[dict[str, Any]] = []
    for uid in uids:
        data = fetched.get(uid) or {}
        if not isinstance(data, dict):
            continue
        env = _fetch_field(data, "ENVELOPE")
        flags = _fetch_field(data, "FLAGS")
        row = envelope_to_message(int(uid), env, flags)
        if row["subject"] or row["from"] or row["message_id"]:
            out.append(row)
    return out


def _search_criteria(
    user: str,
    query: str,
    since_token: str | None = None,
    before_token: str | None = None,
) -> list[Any]:
    # Avoid TEXT (full-body) — times out on large mailboxes.
    parts: list[Any] = []
    if since_token:
        parts.extend(["SINCE", since_token])
    if before_token:
        parts.extend(["BEFORE", before_token])
    needle = (user or query).strip()
    if needle:
        if "@" in needle:
            parts.extend(["FROM", needle])
        else:
            parts.extend(["OR", "FROM", needle, "SUBJECT", needle])
    return parts or ["ALL"]


def _search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    user = str(args.get("user", "")).strip()
    limit = max(1, min(80, int(args.get("limit", 50))))
    since, before = _date_window(args)
    since_token = imap_date_token(since.strftime("%Y-%m-%d")) if since else None
    before_token = imap_date_token(before.strftime("%Y-%m-%d")) if before else None
    client = _connect()
    try:
        client.select_folder(settings.imap_mailbox)
        uids = list(client.search(_search_criteria(user, query, since_token, before_token)))[-limit:]
        messages = _messages_for_uids(client, uids)
        return {
            "summary": f"found={len(uids)}",
            "query": query,
            "user": user,
            "uids": uids,
            "messages": messages,
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
