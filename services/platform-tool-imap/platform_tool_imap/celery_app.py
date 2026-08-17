from __future__ import annotations

import os

from celery import Celery

broker = os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@127.0.0.1:5672//")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "rpc://")

celery_app = Celery("platform_tool_imap", broker=broker, backend=result_backend)
celery_app.conf.task_routes = {"platform_tool_imap.*": {"queue": "imap"}}
celery_app.conf.result_backend = result_backend


def _handler_table():
    from platform_tool_imap.main import REAL_HANDLERS, STUB_HANDLERS, _imap_ready, settings

    if _imap_ready():
        return REAL_HANDLERS
    if settings.use_stubs:
        return STUB_HANDLERS
    return REAL_HANDLERS


@celery_app.task(name="platform_tool_imap.invoke_async", bind=True, max_retries=3)
def invoke_async(self, tool_name: str, payload: dict) -> dict:
    from platform_contracts.tools import ToolInvokeRequest, ToolResult

    req = ToolInvokeRequest.model_validate(payload)
    table = _handler_table()
    handler = table.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    try:
        data = handler(req)
        return ToolResult(ok=True, tool_name=tool_name, data=data, duration_ms=0).model_dump(mode="json")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5) from exc


@celery_app.task(name="platform_tool_imap.poll_mailbox")
def poll_mailbox() -> dict:
    """Periodic IMAP check; enqueues fetch tasks when new mail is detected."""
    from platform_contracts.tools import ToolInvokeRequest
    from platform_tool_imap.main import IMAP_NOT_CONFIGURED, REAL_HANDLERS, _imap_ready

    if not _imap_ready():
        return {"polled": False, "error": IMAP_NOT_CONFIGURED}

    handler = REAL_HANDLERS.get("imap.list_unread")
    if handler is None:
        return {"polled": True, "new_messages": 0}
    result = handler(ToolInvokeRequest(payload={"source": "poll_mailbox"}))
    count = int(result.get("count", 0))
    if count > 0:
        invoke_async.delay(
            "imap.list_unread",
            ToolInvokeRequest(payload={"source": "poll_mailbox", "trigger": "new_mail"}).model_dump(
                mode="json"
            ),
        )
    return {"polled": True, "new_messages": count, "source": "imap"}
