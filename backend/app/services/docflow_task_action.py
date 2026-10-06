"""Действие по задаче 1С:Документооборот.

Завершение идёт в HTTP TaskAction базы ДО — ту же процедуру вызывают кнопки
формы 1С. Отметка SOAP (DMUpdateRequest) для кнопок не используется: она
обходит проверки документа. Чтение карточки и ссылка web_url остаются SOAP.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.docflow_tasks import DocflowError, docflow_soap_ready
from app.tools.onec.docflow_task_kinds import (
    ACTIONS,
    action_button,
    docflow_task_kind,
    resolve_action,
    web_client_task_url,
)
from app.tools.onec.dok_http import TaskActionNotPublished, post_task_action
from app.tools.onec.dok_soap import drop_task_from_inbox_cache, load_config, retrieve_tasks

logger = logging.getLogger(__name__)

_ACTION_NAMES = ", ".join(["retrieve", "web_url", "close", *ACTIONS])


def _session_credentials(args: dict[str, Any]) -> tuple[str, str]:
    user = str(args.get("fio") or args.get("erp_login") or args.get("username") or "").strip()
    password = str(args.get("password") or args.get("erp_password") or "").strip()
    return user, password


_UNPUBLISHED_SUMMARY = (
    "Действие доступно только в карточке 1С: метод TaskAction ещё не опубликован."
)


def _task_web_url(task_id: str) -> str:
    from app.config import settings

    return web_client_task_url(
        settings.dok_http_server,
        int(settings.dok_http_port or 81),
        settings.dok_http_base_path or "/doc",
        task_id,
    )


def _complete_docflow_task(args: dict[str, Any], *, actor_fio: str, action: str) -> dict[str, Any]:
    task_id = str(args.get("task_id") or args.get("uid") or args.get("ref_key") or args.get("id") or "").strip()
    if not task_id:
        raise DocflowError("Для действия нужен UID задачи")
    user, password = _session_credentials(args)
    if not password:
        user = user or actor_fio.strip()
    if not user or not password:
        raise DocflowError("Нужны учётные данные сеанса 1С (ФИО и пароль)")

    step = str(args.get("step") or "")
    title = str(args.get("title") or args.get("name") or "")
    kind = docflow_task_kind(step, title)
    resolved = resolve_action(action, kind)
    if not resolved:
        raise DocflowError(f"Для задачи «{step or title or 'без шага'}» это действие недоступно.")
    spec = ACTIONS[resolved]
    comment = " ".join(str(args.get("comment") or "").split())
    if spec.needs_comment and not comment:
        raise DocflowError("Для этого действия 1С требует комментарий.")
    button = action_button(kind, resolved)
    actual = str(args.get("actual_performer") or args.get("factual_performer") or "").strip()

    try:
        outcome = post_task_action(
            task_id,
            button,
            comment=comment,
            actual_performer=actual,
            auth=(user, password),
        )
    except TaskActionNotPublished:
        # Пока 1С не опубликовала ту же процедуру, что и кнопки формы,
        # SOAP-отметка обошла бы проверки документа. Карточку только открываем.
        logger.info("TaskAction не опубликован, задача %s не закрывается через SOAP", task_id)
        return {
            "ok": False,
            "closed": False,
            "needs_form": True,
            "summary": _UNPUBLISHED_SUMMARY,
            "action": resolved,
            "kind": kind,
            "button": button,
            "task_id": task_id,
            "web_url": _task_web_url(task_id),
        }
    except RuntimeError as exc:
        raise DocflowError(str(exc)) from exc

    summary = str(outcome.get("summary") or "").strip()
    closed = bool(outcome.get("closed"))
    if not summary:
        summary = spec.summary if closed else "Документооборот не закрыл задачу."
    if closed:
        drop_task_from_inbox_cache(task_id)
    return {
        "ok": bool(outcome.get("ok")),
        "closed": closed,
        "needs_form": bool(outcome.get("needs_form")),
        "summary": summary,
        "action": resolved,
        "kind": kind,
        "button": button,
        "task_id": task_id,
        "web_url": _task_web_url(task_id) if outcome.get("needs_form") else "",
    }


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
        raise DocflowError(f"Укажите action ({_ACTION_NAMES})")
    if action not in {"retrieve", "web_url"}:
        if action not in ACTIONS and action not in {"close", "reject"}:
            raise DocflowError(f"Неизвестное действие: {action}. Доступно: {_ACTION_NAMES}")
        return _complete_docflow_task(args, actor_fio=actor_fio, action=action)
    if not docflow_soap_ready():
        raise DocflowError("SOAP документооборота не настроен (DOK_HTTP_*)")
    user, password = _session_credentials(args)
    if not password:
        user = user or actor_fio.strip()
    if not user:
        raise DocflowError("Нужны учётные данные сеанса 1С (ФИО и пароль)")
    config = load_config(username=user, password=password, require_user=True)
    if not task_id:
        raise DocflowError(f"Для {action} нужен task_id")
    web_url = web_client_task_url(config.server, config.port, config.base_path, task_id)
    if action == "web_url":
        if not web_url:
            raise DocflowError("Не удалось собрать ссылку на карточку задачи")
        return {"summary": "Ссылка на карточку задачи", "action": action, "task_id": task_id, "web_url": web_url}
    rows = retrieve_tasks(config, [task_id], timeout=float(config.timeout))
    return {
        "summary": "Карточка задачи документооборота",
        "action": action,
        "task_id": task_id,
        "tasks": rows,
        "count": len(rows),
        "web_url": web_url,
    }


def stub_docflow_task_action(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    return {
        "summary": "stub: docflow_task_action",
        "action": str(args.get("action") or ""),
        "ok": False,
        "message": "Настройте DOK_HTTP_* на backend для записи в документооборот",
    }
