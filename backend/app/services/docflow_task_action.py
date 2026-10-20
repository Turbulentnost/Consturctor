"""Действие по задаче 1С:Документооборот.

Сначала HTTP TaskAction. Если метод закрыл задачу или вернул отказ текстом,
этот ответ и есть результат. Пустая таблица и неопубликованный метод задачу
не меняют — тогда ту же кнопку закрывает отметка SOAP (DMUpdateRequest),
как до перевода кнопок на TaskAction. Чтение карточки и ссылка web_url остаются SOAP.
"""

from __future__ import annotations

import logging
import re
import time
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
from app.tools.onec.dok_soap import (
    drop_task_from_inbox_cache,
    is_object_locked_error,
    load_config,
    mark_task_executed,
    open_tasks_for_target,
    retrieve_tasks,
)

logger = logging.getLogger(__name__)

_ACTION_NAMES = ", ".join(["retrieve", "web_url", "close", "close_without_report", *ACTIONS])


def _session_credentials(args: dict[str, Any]) -> tuple[str, str]:
    user = str(args.get("fio") or args.get("erp_login") or args.get("username") or "").strip()
    password = str(args.get("password") or args.get("erp_password") or "").strip()
    return user, password


def _task_web_url(task_id: str) -> str:
    from app.config import settings

    return web_client_task_url(
        settings.dok_http_server,
        int(settings.dok_http_port or 81),
        settings.dok_http_base_path or "/doc",
        task_id,
    )


def _return_for_rework(
    args: dict[str, Any],
    *,
    user: str,
    password: str,
    comment: str,
    kind: str,
) -> dict[str, Any]:
    """Вернуть проверку в том же процессе с новым сроком и комментарием в истории."""
    from app.tools.onec.dok_create import parse_due
    from app.tools.onec.dok_rework import ReworkError, return_task_for_rework

    task_id = str(args.get("task_id") or args.get("uid") or args.get("ref_key") or args.get("id") or "").strip()
    due_raw = str(args.get("due") or args.get("new_due") or args.get("due_date") or "").strip()
    if not due_raw:
        raise DocflowError("Для возврата на доработку нужен новый срок")
    try:
        due = parse_due(due_raw)
    except ValueError as exc:
        raise DocflowError(str(exc)) from exc
    if due is None:
        raise DocflowError("Для возврата на доработку нужен новый срок")
    config = load_config(username=user, password=password, require_user=True)
    try:
        result = return_task_for_rework(
            config,
            task_id,
            due=due,
            comment=comment,
            timeout=float(config.timeout),
        )
    except ReworkError as exc:
        raise DocflowError(str(exc)) from exc
    except RuntimeError as exc:
        raise DocflowError(str(exc)) from exc
    drop_task_from_inbox_cache(task_id)
    return {
        "ok": True,
        "closed": True,
        "needs_form": False,
        "summary": str(result.get("summary") or ""),
        "action": "return",
        "kind": kind,
        "task_id": task_id,
        "new_task_id": result.get("new_task_id") or "",
        "business_process_id": result.get("business_process_id") or "",
        "due": result.get("due") or "",
        "web_url": "",
    }


_TASK_NO_RE = re.compile(r"№\s*(\d+)")
_CHECK_WAIT_ATTEMPTS = 6
_CHECK_WAIT_SEC = 1.5


def _mark_executed(config: Any, task_id: str, *, comment: str) -> None:
    try:
        row = mark_task_executed(config, task_id, timeout=float(config.timeout), comment=comment)
    except RuntimeError as exc:
        raise DocflowError(str(exc)) from exc
    if not row.get("executed"):
        raise DocflowError("Документооборот не отметил задачу выполненной.")
    drop_task_from_inbox_cache(task_id)


def _open_checks(config: Any, execute: dict[str, Any]) -> list[dict[str, Any]]:
    rows = open_tasks_for_target(
        config,
        str(execute.get("target_id") or ""),
        str(execute.get("target_type") or ""),
        timeout=float(config.timeout),
    )
    return [
        row
        for row in rows
        if docflow_task_kind(str(row.get("step") or ""), str(row.get("name") or "")) == "check"
    ]


def _next_check_task(config: Any, execute: dict[str, Any], before: set[str]) -> dict[str, Any] | None:
    """«Проверка исполнения», которую ДО выпускает автору после закрытия задачи исполнителя.

    Сначала — проверка, появившаяся после закрытия; иначе — с тем же «№N».
    """
    number = _TASK_NO_RE.search(str(execute.get("name") or ""))
    for attempt in range(_CHECK_WAIT_ATTEMPTS):
        checks = _open_checks(config, execute)
        fresh = [row for row in checks if str(row.get("id") or "") not in before]
        if len(fresh) == 1:
            return fresh[0]
        if number:
            checks = [row for row in checks if (m := _TASK_NO_RE.search(str(row.get("name") or ""))) and m.group(1) == number.group(1)]
        if len(checks) == 1:
            return checks[0]
        if attempt + 1 < _CHECK_WAIT_ATTEMPTS:
            time.sleep(_CHECK_WAIT_SEC)
    return None


