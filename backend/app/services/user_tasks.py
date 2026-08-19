"""Задачи пользователя — поручения и Action Tracker для текущего пользователя в 1С.

Источники (COM, Windows :7831):
- документооборот ТД: регистр ТД_ЗадачиПротоколов + Document.ТД_Поручения (табличная часть);
- ERP: Задача.ЗадачаИсполнителя (резерв, с артефактами).

Модуль зафиксирован для агентов «мои поручения / Action Tracker / Decision Log».
"""

from __future__ import annotations

from typing import Any

from app.services.docflow_tasks import fetch_docflow_assignments
from app.services.onec_com_tasks import (
    enrich_tasks_with_erp_artifacts,
    fetch_current_tasks_com,
    fetch_work_items_com,
)

MODULE_ID = "user_tasks"
MODULE_TITLE = "Задачи пользователя"


def fetch_user_tasks(*, fio: str = "", limit: int = 100, enrich_artifacts: bool = False) -> dict[str, Any]:
    """Поручения/задачи пользователя из документооборота (основной источник)."""
    payload = fetch_docflow_assignments(fio=fio, limit=limit)
    tasks = list(payload.get("tasks") or [])
    if enrich_artifacts and tasks:
        payload["tasks"] = enrich_tasks_with_erp_artifacts(tasks, fio=fio, limit=limit)
    payload["module"] = MODULE_ID
    payload["module_title"] = MODULE_TITLE
    return payload


def fetch_user_tasks_com_scope(
    *,
    fio: str = "",
    scope: str = "docflow",
    limit: int = 100,
    only_open: bool = True,
) -> dict[str, Any] | None:
    """Расширенный COM-запрос через query_work_items (docflow / erp_tasks / all)."""
    payload = fetch_work_items_com(
        fio=fio,
        scope=scope,
        limit=limit,
        only_open=only_open,
    )
    if not payload:
        return None
    payload["module"] = MODULE_ID
    payload["module_title"] = MODULE_TITLE
    return payload


def fetch_user_erp_tasks(*, fio: str = "", limit: int = 100) -> dict[str, Any] | None:
    """Резерв: задачи исполнителя ERP (Задача.ЗадачаИсполнителя)."""
    payload = fetch_current_tasks_com(fio=fio, limit=limit)
    if not payload:
        return None
    payload["module"] = MODULE_ID
    payload["module_title"] = MODULE_TITLE
    payload["source"] = payload.get("source") or "erp-performer-tasks"
    return payload
