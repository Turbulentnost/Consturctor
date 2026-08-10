from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import httpx
from celery import Celery
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select

from platform_contracts.runs import RunStartRequest, RunStatus, RunStatusEnum
from platform_contracts.tools import ToolInvokeRequest, ToolResult
from platform_db.models import AgentRunRow, ToolEventRow
from platform_db.session import get_session_factory

broker = os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@127.0.0.1:5672//")

celery_app = Celery("platform_orchestrator", broker=broker)
celery_app.conf.task_routes = {
    "platform_orchestrator.start_agent_run": {"queue": "default"},
    "platform_orchestrator.invoke_tool_async": {"queue": "default"},
    "platform_orchestrator.retry_failed_tool": {"queue": "default"},
}


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor"
    )
    tool_imap_url: str = "http://127.0.0.1:7821"
    tool_onec_url: str = "http://127.0.0.1:7822"
    tool_shell_url: str = "http://127.0.0.1:7823"
    tool_browser_url: str = "http://127.0.0.1:7824"
    use_stubs: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 7825


settings = OrchestratorSettings()


def _tool_url(tool_name: str) -> str:
    if tool_name.startswith("imap."):
        return settings.tool_imap_url
    if tool_name.startswith("onec."):
        return settings.tool_onec_url
    if tool_name.startswith("shell."):
        return settings.tool_shell_url
    if tool_name.startswith("browser."):
        return settings.tool_browser_url
    raise ValueError(f"Unknown tool: {tool_name}")


def _row_to_status(row: AgentRunRow, tool_events_count: int = 0) -> RunStatus:
    return RunStatus(
        run_id=row.id,
        agent_id=row.agent_id,
        department=row.department,
        user_id=row.user_id,
        status=RunStatusEnum(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        error=row.error_message,
        tool_events_count=tool_events_count,
    )


def create_run(body: RunStartRequest) -> RunStatus:
    run_id = uuid.uuid4()
    row = AgentRunRow(
        id=run_id,
        agent_id=body.agent_id,
        user_id=body.user_id,
        department=body.department,
        status=RunStatusEnum.PENDING.value,
        config_json=json.dumps(body.config, ensure_ascii=False),
        tools_json=json.dumps(body.tools, ensure_ascii=False),
        started_at=datetime.now(timezone.utc),
    )
    factory = get_session_factory()
    with factory() as session:
        session.add(row)
        session.commit()
    start_agent_run.delay(str(run_id))
    return _row_to_status(row)


def get_run(run_id: uuid.UUID) -> RunStatus | None:
    factory = get_session_factory()
    with factory() as session:
        row = session.get(AgentRunRow, run_id)
        if row is None:
            return None
        tool_count = session.query(ToolEventRow).filter(ToolEventRow.run_id == run_id).count()
        return _row_to_status(row, tool_events_count=tool_count)


def get_run_events(run_id: uuid.UUID) -> list[dict]:
    factory = get_session_factory()
    with factory() as session:
        rows = session.scalars(
            select(ToolEventRow)
            .where(ToolEventRow.run_id == run_id)
            .order_by(ToolEventRow.created_at.asc())
        ).all()
        return [
            {
                "id": str(r.id),
                "tool_name": r.tool_name,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "output_summary": r.output_summary,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


def invoke_tool_http(run_id: uuid.UUID, tool_name: str, payload: dict) -> ToolResult:
    url = f"{_tool_url(tool_name).rstrip('/')}/api/v1/tools/{tool_name}/invoke"
    req = ToolInvokeRequest(
        run_id=run_id,
        department=payload.get("department", ""),
        user_id=payload.get("user_id", ""),
        payload=payload.get("payload") or {},
    )
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            url,
            json=req.model_dump(mode="json"),
            headers={
                "X-Run-Id": str(run_id),
                "X-Department": req.department,
                "X-User-Id": req.user_id,
            },
        )
        response.raise_for_status()
        return ToolResult.model_validate(response.json())


@celery_app.task(name="platform_orchestrator.invoke_tool_async", bind=True, max_retries=3)
def invoke_tool_async(self, run_id: str, tool_name: str, payload: dict) -> dict:
    try:
        result = invoke_tool_http(uuid.UUID(run_id), tool_name, payload)
        return result.model_dump(mode="json")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc


@celery_app.task(name="platform_orchestrator.retry_failed_tool", bind=True, max_retries=3)
def retry_failed_tool(self, run_id: str, tool_name: str, payload: dict) -> dict:
    return invoke_tool_async(run_id, tool_name, payload)


@celery_app.task(name="platform_orchestrator.start_agent_run")
def start_agent_run(run_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        row = session.get(AgentRunRow, uuid.UUID(run_id))
        if row is None:
            return
        row.status = RunStatusEnum.RUNNING.value
        row.updated_at = datetime.now(timezone.utc)
        tools = json.loads(row.tools_json or "[]")
        department = row.department
        user_id = row.user_id
        session.commit()

    if not tools:
        tools = ["imap.list_unread"] if settings.use_stubs else []

    errors: list[str] = []
    for tool_name in tools:
        try:
            invoke_tool_http(
                uuid.UUID(run_id),
                tool_name,
                {"department": department, "user_id": user_id, "payload": {}},
            )
        except Exception as exc:
            errors.append(f"{tool_name}: {exc}")

    with factory() as session:
        row = session.get(AgentRunRow, uuid.UUID(run_id))
        if row is None:
            return
        if errors:
            row.status = RunStatusEnum.ERROR.value
            row.error_message = "; ".join(errors)[:2000]
        else:
            row.status = RunStatusEnum.DONE.value
        row.finished_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
