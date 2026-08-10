from __future__ import annotations

import os

from celery import Celery

broker = os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@127.0.0.1:5672//")

celery_app = Celery("platform_tool_onec", broker=broker)
celery_app.conf.task_routes = {"platform_tool_onec.*": {"queue": "onec"}}
celery_app.conf.task_annotations = {"platform_tool_onec.invoke_async": {"rate_limit": "10/m"}}


@celery_app.task(name="platform_tool_onec.invoke_async", bind=True, max_retries=5)
def invoke_async(self, tool_name: str, payload: dict) -> dict:
    from platform_contracts.tools import ToolInvokeRequest
    from platform_tool_onec.main import REAL_HANDLERS, STUB_HANDLERS, settings

    req = ToolInvokeRequest.model_validate(payload)
    table = STUB_HANDLERS if settings.use_stubs else REAL_HANDLERS
    handler = table.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    try:
        return handler(req)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc
