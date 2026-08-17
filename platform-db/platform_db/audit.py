from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from platform_db.models import ToolEventRow


def hash_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def log_tool_event(
    session: Session,
    *,
    tool_name: str,
    run_id: uuid.UUID | None = None,
    department: str = "",
    user_id: str = "",
    payload: dict[str, Any] | None = None,
    output_summary: str = "",
    status: str = "ok",
    error_message: str | None = None,
    duration_ms: int = 0,
) -> ToolEventRow:
    row = ToolEventRow(
        id=uuid.uuid4(),
        run_id=run_id,
        tool_name=tool_name,
        department=department,
        user_id=user_id,
        input_hash=hash_payload(payload or {}),
        output_summary=output_summary[:2000],
        status=status,
        error_message=error_message,
        duration_ms=duration_ms,
        payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str),
    )
    session.add(row)
    session.flush()
    return row
