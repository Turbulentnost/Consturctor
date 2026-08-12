from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.regulation import AgentDraft

logger = logging.getLogger(__name__)

DEFAULT_KPI_METRICS = [
    {
        "metric_id": "task_success_rate",
        "title": "Доля успешно закрытых задач",
        "kind": "rate",
        "source": "agent_task_reports",
        "threshold_min": 0.8,
        "weight": 1.0,
    }
]

PLATFORM_CARD_STATUSES = frozenset({"ready", "finalized"})


def list_allowed_tools(department: str) -> list[str]:
    allowed = settings.allowed_tools_for_department(department)
    if allowed is None:
        return sorted(_fallback_tool_catalog())
    return sorted(allowed)


def _fallback_tool_catalog() -> set[str]:
    return {
        "imap.list_unread",
        "imap.fetch_message",
        "imap.fetch_attachments",
        "imap.search",
        "onec.odata_get",
        "onec.odata_post",
        "onec.odata_patch",
        "onec.attach_file",
        "onec.sql_query",
        "com.list_apps",
        "com.connect",
        "com.invoke",
        "com.release",
        "fs.list",
        "fs.read",
        "fs.write",
        "fs.stat",
        "fs.move",
        "fs.copy",
        "shell.run",
        "browser.navigate",
        "browser.screenshot",
        "browser.click",
        "browser.extract_text",
    }


def sync_draft_to_platform_card(db: Session, draft: AgentDraft) -> str | None:
    """Publish agent draft as platform_core.agent_cards row (runtime agent_id = draft.id)."""
    if draft.status not in PLATFORM_CARD_STATUSES:
        return None

    tasks = []
    readiness = (draft.result_json or {}).get("readinessRunId")
    if readiness:
        tasks.append(
            {
                "task_id": "execute_regulation",
                "title": draft.title or "Выполнение регламента",
                "description": f"Должность: {draft.position}",
                "kpi_tags": ["accuracy"],
            }
        )

    payload = {
        "agent_id": draft.id,
        "title": draft.title or draft.id,
        "department": draft.department or "",
        "tasks_json": json.dumps(tasks, ensure_ascii=False),
        "kpi_metrics_json": json.dumps(DEFAULT_KPI_METRICS, ensure_ascii=False),
        "description": f"Создан из черновика агента ({draft.position})",
    }
    db.execute(
        text(
            """
            INSERT INTO platform_core.agent_cards (
                agent_id, title, description, department,
                tasks_json, kpi_metrics_json, interaction_mode, enabled
            ) VALUES (
                :agent_id, :title, :description, :department,
                :tasks_json, :kpi_metrics_json, 'pull', TRUE
            )
            ON CONFLICT (agent_id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                department = EXCLUDED.department,
                tasks_json = EXCLUDED.tasks_json,
                kpi_metrics_json = EXCLUDED.kpi_metrics_json,
                updated_at = NOW()
            """
        ),
        payload,
    )
    db.commit()
    logger.info("Platform agent card synced for draft %s", draft.id)
    return draft.id
