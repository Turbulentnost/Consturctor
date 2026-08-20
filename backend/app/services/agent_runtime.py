from __future__ import annotations

import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.services.local_mcp import list_tools
from app.services.onec_tools import ONEC_TOOLS as _ONEC_TOOLS
from app.services.onec_tools import ONEC_WRITE_TOOLS as _ONEC_WRITE_TOOLS
from app.services.plan_run import (
    PlanRunError,
    build_plan_export_arguments,
    format_plan_run_answer,
    uses_plan_export,
)
from app.services.tool_bridge import CONFIRM_TIMEOUT_S, DEFAULT_TIMEOUT_S, tool_bridge


AgentEventCallback = Callable[[dict[str, Any]], None]

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

_IMAP_TOOLS = frozenset(
    {
        "imap.list_unread",
        "imap.search",
        "imap.fetch_message",
        "imap.fetch_attachments",
    }
)
_TURBOPROJECT_TOOLS = frozenset({"turboproject", "turboproject.projects"})


class AgentRuntimeError(RuntimeError):
    pass


def available_tools() -> list[dict[str, Any]]:
    return list_tools()


def run_agent_task(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    message: str,
    emit: AgentEventCallback,
    run_id: str,
    history_id: str = "",
) -> dict[str, Any]:
    workflow = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .first()
    )
    if workflow is None:
        raise AgentRuntimeError("Workflow не найден")
    task = message.strip()
    if not task:
        raise AgentRuntimeError("Пустая задача")

    emit({"type": "status", "text": "Получил задачу, готовлю запуск…"})
    emit({"type": "agent_message", "text": f"Запускаю «{workflow.title or 'ИИ-агент'}»."})

    from app.services.workflows.service import playbook_of

    playbook = playbook_of(workflow)
    if str(playbook.get("instructions") or "").strip():
        return _run_with_playbook(
            db,
            workflow=workflow,
            user_id=user_id,
            message=task,
            emit=emit,
            run_id=run_id,
            playbook=playbook,
            history_id=history_id,
        )

    domain = _agent_domain(workflow)

    # Rules come from THIS agent's plan (runtime / constraints / answers), not globals.
    # Outlook/meetings must never fall into tender Excel export or web_search.
    if domain != "outlook_calendar" and uses_plan_export(workflow):
        emit({"type": "status", "text": "Читаю правила из паспорта этого агента…"})
        emit(
            {
                "type": "agent_message",
                "text": (
                    "Выполняю по правилам из ответов при создании: поиск по ключам, "
                    "Excel с указанными колонками, сохранение куда указано в плане."
                ),
            }
        )
        try:
            arguments = build_plan_export_arguments(workflow)
        except PlanRunError as exc:
            emit({"type": "error", "message": str(exc)})
            raise AgentRuntimeError(str(exc)) from exc

        try:
            result = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
                tool="plan_export",
                arguments=arguments,
            )
        except AgentRuntimeError as exc:
            emit({"type": "error", "message": str(exc)})
            raise

        answer = format_plan_run_answer(result)
        emit({"type": "tool_result", "tool": "plan_export", "result": result})
        emit({"type": "agent_message", "text": answer})
        return {"answer": answer, "tool": "plan_export", "tool_result": result}

    if domain == "outlook_calendar":
        emit({"type": "status", "text": "Читаю Outlook на этом компьютере…"})
        outlook_tool, outlook_args = _outlook_tool_request(task)
        try:
            tool_result = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
                tool=outlook_tool,
                arguments=outlook_args,
            )
        except AgentRuntimeError as exc:
            emit({"type": "error", "message": str(exc)})
            raise
        emit({"type": "tool_result", "tool": outlook_tool, "result": tool_result})
        answer = _compose_outlook_tool_answer(task, outlook_tool, tool_result)
        emit({"type": "agent_message", "text": answer})
        return {"answer": answer, "tool": outlook_tool, "tool_result": tool_result}

    if domain == "onec":
        emit({"type": "status", "text": "Ищу документы 1С на этом компьютере…"})
        try:
            tool_result = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
                tool="onec.search_documents",
                arguments={"query": task, "max_results": 10},
            )
        except AgentRuntimeError as exc:
            emit({"type": "error", "message": str(exc)})
            raise
        emit({"type": "tool_result", "tool": "onec.search_documents", "result": tool_result})
        answer = _compose_onec_desktop_answer(tool_result)
        emit({"type": "agent_message", "text": answer})
        return {
            "answer": answer,
            "tool": "onec.search_documents",
            "tool_result": tool_result,
        }

    tool_name = ""
    tool_result: dict[str, Any] | None = None
    arguments: dict[str, Any] = {}

    browser_args = _site_browser_args(task, workflow)
    if browser_args:
        tool_name = "site_browser"
        arguments = browser_args
        emit({"type": "thinking", "text": "Открываю указанный сайт и собираю данные.\n"})
    else:
        query = _search_query(task, workflow)
        if query:
            tool_name = "web_search"
            arguments = {"query": query, "max_results": 8, "fetch_top": False}
            emit({"type": "thinking", "text": "Ищу информацию в интернете.\n"})

    if tool_name:
        try:
            tool_result = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
                tool=tool_name,
                arguments=arguments,
            )
        except AgentRuntimeError as exc:
            emit({"type": "error", "message": str(exc)})
            raise
        emit({"type": "tool_result", "tool": tool_name, "result": tool_result})

    answer = _compose_answer(task, tool_name, tool_result)
    emit({"type": "agent_message", "text": answer})
    return {"answer": answer, "tool": tool_name, "tool_result": tool_result or {}}


