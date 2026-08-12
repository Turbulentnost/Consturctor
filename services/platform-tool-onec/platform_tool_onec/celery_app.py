from __future__ import annotations

import os

from celery import Celery

broker = os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@127.0.0.1:5672//")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "rpc://")

celery_app = Celery("platform_tool_onec", broker=broker, backend=result_backend)
celery_app.conf.task_routes = {"platform_tool_onec.*": {"queue": "onec"}}
celery_app.conf.result_backend = result_backend
celery_app.conf.task_annotations = {"platform_tool_onec.invoke_async": {"rate_limit": "10/m"}}


@celery_app.task(name="platform_tool_onec.invoke_async", bind=True, max_retries=5)
def invoke_async(self, tool_name: str, payload: dict) -> dict:
    from platform_contracts.tools import ToolInvokeRequest, ToolResult
    from platform_tool_onec.main import REAL_HANDLERS, STUB_HANDLERS, settings

    req = ToolInvokeRequest.model_validate(payload)
    table = STUB_HANDLERS if settings.use_stubs else REAL_HANDLERS
    handler = table.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    try:
        data = handler(req)
        return ToolResult(ok=True, tool_name=tool_name, data=data, duration_ms=0).model_dump(mode="json")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc


@celery_app.task(name="platform_tool_onec.poll_events")
def poll_events() -> dict:
    """Periodic 1C OData change detection; enqueues tool tasks on new events."""
    from platform_contracts.tools import ToolInvokeRequest
    from platform_tool_onec.main import REAL_HANDLERS, STUB_HANDLERS, settings

    if settings.use_stubs:
        invoke_async.delay(
            "onec.odata_get",
            ToolInvokeRequest(payload={"source": "poll_events", "path": "/stub/changes"}).model_dump(
                mode="json"
            ),
        )
        return {"polled": True, "stub": True, "enqueued": "onec.odata_get"}

    handler = REAL_HANDLERS.get("onec.odata_get")
    if handler is None:
        return {"polled": True, "changes": 0}
    result = handler(
        ToolInvokeRequest(payload={"source": "poll_events", "path": "/Document_Changes"})
    )
    changes = int(result.get("count", 0))
    if changes > 0:
        invoke_async.delay(
            "onec.odata_get",
            ToolInvokeRequest(
                payload={"source": "poll_events", "path": "/Document_Changes", "trigger": "new_event"}
            ).model_dump(mode="json"),
        )
    return {"polled": True, "changes": changes}
