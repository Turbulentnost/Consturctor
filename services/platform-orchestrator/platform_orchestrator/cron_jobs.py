"""User-defined cron jobs: templates, scheduling, dispatch to agent runs."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import select

from platform_contracts.cron import CronJobCreate, CronJobOut, CronJobUpdate, CronTemplateInfo
from platform_contracts.runs import RunStartRequest, RunStatus
from platform_db.models import ScheduledJobRow
from platform_db.session import get_session_factory

CRON_TEMPLATES: dict[str, dict[str, Any]] = {
    "daily_tasks": {
        "title": "Задачи 1С на сегодня",
        "description": "Открытые задачи исполнителя через COM (onec.com.query_tasks)",
        "default_cron": "0 8 * * *",
        "default_agent_id": "cron-daily-tasks",
        "config_schema": {
            "limit": {"type": "integer", "default": 50, "description": "Макс. записей из COM"},
            "mine_only": {
                "type": "boolean",
                "default": True,
                "description": "Только задачи текущего ERP-пользователя",
            },
        },
    },
    "daily_mail": {
        "title": "Проверка почты",
        "description": "Поиск непрочитанных писем в IMAP",
        "default_cron": "0 9 * * *",
        "default_agent_id": "cron-daily-mail",
        "config_schema": {
            "query": {"type": "string", "default": "UNSEEN", "description": "IMAP SEARCH criteria"},
            "limit": {"type": "integer", "default": 20, "description": "Макс. писем"},
        },
    },
    "custom": {
        "title": "Свой алгоритм",
        "description": "Произвольная цепочка tool_calls в config",
        "default_cron": "0 8 * * *",
        "default_agent_id": "cron-custom",
        "config_schema": {},
    },
}


def list_templates() -> list[CronTemplateInfo]:
    items: list[CronTemplateInfo] = []
    for template_id, meta in CRON_TEMPLATES.items():
        items.append(
            CronTemplateInfo(
                id=template_id,
                title=str(meta["title"]),
                description=str(meta["description"]),
                default_cron=str(meta["default_cron"]),
                default_agent_id=str(meta["default_agent_id"]),
                config_schema=dict(meta.get("config_schema") or {}),
            )
        )
    return items


def validate_cron_expr(cron_expr: str) -> str:
    expr = cron_expr.strip()
    if not expr:
        raise ValueError("cron_expr required")
    if not croniter.is_valid(expr):
        raise ValueError(f"invalid cron expression: {expr}")
    return expr


def compute_next_run(cron_expr: str, tz_name: str, *, base: datetime | None = None) -> datetime:
    expr = validate_cron_expr(cron_expr)
    tz = ZoneInfo(tz_name or "UTC")
    if base is None:
        base = datetime.now(tz)
    elif base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc).astimezone(tz)
    else:
        base = base.astimezone(tz)
    next_local = croniter(expr, base).get_next(datetime)
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=tz)
    return next_local.astimezone(timezone.utc)


def build_tool_calls(template_id: str, config: dict[str, Any], tool_calls: list[dict[str, Any]]) -> list[dict]:
    if tool_calls:
        return tool_calls
    if template_id == "daily_tasks":
        limit = max(1, min(100, int(config.get("limit") or config.get("top") or 50)))
        mine_only = config.get("mine_only")
        if mine_only is None:
            mine_only = True
        return [
            {
                "tool_name": "onec.com.query_tasks",
                "payload": {
                    "mine_only": bool(mine_only),
                    "limit": limit,
                    "source": "cron_daily_tasks",
                },
            }
        ]
    if template_id == "daily_mail":
        return [
            {
                "tool_name": "imap.search",
                "payload": {
                    "query": str(config.get("query") or "UNSEEN"),
                    "limit": max(1, min(100, int(config.get("limit") or 20))),
                    "source": "cron_daily_mail",
                },
            }
        ]
    custom_calls = config.get("tool_calls")
    if isinstance(custom_calls, list) and custom_calls:
        return custom_calls
    raise ValueError("custom cron job requires tool_calls in config or body")


def _row_to_out(row: ScheduledJobRow) -> CronJobOut:
    return CronJobOut(
        id=row.id,
        name=row.name,
        description=row.description,
        template_id=row.template_id,
        agent_id=row.agent_id,
        department=row.department,
        user_id=row.user_id,
        cron_expr=row.cron_expr,
        timezone=row.timezone,
        enabled=row.enabled,
        config=json.loads(row.config_json or "{}"),
        last_run_at=row.last_run_at,
        last_run_id=row.last_run_id,
        next_run_at=row.next_run_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_cron_job(body: CronJobCreate) -> CronJobOut:
    template_id = body.template_id or "custom"
    if template_id not in CRON_TEMPLATES:
        raise ValueError(f"unknown template: {template_id}")
    meta = CRON_TEMPLATES[template_id]
    cron_expr = validate_cron_expr(body.cron_expr or str(meta["default_cron"]))
    agent_id = (body.agent_id or str(meta["default_agent_id"])).strip()
    config = dict(body.config)
    tool_calls = build_tool_calls(template_id, config, body.tool_calls)
    config["tool_calls"] = tool_calls
    next_run = compute_next_run(cron_expr, body.timezone)
    row = ScheduledJobRow(
        id=uuid.uuid4(),
        name=body.name.strip(),
        description=(body.description or str(meta["description"])).strip(),
        template_id=template_id,
        agent_id=agent_id,
        user_id=body.user_id or "",
        department=body.department or "",
        cron_expr=cron_expr,
        timezone=body.timezone or "Europe/Moscow",
        enabled=body.enabled,
        config_json=json.dumps(config, ensure_ascii=False),
        next_run_at=next_run,
    )
    factory = get_session_factory()
    with factory() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row_to_out(row)


def list_cron_jobs(*, user_id: str = "", enabled_only: bool = False) -> list[CronJobOut]:
    factory = get_session_factory()
    with factory() as session:
        stmt = select(ScheduledJobRow).order_by(ScheduledJobRow.created_at.desc())
        if user_id:
            stmt = stmt.where(ScheduledJobRow.user_id == user_id)
        if enabled_only:
            stmt = stmt.where(ScheduledJobRow.enabled.is_(True))
        rows = session.scalars(stmt).all()
        return [_row_to_out(row) for row in rows]


def get_cron_job(job_id: uuid.UUID) -> CronJobOut | None:
    factory = get_session_factory()
    with factory() as session:
        row = session.get(ScheduledJobRow, job_id)
        return _row_to_out(row) if row else None


def update_cron_job(job_id: uuid.UUID, body: CronJobUpdate) -> CronJobOut | None:
    factory = get_session_factory()
    with factory() as session:
        row = session.get(ScheduledJobRow, job_id)
        if row is None:
            return None
        config = json.loads(row.config_json or "{}")
        if body.name is not None:
            row.name = body.name.strip()
        if body.description is not None:
            row.description = body.description.strip()
        if body.enabled is not None:
            row.enabled = body.enabled
        if body.timezone is not None:
            row.timezone = body.timezone.strip() or row.timezone
        if body.config is not None:
            config.update(body.config)
        if body.tool_calls is not None:
            config["tool_calls"] = body.tool_calls
        if body.cron_expr is not None:
            row.cron_expr = validate_cron_expr(body.cron_expr)
        if body.config is not None or body.tool_calls is not None or body.cron_expr is not None:
            config["tool_calls"] = build_tool_calls(
                row.template_id,
                config,
                config.get("tool_calls") if isinstance(config.get("tool_calls"), list) else [],
            )
            row.config_json = json.dumps(config, ensure_ascii=False)
            row.next_run_at = compute_next_run(row.cron_expr, row.timezone)
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(row)
        return _row_to_out(row)


def delete_cron_job(job_id: uuid.UUID) -> bool:
    factory = get_session_factory()
    with factory() as session:
        row = session.get(ScheduledJobRow, job_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def trigger_cron_job(job_id: uuid.UUID, *, create_run_fn) -> RunStatus:
    factory = get_session_factory()
    with factory() as session:
        row = session.get(ScheduledJobRow, job_id)
        if row is None:
            raise KeyError("cron job not found")
        return _dispatch_row(row, session, create_run_fn)


def dispatch_due_cron_jobs(*, create_run_fn) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    triggered: list[str] = []
    errors: list[str] = []
    factory = get_session_factory()
    with factory() as session:
        rows = session.scalars(
            select(ScheduledJobRow).where(
                ScheduledJobRow.enabled.is_(True),
                ScheduledJobRow.next_run_at.is_not(None),
                ScheduledJobRow.next_run_at <= now,
            )
        ).all()
        for row in rows:
            try:
                _dispatch_row(row, session, create_run_fn)
                triggered.append(str(row.id))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{row.id}: {exc}")
    return {"triggered": triggered, "errors": errors, "count": len(triggered)}


def _dispatch_row(row: ScheduledJobRow, session, create_run_fn) -> RunStatus:
    config = json.loads(row.config_json or "{}")
    tool_calls = build_tool_calls(
        row.template_id,
        config,
        config.get("tool_calls") if isinstance(config.get("tool_calls"), list) else [],
    )
    body = RunStartRequest(
        agent_id=row.agent_id,
        user_id=row.user_id,
        department=row.department,
        config={
            "tool_calls": tool_calls,
            "cron_job_id": str(row.id),
            "cron_job_name": row.name,
            "template_id": row.template_id,
        },
    )
    status = create_run_fn(body)
    row.last_run_at = datetime.now(timezone.utc)
    row.last_run_id = status.run_id
    row.next_run_at = compute_next_run(row.cron_expr, row.timezone, base=row.last_run_at)
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return status