def _run_with_playbook(
    db: Session,
    *,
    workflow: Workflow,
    user_id: str,
    message: str,
    emit: AgentEventCallback,
    run_id: str,
    playbook: dict[str, Any],
    history_id: str = "",
) -> dict[str, Any]:
    from app.clients import cursor as cursor_client
    from app.clients.cursor import CursorAgentError
    from app.services.workflows import prompts
    from app.services.workflows.cursor_tools import (
        set_tool_context,
        stream_cursor_with_tools,
        wants_notifications,
        with_tools_if_desktop,
    )
    from app.services.workflows.service import _create_exec_agent, _stream_run

    set_tool_context(run_id, user_id, history_id)
    plan_text = _playbook_plan_text(playbook, workflow)
    if plan_text:
        emit({"type": "plan", "title": "План", "text": plan_text})
    prompt = with_tools_if_desktop(
        prompts.build_published_run_prompt(
            instructions=str(playbook.get("instructions") or ""),
            example_run=str(playbook.get("example_run") or ""),
            user_message=message,
            title=workflow.title or "",
        )
    )
    emit({"type": "status", "text": "Запускаю Cursor по инструкции и примеру прогона…"})

    def on_event(event_type: str, text: str = "", extra: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"type": event_type}
        if text:
            payload["text"] = text
        if extra:
            payload.update(extra)
        emit(payload)

    try:
        agent_id = str(workflow.exec_agent_id or "")
        if agent_id:
            try:
                run = cursor_client.create_run_when_ready(
                    agent_id,
                    prompt=prompt,
                    mode="agent",
                    previous_run_id=str(workflow.exec_run_id or ""),
                )
                cursor_run_id = str(run.get("id") or "")
            except CursorAgentError:
                agent_id, cursor_run_id = _create_exec_agent(workflow.title or "агент", prompt)
                workflow.exec_agent_id = agent_id
                db.commit()
        else:
            agent_id, cursor_run_id = _create_exec_agent(workflow.title or "агент", prompt)
            workflow.exec_agent_id = agent_id
            db.commit()
        if not agent_id or not cursor_run_id:
            raise AgentRuntimeError("Cursor не вернул agent/run")
        required = ["notify"] if wants_notifications(
            str(playbook.get("instructions") or ""),
            message,
            str(workflow.notes or ""),
        ) else []
        phase = stream_cursor_with_tools(
            agent_id=agent_id,
            run_id=cursor_run_id,
            on_event=on_event,
            workflow_id=workflow.id,
            mode="execute",
            stream_run=_stream_run,
            required_live_tools=required,
        )
    except CursorAgentError as exc:
        emit({"type": "error", "message": exc.message})
        raise AgentRuntimeError(exc.message) from exc
    finally:
        from app.services.workflows.cursor_tools import clear_tool_context

        clear_tool_context()

    work = prompts.parse_work_result(phase.text or "")
    answer = (work.get("text") or "").strip() or "Прогон завершён."
    emit(
        {
            "type": "work_result",
            "text": answer,
            "files": work.get("files") or [],
            "actions": work.get("actions") or [],
            "notifications": work.get("notifications") or [],
        }
    )
    local = dict(workflow.local_run or {})
    local["work_result"] = work
    workflow.local_run = local
    workflow.last_result = answer
    db.commit()
    return {
        "answer": answer,
        "work_result": work,
        "tool": "cursor",
        "tool_result": {"tools": list(phase.successful_live_tools or [])},
    }


