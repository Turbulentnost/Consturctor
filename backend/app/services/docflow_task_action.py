"""Запись по задаче 1С:Документооборот (завершение через DMUpdateRequest / retrieve)."""

from __future__ import annotations

import logging
from typing import Any

from app.services.docflow_tasks import DocflowError, docflow_soap_ready
from app.tools.onec.docflow_task_kinds import (
    ACTIONS,
    docflow_task_kind,
    resolve_action,
    web_client_task_url,
)
from app.tools.onec.dok_soap import (
    load_config,
    mark_task_executed,
    open_tasks_for_target,
    person_names_match,
    retrieve_task_card,
    retrieve_tasks,
)

logger = logging.getLogger(__name__)

_ACTION_NAMES = ", ".join(["retrieve", "web_url", "close", *ACTIONS])


def _session_credentials(args: dict[str, Any]) -> tuple[str, str]:
    user = str(args.get("fio") or args.get("erp_login") or args.get("username") or "").strip()
    password = str(args.get("password") or args.get("erp_password") or "").strip()
    return user, password


def _complete_docflow_task(args: dict[str, Any], *, actor_fio: str, action: str) -> dict[str, Any]:
    task_id = str(args.get("task_id") or args.get("uid") or args.get("ref_key") or args.get("id") or "").strip()
    if not task_id:
        raise DocflowError("Для действия нужен UID задачи")
    user, password = _session_credentials(args)
    if not password:
        user = user or actor_fio.strip()
    if not user or not password:
        raise DocflowError("Нужны учётные данные сеанса 1С (ФИО и пароль)")

    config = load_config(username=user, password=password, require_user=True)
    lookup_timeout = min(40.0, float(config.timeout))

    def task_is_executed(uid: str) -> bool:
        try:
            cards = retrieve_tasks(config, [uid], timeout=lookup_timeout)
        except RuntimeError as exc:
            logger.warning("Повторное чтение задачи %s не удалось: %s", uid, exc)
            return False
        if not cards:
            logger.warning("Документооборот не вернул карточку задачи %s", uid)
            return False
        logger.info("Карточка задачи %s после действия: %s", uid, cards[0])
        mark = str(cards[0].get("execution_mark") or "")
        # Пометка исполнения — единственный признак, который ДО ставит сам.
        return bool(cards[0].get("executed")) and mark.startswith("Executed")

    try:
        card = retrieve_task_card(config, task_id, timeout=lookup_timeout)
    except RuntimeError as exc:
        raise DocflowError(f"Карточка задачи не прочитана: {exc}") from exc
    performer = str(card.get("performer") or "")
    if performer and not person_names_match(user, performer):
        raise DocflowError(f"Задача назначена не вам (исполнитель: {performer}). Отметку не ставлю.")

    step = str(card.get("step") or args.get("step") or "")
    kind = docflow_task_kind(step, str(card.get("name") or ""))
    resolved = resolve_action(action, kind)
    if not resolved:
        raise DocflowError(f"Для задачи «{step or card.get('name') or 'без шага'}» это действие недоступно.")
    spec = ACTIONS[resolved]
    comment = " ".join(str(args.get("comment") or "").split())
    if spec.needs_comment and not comment:
        raise DocflowError("Для этого действия 1С требует комментарий.")

    # Доработка процесса создаёт задачу с новым УИД, а в таблице остаётся старый.
    targets = [task_id]
    if card.get("executed"):
        try:
            live = open_tasks_for_target(
                config,
                str(card.get("target_id") or ""),
                str(card.get("target_type") or ""),
                timeout=max(float(config.timeout), 120.0),
            )
        except RuntimeError as exc:
            logger.warning("Задачи документа %s не прочитаны: %s", card.get("target_id"), exc)
            live = []
        logger.info(
            "Задача %s уже завершена, открытых задач документа %s: %s",
            task_id,
            card.get("target_id"),
            "; ".join(f"{row.get('id')} {row.get('step')} {row.get('performer')}" for row in live)
            or "нет",
        )
        # Подменяем только на ту же задачу, выданную заново этому же исполнителю.
        # Остальные задачи по документу чужие или про другое — их не трогаем.
        targets = [
            str(row["id"])
            for row in live
            if person_names_match(user, str(row.get("performer") or ""))
            and str(row.get("performer") or "") == performer
            and str(row.get("description") or "") == str(card.get("description") or "")
            and str(row.get("step") or "") == str(card.get("step") or "")
        ]
        if not targets:
            return {
                "summary": "Задача уже завершена в документообороте.",
                "action": resolved,
                "kind": kind,
                "task_id": task_id,
                "already_executed": True,
            }

    # TaskPatch переносит срок и возвращает уже исполненную задачу на доработку,
    # поэтому задачу завершает только отметка исполнения.
    perform_error = ""
    closed: list[str] = []
    for uid in targets:
        try:
            mark_task_executed(config, uid, timeout=lookup_timeout, comment=comment, mark=spec.mark)
        except RuntimeError as exc:
            perform_error = str(exc)
            logger.warning("Отметка %s по задаче %s не прошла: %s", spec.mark, uid, exc)
            continue
        if task_is_executed(uid):
            closed.append(uid)

    if closed:
        return {
            "summary": f"{spec.summary} в документообороте.",
            "action": resolved,
            "kind": kind,
            "execution_mark": spec.mark,
            "task_id": closed[0],
            "closed_task_ids": closed,
        }
    detail = perform_error or "1С не сообщила причину."
    if "абстрактного типа" in perform_error:
        from app.tools.onec.dok_soap import dm_request_type_names

        try:
            names = dm_request_type_names(config, timeout=lookup_timeout)
        except RuntimeError as exc:
            logger.warning("Список типов DM не получен: %s", exc)
        else:
            task_names = [name for name in names if "Task" in name] or names
            logger.info("dok_soap запросы задач: %s", ", ".join(task_names))
            detail = "Сервис не знает наш тип запроса. Он принимает: " + ", ".join(task_names[:20])
    raise DocflowError(f"Документооборот не принял действие «{spec.summary}». {detail}")


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
