"""Map colleague SOAP/HTTP inbox rows to orchestrator docflow task dicts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.erp_tasks import from_1c_datetime, task_is_late
from app.tools.onec.docflow_task_kinds import docflow_task_kind
from app.tools.onec.dok_soap import (
    CHANNEL_SOAP,
    ROLE_AUTHOR,
    ROLE_BOTH,
    ROLE_DELEGATE,
    ROLE_EXECUTOR,
    source_for_role,
    task_role_for_user,
)


_HISTORY_LINE = re.compile(
    r"(?m)^(\d{2}\.\d{2}\.\d{4})(?:[ \t]+(\d{1,2}:\d{2}))?,\s+.+?\.\s+Задача\s+(выполнена|завершена)\b",
    re.IGNORECASE,
)


def completion_from_history(text: str) -> datetime | None:
    """День из «Истории выполнения»: сначала «Задача выполнена», иначе «Задача завершена»."""
    body = str(text or "")
    marker = body.rfind("История выполнения")
    if marker >= 0:
        body = body[marker:]
    done_at: datetime | None = None
    closed_at: datetime | None = None
    for match in _HISTORY_LINE.finditer(body):
        clock = match.group(2)
        try:
            stamp = datetime.strptime(
                f"{match.group(1)} {clock}" if clock else match.group(1),
                "%d.%m.%Y %H:%M" if clock else "%d.%m.%Y",
            )
        except ValueError:
            continue
        if "выполн" in match.group(3).casefold():
            if done_at is None or stamp > done_at:
                done_at = stamp
        elif closed_at is None or stamp > closed_at:
            closed_at = stamp
    return done_at or closed_at


def _parse_due(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text or text.startswith("0001-01-01"):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", ""))
    except ValueError:
        return None
    return from_1c_datetime(parsed) or parsed


def map_inbox_row(row: dict[str, Any], *, fio: str) -> dict[str, Any]:
    """SOAP inbox row keys: description, step, due, begin, author, name, target."""
    title = " ".join(
        str(row.get("description") or row.get("target") or row.get("name") or "").split()
    )
    due = _parse_due(row.get("due"))
    created = _parse_due(row.get("begin"))
    done = bool(row.get("executed"))
    completed = completion_from_history(str(row.get("description") or "")) if done else None
    author = str(row.get("author") or "").strip()
    step = str(row.get("step") or "").strip()
    name = " ".join(str(row.get("name") or "").split())
    target = str(row.get("target") or "").strip()
    raw_performer = str(row.get("performer") or "").strip()
    tagged_role = str(row.get("role") or "").strip()
    role = tagged_role if tagged_role in {ROLE_EXECUTOR, ROLE_AUTHOR, ROLE_BOTH, ROLE_DELEGATE} else (
        task_role_for_user({"author": author, "performer": raw_performer}, fio) or ROLE_EXECUTOR
    )
    performer = raw_performer or ("" if role == ROLE_AUTHOR else fio)
    comment_parts = [part for part in (step, target) if part]
    return {
        "number": str(row.get("number") or row.get("id") or "").strip(),
        "title": title,
        "status": "выполнена" if done else "открыта",
        "done": done,
        "late": task_is_late(done=done, completed_at=completed, due_at=due),
        "created_at": created.isoformat(sep=" ") if created else "",
        "due_at": due.isoformat(sep=" ") if due else "",
        "completed_at": completed.isoformat(sep=" ") if completed else "",
        "comment": "; ".join(comment_parts),
        "approval": step or ("завершена" if done else "не согласовано"),
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "author": author,
        "performer": performer,
        "role": role,
        "channel": CHANNEL_SOAP,
        "source": source_for_role(role),
        "ref_key": str(row.get("id") or "").strip(),
        "target_id": str(row.get("target_id") or "").strip(),
        "step": step,
        "task_name": name,
        "importance": str(row.get("importance") or "").strip(),
        "kind": docflow_task_kind(step, name),
        "on_behalf_of": str(row.get("on_behalf_of") or "").strip(),
    }


def _mapped_task_key(row: dict[str, Any]) -> str:
    ref = str(row.get("ref_key") or "").strip()
    if ref:
        return f"ref:{ref.casefold()}"
    number = str(row.get("number") or "").strip()
    if number:
        return f"num:{number.casefold()}"
    title = " ".join(str(row.get("title") or "").split()).casefold()
    due = str(row.get("due_at") or "")[:10]
    author = " ".join(str(row.get("author") or "").split()).casefold()
    performer = " ".join(str(row.get("performer") or "").split()).casefold()
    return f"sig:{author}|{performer}|{title}|{due}"


def map_inbox_payload(payload: dict[str, Any], *, fio: str) -> list[dict[str, Any]]:
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        mapped = map_inbox_row(row, fio=fio)
        key = _mapped_task_key(mapped)
        if key in seen:
            continue
        seen.add(key)
        out.append(mapped)
    return out