def _playbook_plan_text(playbook: dict[str, Any], workflow: Workflow) -> str:
    steps = playbook.get("steps") if isinstance(playbook.get("steps"), list) else []
    if not steps:
        local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
        draft = local.get("playbook_draft") if isinstance(local.get("playbook_draft"), dict) else {}
        steps = draft.get("steps") if isinstance(draft.get("steps"), list) else []
    lines: list[str] = []
    goal = str(playbook.get("goal") or "").strip()
    if goal:
        lines.append(f"Цель: {goal}")
    numbered = [step for step in steps if isinstance(step, dict)]
    if numbered:
        if lines:
            lines.append("")
        lines.append("Шаги:")
        for index, step in enumerate(numbered, start=1):
            sid = str(step.get("id") or f"s{index}").strip()
            title = str(step.get("title") or "").strip()
            action = str(step.get("action") or "").strip()
            head = f"{sid} — {title}".strip(" —") if sid or title else f"шаг {index}"
            lines.append(head)
            if action:
                lines.append(f"  {action}")
    return "\n".join(lines).strip()


def _agent_domain(workflow: Workflow) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    kind = str(runtime.get("kind") or "").strip().casefold()
    if kind in {"outlook_calendar", "site_search_excel", "browser_task", "onec"}:
        return kind
    answered = plan.get("answered_questions") or []
    answered_text = ""
    if isinstance(answered, list):
        answered_text = " ".join(
            f"{x.get('question', '')} {x.get('answer', '')}"
            for x in answered
            if isinstance(x, dict)
        )
    elif isinstance(answered, dict):
        answered_text = " ".join(f"{k} {v}" for k, v in answered.items())
    open_qs = plan.get("open_questions") or []
    open_text = ""
    if isinstance(open_qs, list):
        open_text = " ".join(
            f"{x.get('question', '')} {x.get('answer', '')}"
            for x in open_qs
            if isinstance(x, dict)
        )
    blob = " ".join(
        [
            str(workflow.title or ""),
            str(workflow.notes or ""),
            str(plan.get("title") or ""),
            str(plan.get("goal") or ""),
            " ".join(str(x) for x in (plan.get("constraints") or [])),
            " ".join(str(x) for x in (plan.get("test_criteria") or [])),
            answered_text,
            open_text,
        ]
    ).casefold()
    if any(tip in blob for tip in ("1с", "1c", "onec", "odata", "erp_pm", "задач")) and "outlook" not in blob:
        return "onec"
    if any(
        tip in blob
        for tip in (
            "outlook",
            "календар",
            "совещан",
            "встреч",
            "занятост",
            "confirm_slot",
        )
    ):
        return "outlook_calendar"
    if ("excel" in blob or "xlsx" in blob) and (
        "ключев" in blob or "этп" in blob or "сайт" in blob
    ):
        return "site_search_excel"
    return ""