def _close_without_report(args: dict[str, Any], *, user: str, password: str) -> dict[str, Any]:
    """Автор закрывает мероприятие без отчёта: задача исполнителя, затем приём проверки.

    Оба шага — SOAP-отметка исполнения (как при возврате на доработку): в базе ДО
    нет HTTP TaskAction. Мероприятие становится «принято проверяющим» — так же,
    как после обычного отчёта и приёма исполнения.
    """
    task_id = str(args.get("task_id") or args.get("ref_key") or args.get("id") or "").strip()
    if not task_id:
        raise DocflowError("Нужен UID задачи исполнителя")
    reason = " ".join(str(args.get("comment") or "").split())
    comment = "Закрыто автором без отчёта исполнителя" + (f": {reason}" if reason else ".")
    config = load_config(username=user, password=password, require_user=True)
    rows = retrieve_tasks(config, [task_id], timeout=float(config.timeout))
    if not rows:
        raise DocflowError("Задача исполнителя не найдена в Документообороте")
    execute = rows[0]
    kind = docflow_task_kind(str(execute.get("step") or ""), str(execute.get("name") or ""))
    if kind != "execute":
        raise DocflowError("«Закрыть без отчёта» закрывает задачу исполнителя «Исполнить», а не проверку")
    before: set[str] = set()
    if not execute.get("executed"):
        before = {str(row.get("id") or "") for row in _open_checks(config, execute)}
        _mark_executed(config, task_id, comment=comment)
    check = _next_check_task(config, execute, before)
    if check is None:
        return {
            "ok": True,
            "closed": True,
            "line_closed": False,
            "task_id": task_id,
            "summary": "Задача исполнителя закрыта. «Проверка исполнения» ещё не пришла — примите её, когда появится.",
        }
    check_id = str(check.get("id") or "")
    _mark_executed(config, check_id, comment=comment)
    logger.info("Мероприятие закрыто автором без отчёта: исполнение %s, проверка %s", task_id, check_id)
    return {
        "ok": True,
        "closed": True,
        "line_closed": True,
        "task_id": task_id,
        "check_task_id": check_id,
        "summary": "Мероприятие закрыто: задача исполнителя выполнена автором, исполнение принято.",
    }


def _task_action_answered(outcome: dict[str, Any]) -> bool:
    """TaskAction реально закрыл задачу или вернул текст отказа, а не пустую таблицу."""
    if outcome.get("closed") or outcome.get("needs_form"):
        return True
    summary = str(outcome.get("summary") or "").strip()
    return bool(summary) and not summary.startswith('{"#')


def _close_by_mark(
    task_id: str,
    *,
    user: str,
    password: str,
    comment: str,
    mark: str,
    summary: str,
    resolved: str,
    kind: str,
    button: int,
) -> dict[str, Any]:
    """Отметка исполнения SOAP: executed и executionMark. Так кнопки закрывали задачу раньше."""
    config = load_config(username=user, password=password, require_user=True)
    try:
        row = mark_task_executed(
            config,
            task_id,
            timeout=float(config.timeout),
            comment=comment,
            mark=mark,
        )
    except RuntimeError as exc:
        text = str(exc)
        if is_object_locked_error(text):
            raise DocflowError(
                "Задача сейчас заблокирована в 1С. Подождите минуту и нажмите кнопку снова."
            ) from exc
        raise DocflowError(f"Документооборот не принял действие «{summary}». {text}") from exc
    if not row.get("executed"):
        raise DocflowError("Документооборот не отметил задачу выполненной.")
    drop_task_from_inbox_cache(task_id)
    return {
        "ok": True,
        "closed": True,
        "needs_form": False,
        "summary": summary,
        "action": resolved,
        "kind": kind,
        "button": button,
        "task_id": task_id,
        "execution_mark": mark,
        "web_url": "",
    }


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
    if resolved == "return":
        return _return_for_rework(args, user=user, password=password, comment=comment, kind=kind)
    button = action_button(kind, resolved)
    actual = str(args.get("actual_performer") or args.get("factual_performer") or "").strip()

    outcome: dict[str, Any] | None = None
    try:
        outcome = post_task_action(
            task_id,
            button,
            comment=comment,
            actual_performer=actual,
            auth=(user, password),
        )
    except TaskActionNotPublished:
        logger.info("TaskAction не опубликован, задача %s закрывается отметкой SOAP", task_id)
    except RuntimeError as exc:
        raise DocflowError(str(exc)) from exc

    if outcome is not None and _task_action_answered(outcome):
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

    logger.info(
        "TaskAction не закрыл задачу %s, ставлю отметку SOAP %s",
        task_id,
        spec.mark,
    )
    return _close_by_mark(
        task_id,
        user=user,
        password=password,
        comment=comment,
        mark=spec.mark,
        summary=spec.summary,
        resolved=resolved,
        kind=kind,
        button=button,
    )


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
    if action == "close_without_report":
        user, password = _session_credentials(args)
        if not user or not password:
            raise DocflowError("Нужны учётные данные сеанса 1С (ФИО и пароль)")
        return _close_without_report(args, user=user, password=password)
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


def handle_docflow_rework(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> dict[str, Any]:
    """Инструмент onec.docflow_rework: возврат проверки в том же процессе."""
    del actor_user_id
    user, password = _session_credentials(args)
    if not password:
        user = user or actor_fio.strip()
    if not user or not password:
        raise DocflowError("Нужны учётные данные сеанса 1С (ФИО и пароль)")
    comment = " ".join(str(args.get("comment") or "").split())
    if not comment:
        raise DocflowError("Для возврата на доработку нужен комментарий.")
    step = str(args.get("step") or "")
    title = str(args.get("title") or args.get("name") or "")
    kind = docflow_task_kind(step, title) if step or title else "check"
    return _return_for_rework(args, user=user, password=password, comment=comment, kind=kind)


def stub_docflow_rework(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    return {
        "summary": "stub: docflow_rework",
        "ok": False,
        "task_id": str(args.get("task_id") or ""),
        "message": "Настройте DOK_HTTP_* на backend для возврата задачи на доработку",
    }


def stub_docflow_task_action(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    return {
        "summary": "stub: docflow_task_action",
        "action": str(args.get("action") or ""),
        "ok": False,
        "message": "Настройте DOK_HTTP_* на backend для записи в документооборот",
    }
