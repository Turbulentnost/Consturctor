"""Map colleague SOAP/HTTP inbox rows to orchestrator docflow task dicts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.erp_tasks import from_1c_datetime, task_is_late
from app.tools.onec.dok_soap import (
    CHANNEL_SOAP,
    ROLE_AUTHOR,
    ROLE_BOTH,
    ROLE_EXECUTOR,
    source_for_role,
    task_role_for_user,
)


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
    author = str(row.get("author") or "").strip()
    step = str(row.get("step") or "").strip()
    target = str(row.get("target") or "").strip()
    raw_performer = str(row.get("performer") or "").strip()
    tagged_role = str(row.get("role") or "").strip()
    role = tagged_role if tagged_role in {ROLE_EXECUTOR, ROLE_AUTHOR, ROLE_BOTH} else (
        task_role_for_user({"author": author, "performer": raw_performer}, fio) or ROLE_EXECUTOR
    )
    performer = raw_performer or ("" if role == ROLE_AUTHOR else fio)
    comment_parts = [part for part in (step, target) if part]
    return {
        "number": str(row.get("number") or row.get("id") or "").strip(),
        "title": title,
        "status": "выполнена" if done else "открыта",
        "done": done,
        "late": task_is_late(done=done, completed_at=None, due_at=due),
        "created_at": created.isoformat(sep=" ") if created else "",
        "due_at": due.isoformat(sep=" ") if due else "",
        "completed_at": "",
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
