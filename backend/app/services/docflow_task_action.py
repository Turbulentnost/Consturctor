"""Запись по задаче 1С:Документооборот (SOAP perform / retrieve)."""

from __future__ import annotations

from typing import Any

from app.services.docflow_tasks import DocflowError, docflow_soap_ready
from app.tools.onec.dok_soap import load_config, perform_business_process_task, retrieve_tasks


def _session_credentials(args: dict[str, Any]) -> tuple[str, str]:
    user = str(args.get("fio") or args.get("erp_login") or args.get("username") or "").strip()
    password = str(args.get("password") or args.get("erp_password") or "").strip()
    return user, password


def handle_docflow_task_action(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> dict[str, Any]:
    del actor_user_id
    action = str(args.get("action") or "").strip().lower()
    task_id = str(args.get("task_id") or args.get("ref_key") or args.get("id") or "").strip()
    if not action:
        raise DocflowError("Укажите action (retrieve | execute | acquaint | reject | consider | approve)")
    if not docflow_soap_ready():
        raise DocflowError("SOAP документооборота не настроен (DOK_HTTP_*)")
    user, password = _session_credentials(args)
    if not password:
        user = user or actor_fio.strip()
    if not user:
        raise DocflowError("Нужны учётные данные сеанса 1С (ФИО и пароль)")
    config = load_config(username=user, password=password, require_user=True)
    if action == "retrieve":
        if not task_id:
            raise DocflowError("Для retrieve нужен task_id")
        rows = retrieve_tasks(config, [task_id], timeout=float(config.timeout))
        return {
            "summary": "Карточка задачи документооборота",
            "action": action,
            "task_id": task_id,
            "tasks": rows,
            "count": len(rows),
        }
    if not task_id:
        raise DocflowError("Для действия нужен task_id (ref_key из onec.docflow_tasks)")
    result = perform_business_process_task(config, task_id, action=action, timeout=float(config.timeout))
    labels = {
        "execute": "Исполнено",
        "acquaint": "Ознакомление",
        "reject": "Отказ от исполнения",
        "consider": "Рассмотрено",
        "approve": "Согласовано",
    }
    label = labels.get(action, action)
    return {
        "summary": f"{label}: задача отправлена в 1С:Документооборот",
        "action": action,
        "task_id": task_id,
        "result": result,
    }


def stub_docflow_task_action(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    return {
        "summary": "stub: docflow_task_action",
        "action": str(args.get("action") or ""),
        "ok": False,
        "message": "Настройте DOK_HTTP_* на backend для записи в документооборот",
    }