def _await_human_confirm_runtime(
    emit: AgentEventCallback,
    *,
    run_id: str,
    user_id: str,
    tool: str,
    arguments: dict[str, Any],
) -> None:
    request_id = tool_bridge.new_request_id()
    tool_bridge.begin_wait(request_id=request_id, user_id=user_id)
    emit({"type": "status", "text": f"жду подтверждения: {tool}"})
    emit(
        {
            "type": "tool_request",
            "run_id": run_id,
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
            "confirm_only": True,
        }
    )
    try:
        payload = tool_bridge.await_result(
            request_id=request_id,
            timeout_s=CONFIRM_TIMEOUT_S,
        )
    except TimeoutError as exc:
        raise AgentRuntimeError(str(exc)) from exc
    if not payload.get("ok"):
        raise AgentRuntimeError(str(payload.get("error") or "отклонено человеком"))


def _request_desktop_tool(
    emit: AgentEventCallback,
    *,
    run_id: str,
    user_id: str,
    tool: str,
    arguments: dict[str, Any],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    workflow_id: str = "",
) -> dict[str, Any]:
    arguments = dict(arguments)
    if workflow_id:
        arguments.setdefault("workflow_id", workflow_id)
        arguments.setdefault("agent_id", workflow_id)
    if tool.startswith("imap.") or tool in _IMAP_TOOLS:
        return _invoke_imap_server(tool, arguments)
    if tool in _ONEC_TOOLS:
        if tool in _ONEC_WRITE_TOOLS:
            _await_human_confirm_runtime(
                emit,
                run_id=run_id,
                user_id=user_id,
                tool=tool,
                arguments=arguments,
            )
        return _invoke_onec_server(tool, arguments, user_id=user_id)
    if tool in _TURBOPROJECT_TOOLS or tool.startswith("turboproject"):
        return _invoke_turboproject_server(tool, arguments)

    request_id = tool_bridge.new_request_id()
    tool_bridge.begin_wait(request_id=request_id, user_id=user_id)
    emit({"type": "tool_call", "tool": tool, "arguments": arguments})
    emit(
        {
            "type": "tool_request",
            "run_id": run_id,
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        }
    )
    try:
        payload = tool_bridge.await_result(
            request_id=request_id,
            timeout_s=timeout_s,
        )
    except TimeoutError as exc:
        raise AgentRuntimeError(str(exc)) from exc

    if not payload.get("ok"):
        raise AgentRuntimeError(str(payload.get("error") or f"Ошибка инструмента {tool}"))
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def _invoke_turboproject_server(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.services.turboproject import TurboProjectError, invoke_turboproject

    try:
        return invoke_turboproject(tool, arguments)
    except TurboProjectError as exc:
        raise AgentRuntimeError(str(exc)) from exc


def _invoke_imap_server(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.services.imap_tools import ImapToolError, invoke_imap

    try:
        return invoke_imap(tool, arguments)
    except ImapToolError as exc:
        raise AgentRuntimeError(str(exc)) from exc


def _invoke_onec_server(
    tool: str,
    arguments: dict[str, Any],
    *,
    user_id: str = "",
) -> dict[str, Any]:
    from app.services.app_users import get_app_user
    from app.services.onec_tools import OnecToolError, invoke_onec

    fio = ""
    if user_id:
        user = get_app_user(user_id)
        if user is not None:
            fio = str(user.fio or "")
    try:
        return invoke_onec(tool, arguments, actor_user_id=user_id, actor_fio=fio)
    except OnecToolError as exc:
        raise AgentRuntimeError(str(exc)) from exc


def _extract_url(text: str) -> str:
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(").,;") if m else ""


def _plan_site_url(workflow: Workflow) -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    url = str(runtime.get("site_url") or "").strip()
    if url:
        return url
    for c in plan.get("constraints") or []:
        found = _extract_url(str(c))
        if found:
            return found
    return ""


def _keyword_from_task(task: str, workflow: Workflow) -> str:
    """Short search keyword from the user task / plan keywords — no domain dictionaries."""
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    keywords = runtime.get("keywords") if isinstance(runtime.get("keywords"), list) else []
    if keywords:
        return str(keywords[0]).strip()[:80]

    text = _URL_RE.sub("", task or "")
    text = re.sub(r"[«»\"']", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-:")
    words = [w for w in text.split() if len(w) > 2][:6]
    return " ".join(words)[:120] if words else ""


def _search_query(task: str, workflow: Workflow) -> str:
    kw = _keyword_from_task(task, workflow)
    return kw or (workflow.title or task)[:120]


def _outlook_tool_request(task: str) -> tuple[str, dict[str, Any]]:
    low = (task or "").casefold()
    if any(tip in low for tip in ("письм", "почт", "mail", "inbox", "входящ", "отправлен")):
        return "outlook.search_mail", {
            "query": task,
            "folder": "All",
            "max_results": 20,
        }
    return "outlook.read_calendar", {"days_forward": 7, "max_results": 30}


def _compose_outlook_tool_answer(
    task: str, tool_name: str, tool_result: dict[str, Any]
) -> str:
    _ = task
    if tool_name == "outlook.search_mail":
        messages = tool_result.get("messages") or []
        if not messages:
            return "В Outlook писем по запросу не найдено."
        lines = [f"Нашла писем: {len(messages)}"]
        for item in messages[:10]:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject") or "Без темы")
            sender = str(item.get("sender") or item.get("from") or "")
            lines.append(f"• {subject}" + (f" — {sender}" if sender else ""))
        return "\n".join(lines)
    events = tool_result.get("events") or []
    if not events:
        return "В календаре Outlook событий за выбранный период нет."
    lines = [f"События календаря: {len(events)}"]
    for item in events[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("subject") or item.get("title") or "Без названия")
        start = str(item.get("start") or item.get("start_time") or "")
        lines.append(f"• {title}" + (f" ({start})" if start else ""))
    return "\n".join(lines)


def _compose_onec_desktop_answer(tool_result: dict[str, Any]) -> str:
    documents = tool_result.get("documents") or []
    if not documents:
        return "Документы 1С не найдены."
    lines = [f"Найдено документов 1С: {len(documents)}"]
    for item in documents[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("number") or "Документ")
        status = str(item.get("status") or "")
        lines.append(f"• {title}" + (f" — {status}" if status else ""))
    return "\n".join(lines)


def _compose_outlook_answer(task: str, workflow: Workflow) -> str:
    """Answer meeting/calendar tasks from the plan — do not call site_browser."""
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    goal = str(plan.get("goal") or workflow.title or "").strip()
    constraints = [
        str(x).strip() for x in (plan.get("constraints") or []) if str(x).strip()
    ]
    criteria = [
        str(x).strip() for x in (plan.get("test_criteria") or []) if str(x).strip()
    ]
    answered = _answered_pairs(plan)
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []

    lines = [
        f"Задача: {(task or '').strip() or 'выполнить рабочий сценарий агента'}",
        "",
        "Работаю как агент планирования совещаний по правилам своего плана. "
        "Календарь Outlook пока не подключён напрямую в этом чате, поэтому "
        "не лезу в «просмотр сайта».",
        "",
    ]
    if goal:
        lines.append(f"Цель из плана: {goal}")
    if answered:
        lines.append("Ваши ответы при создании (обязательны):")
        for question, answer in answered[:12]:
            lines.append(f"• {question}: {answer}")
    if constraints:
        lines.append("Правила из паспорта / уточнений:")
        for item in constraints[:8]:
            lines.append(f"• {item}")
    if steps:
        lines.append("Шаги плана:")
        for step in steps[:8]:
            if isinstance(step, dict):
                sid = str(step.get("id") or "").strip()
                title = str(step.get("title") or step.get("action") or "").strip()
                lines.append(f"• {sid + ': ' if sid else ''}{title or step}")
            else:
                lines.append(f"• {step}")
    if criteria:
        lines.append("Критерии готовности:")
        for item in criteria[:6]:
            lines.append(f"• {item}")

    lines.extend(
        [
            "",
            "Чтобы продолжить по делу, напишите в чат:",
            "• тему встречи;",
            "• участников;",
            "• желаемое окно времени / длительность;",
            "• нужно ли обязательное подтверждение человека перед созданием в Outlook.",
            "",
            "Интеграции из ваших ответов (1С / COM Outlook и т.п.) сохранены в плане "
            "и должны использоваться при сборке агента; в этом чате пока только сценарий "
            "по правилам, без живого COM.",
        ]
    )
    return "\n".join(lines)


def _answered_pairs(plan: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key in ("answered_questions", "open_questions"):
        raw = plan.get(key) or []
        if isinstance(raw, dict):
            for qid, value in raw.items():
                if isinstance(value, dict):
                    q = str(value.get("question") or qid).strip()
                    a = str(value.get("answer") or "").strip()
                else:
                    q = str(qid).strip()
                    a = str(value).strip()
                if a and a.casefold() not in seen:
                    pairs.append((q or qid, a))
                    seen.add(a.casefold())
            continue
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question") or item.get("id") or "").strip()
            a = str(item.get("answer") or "").strip()
            if a and a.casefold() not in seen:
                pairs.append((q or str(item.get("id") or "ответ"), a))
                seen.add(a.casefold())
    # Legacy phantom field
    answers = plan.get("answers")
    if isinstance(answers, dict):
        for key, value in answers.items():
            a = str(value).strip() if not isinstance(value, dict) else str(value.get("answer") or "").strip()
            q = str(key) if not isinstance(value, dict) else str(value.get("question") or key)
            if a and a.casefold() not in seen:
                pairs.append((q, a))
                seen.add(a.casefold())
    return pairs


def _site_browser_args(task: str, workflow: Workflow) -> dict[str, Any] | None:
    """Open site_browser only when task or plan explicitly contains a URL."""
    url = _extract_url(task) or _plan_site_url(workflow)
    if not url:
        return None
    return {
        "action": "open",
        "url": url,
        "wait_ms": 2000,
        "max_items": 25,
        "headless": True,
    }


def _compose_answer(task: str, tool_name: str, tool_result: dict[str, Any] | None) -> str:
    _ = task
    if not tool_result:
        return "Не удалось получить данные. Попробуйте ещё раз или уточните задачу."

    if tool_name == "site_browser":
        cards = tool_result.get("cards") or []
        lines = ["Нашла на сайте:"]
        if cards:
            for item in cards[:10]:
                title = str(item.get("title") or "Без названия").strip()
                url = str(item.get("url") or "").strip()
                snippet = str(item.get("text") or "").strip()
                line = f"• {title}"
                if url:
                    line += f"\n  {url}"
                elif snippet:
                    line += f"\n  {snippet[:160]}"
                lines.append(line)
            return "\n".join(lines)
        text = str(tool_result.get("text") or "").strip()
        if text:
            return "Открыла страницу, но список карточек пуст. Фрагмент:\n" + text[:1200]
        return (
            "Не удалось прочитать содержимое страницы. "
            "Проверьте URL в плане агента и доступ в интернет."
        )

    results = tool_result.get("results") or []
    if not results:
        return "Поиск в интернете не дал результатов. Уточните запрос или укажите URL в плане."
    lines = ["Нашла в интернете:"]
    for item in results[:5]:
        title = str(item.get("title") or "Без названия")
        url = str(item.get("url") or "")
        lines.append(f"• {title}\n  {url}".rstrip())
    return "\n".join(lines)
