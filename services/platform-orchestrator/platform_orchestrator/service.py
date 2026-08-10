from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import httpx
from celery import Celery
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select

from platform_orchestrator.agent_mocks import get_mock_scenario, tool_names_from_scenario
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
celery_app.conf.beat_schedule = {
    "poll-imap-mailbox": {
        "task": "platform_tool_imap.poll_mailbox",
        "schedule": float(os.environ.get("IMAP_POLL_SECONDS", "60")),
        "options": {"queue": "imap"},
    },
    "poll-onec-events": {
        "task": "platform_tool_onec.poll_events",
        "schedule": float(os.environ.get("ONEC_POLL_SECONDS", "120")),
        "options": {"queue": "onec"},
    },
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
    config = dict(body.config)
    if body.tools and "tool_calls" not in config:
        config.setdefault(
            "tool_calls",
            [{"tool_name": name, "payload": {}} for name in body.tools],
        )
    row = AgentRunRow(
        id=run_id,
        agent_id=body.agent_id,
        user_id=body.user_id,
        department=body.department,
        status=RunStatusEnum.PENDING.value,
        config_json=json.dumps(config, ensure_ascii=False),
        tools_json=json.dumps(body.tools, ensure_ascii=False),
        started_at=datetime.now(timezone.utc),
    )
    factory = get_session_factory()
    with factory() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        status = _row_to_status(row)
    start_agent_run.delay(str(run_id))
    return status


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


def _tool_calls_for_run(config_json: str | None, tools_json: str | None) -> list[dict]:
    config = json.loads(config_json or "{}")
    raw_calls = config.get("tool_calls")
    if isinstance(raw_calls, list) and raw_calls:
        return raw_calls
    tools = json.loads(tools_json or "[]")
    return [{"tool_name": name, "payload": {}} for name in tools]


def start_mock_run(scenario_id: str, body: RunStartRequest) -> RunStatus:
    scenario = get_mock_scenario(scenario_id)
    mock_body = RunStartRequest(
        agent_id=scenario["agent_id"],
        department=body.department,
        user_id=body.user_id,
        tools=tool_names_from_scenario(scenario),
        config={
            "mock_scenario": scenario_id,
            "tool_calls": scenario["tool_calls"],
        },
    )
    return create_run(mock_body)


def simulate_mock_scenario(
    scenario_id: str,
    *,
    department: str = "",
    user_id: str = "",
) -> dict:
    """Synchronous mock agent walkthrough for tool verification."""
    scenario = get_mock_scenario(scenario_id)
    run_id = uuid.uuid4()
    steps: list[dict] = []
    errors: list[str] = []

    for index, call in enumerate(scenario["tool_calls"], start=1):
        thought = call.get("thought") or f"Invoke {call['tool_name']}"
        steps.append(
            {
                "step": index,
                "phase": "plan",
                "message": thought,
                "tool_name": call["tool_name"],
            }
        )
        payload = {
            "department": department,
            "user_id": user_id,
            "payload": call.get("payload") or {},
        }
        try:
            if settings.use_stubs:
                result = invoke_tool_http(run_id, call["tool_name"], payload)
            else:
                result = invoke_tool_queued(run_id, call["tool_name"], payload, wait=True)
            steps.append(
                {
                    "step": index,
                    "phase": "tool",
                    "tool_name": call["tool_name"],
                    "ok": result.ok,
                    "summary": (result.data or {}).get("summary") if isinstance(result.data, dict) else None,
                    "data": result.data,
                    "error": result.error,
                }
            )
            if not result.ok:
                errors.append(f"{call['tool_name']}: {result.error or 'failed'}")
                break
        except Exception as exc:
            errors.append(f"{call['tool_name']}: {exc}")
            steps.append(
                {
                    "step": index,
                    "phase": "error",
                    "tool_name": call["tool_name"],
                    "message": str(exc),
                }
            )
            break

    return {
        "scenario_id": scenario_id,
        "title": scenario["title"],
        "agent_id": scenario["agent_id"],
        "status": "error" if errors else "done",
        "errors": errors,
        "steps": steps,
    }


def _tool_queue(tool_name: str) -> str | None:
    if tool_name.startswith("imap."):
        return "imap"
    if tool_name.startswith("onec."):
        return "onec"
    if tool_name.startswith("shell."):
        return "shell"
    if tool_name.startswith("browser."):
        return "browser"
    return None


def _tool_task_name(tool_name: str) -> str | None:
    queue = _tool_queue(tool_name)
    if queue == "imap":
        return "platform_tool_imap.invoke_async"
    if queue == "onec":
        return "platform_tool_onec.invoke_async"
    return None


def invoke_tool_queued(
    run_id: uuid.UUID,
    tool_name: str,
    payload: dict,
    *,
    wait: bool = True,
    timeout: float = 120.0,
) -> ToolResult:
    """Dispatch tool work to a per-domain RabbitMQ queue; optional sync wait."""
    if settings.use_stubs:
        return invoke_tool_http(run_id, tool_name, payload)

    task_name = _tool_task_name(tool_name)
    queue = _tool_queue(tool_name)
    req = ToolInvokeRequest(
        run_id=run_id,
        department=payload.get("department", ""),
        user_id=payload.get("user_id", ""),
        payload=payload.get("payload") or {},
    )
    if task_name and queue:
        async_result = celery_app.send_task(
            task_name,
            args=[tool_name, req.model_dump(mode="json")],
            queue=queue,
        )
        if not wait:
            return ToolResult(
                ok=True,
                tool_name=tool_name,
                data={"queued": True, "task_id": async_result.id},
                duration_ms=0,
            )
        data = async_result.get(timeout=timeout)
        if isinstance(data, dict) and "ok" in data:
            return ToolResult.model_validate(data)
        return ToolResult(ok=True, tool_name=tool_name, data=data if isinstance(data, dict) else {"result": data})

    return invoke_tool_http(run_id, tool_name, payload)


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


def invoke_tool_for_api(body: ToolInvokeRequest, tool_name: str) -> ToolResult:
    run_id = body.run_id or uuid.uuid4()
    return invoke_tool_queued(
        run_id,
        tool_name,
        {
            "department": body.department,
            "user_id": body.user_id,
            "payload": body.payload,
        },
    )


@celery_app.task(name="platform_orchestrator.invoke_tool_async", bind=True, max_retries=3)
def invoke_tool_async(self, run_id: str, tool_name: str, payload: dict) -> dict:
    try:
        result = invoke_tool_queued(uuid.UUID(run_id), tool_name, payload)
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
        department = row.department
        user_id = row.user_id
        config_json = row.config_json
        tools_json = row.tools_json
        session.commit()

    tool_calls = _tool_calls_for_run(config_json, tools_json)
    if not tool_calls:
        tool_calls = [{"tool_name": "imap.list_unread", "payload": {}}] if settings.use_stubs else []

    errors: list[str] = []
    for call in tool_calls:
        tool_name = call.get("tool_name", "")
        if not tool_name:
            continue
        try:
            invoke_tool_queued(
                uuid.UUID(run_id),
                tool_name,
                {
                    "department": department,
                    "user_id": user_id,
                    "payload": call.get("payload") or {},
                },
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
