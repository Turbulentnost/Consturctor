from __future__ import annotations

import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.services.local_mcp import list_tools
from app.services.tool_bridge import DEFAULT_TIMEOUT_S, tool_bridge
from app.services.workflow_tool_routing import resolve_workflow_routing
from app.services.workflows.plan_models import WorkflowPlan


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

_ONEC_TOOLS = frozenset(
    {
        "onec.odata_get",
        "onec.odata_post",
        "onec.odata_patch",
        "onec.attach_file",
        "onec.sql_query",
    }
)


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

    plan_data = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    plan = WorkflowPlan.from_dict(plan_data)
    domain = _agent_domain(workflow)

    if domain == "hybrid":
        return _run_hybrid_task(
            plan=plan,
            workflow=workflow,
            task=task,
            emit=emit,
            run_id=run_id,
            user_id=user_id,
            workflow_id=workflow_id,
        )

    if domain == "outlook_calendar":
        live_allowed, live_reason = _desktop_com_available(workflow, domain)
        if not live_allowed:
            emit(
                {
                    "type": "status",
                    "text": f"Live COM недоступен ({live_reason}) — использую fixtures/stub.",
                }
            )
            answer = _fallback_live_answer("outlook_calendar", live_reason)
            emit({"type": "agent_message", "text": answer})
            return {
                "answer": answer,
                "tool": "fixtures",
                "tool_result": {"fallback": True, "reason": live_reason},
            }
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
        live_allowed, live_reason = _desktop_com_available(workflow, domain)
        if not live_allowed:
            emit(
                {
                    "type": "status",
                    "text": f"Live COM недоступен ({live_reason}) — использую fixtures/stub.",
                }
            )
            answer = _fallback_live_answer("onec", live_reason)
            emit({"type": "agent_message", "text": answer})
            return {
                "answer": answer,
                "tool": "fixtures",
                "tool_result": {"fallback": True, "reason": live_reason},
            }
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


def _run_hybrid_task(
    *,
    plan: WorkflowPlan,
    workflow: Workflow,
    task: str,
    emit: AgentEventCallback,
    run_id: str,
    user_id: str,
    workflow_id: str,
) -> dict[str, Any]:
    phases = list(getattr(plan.runtime, "phases", []) or [])
    if not phases:
        raise AgentRuntimeError("Hybrid plan не содержит phases")

    phase_summaries: list[str] = []
    phase_outputs: list[dict[str, Any]] = []
    context = ""
    total = len(phases)

    for idx, phase in enumerate(phases, start=1):
        phase_kind = str(getattr(phase, "kind", "") or "").strip().casefold()
        phase_handoff = str(getattr(phase, "handoff", "") or "").strip()
        phase_tools = [str(x) for x in (getattr(phase, "tools", []) or []) if str(x).strip()]
        phase_label = phase_kind or f"phase_{idx}"
        emit(
            {
                "type": "status",
                "text": f"Фаза {idx}/{total}: {phase_label}…",
            }
        )

        if phase_kind == "onec":
            live_allowed, live_reason = _desktop_com_available(workflow, phase_kind)
            if not live_allowed:
                result = {
                    "tool": "fixtures",
                    "result": {"fallback": True, "reason": live_reason},
                }
                summary = _fallback_live_answer("onec", live_reason)
                phase_outputs.append({"kind": phase_kind, "result": result, "summary": summary})
                phase_summaries.append(summary)
                context = summary
                continue
            result = _run_hybrid_onec_phase(
                task=task,
                context=context,
                phase_tools=phase_tools,
                phase_handoff=phase_handoff,
                workflow=workflow,
                emit=emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
            )
            summary = _compose_hybrid_onec_summary(result)
        elif phase_kind == "outlook_calendar":
            live_allowed, live_reason = _desktop_com_available(workflow, phase_kind)
            if not live_allowed:
                result = {
                    "tool": "fixtures",
                    "result": {"fallback": True, "reason": live_reason},
                }
                summary = _fallback_live_answer("outlook_calendar", live_reason)
                phase_outputs.append({"kind": phase_kind, "result": result, "summary": summary})
                phase_summaries.append(summary)
                context = summary
                continue
            result = _run_hybrid_outlook_phase(
                task=task,
                context=context,
                phase_tools=phase_tools,
                phase_handoff=phase_handoff,
                workflow=workflow,
                emit=emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
            )
            summary = _compose_hybrid_outlook_summary(result)
        elif phase_kind in {"browser_task", "site_search_excel", "web_search"}:
            result = _run_hybrid_browser_phase(
                task=task,
                context=context,
                phase_tools=phase_tools,
                phase_handoff=phase_handoff,
                workflow=workflow,
                emit=emit,
                run_id=run_id,
                user_id=user_id,
                workflow_id=workflow_id,
            )
            summary = _compose_hybrid_browser_summary(task, result)
        else:
            raise AgentRuntimeError(f"Неизвестная фаза hybrid: {phase_kind or 'empty'}")

        phase_outputs.append({"kind": phase_kind, "result": result, "summary": summary})
        phase_summaries.append(summary)
        context = summary

    answer = "\n\n".join(s for s in phase_summaries if s.strip()) or "Hybrid flow completed."
    emit({"type": "agent_message", "text": answer})
    return {
        "answer": answer,
        "tool": "hybrid",
        "tool_result": {"phases": phase_outputs},
    }


def _run_hybrid_onec_phase(
    *,
    task: str,
    context: str,
    phase_tools: list[str],
    phase_handoff: str,
    workflow: Workflow,
    emit: AgentEventCallback,
    run_id: str,
    user_id: str,
    workflow_id: str,
) -> dict[str, Any]:
    _ = workflow
    query_parts = [task]
    if phase_handoff:
        query_parts.append(phase_handoff)
    if context:
        query_parts.append(context)
    query = "\n".join(p for p in query_parts if p).strip()
    emit({"type": "thinking", "text": "Ищу данные в 1С и читаю карточку документа…"})

    search_result = _request_desktop_tool(
        emit,
        run_id=run_id,
        user_id=user_id,
        workflow_id=workflow_id,
        tool="onec.search_documents",
        arguments={"query": query, "max_results": 10},
    )
    emit({"type": "tool_result", "tool": "onec.search_documents", "result": search_result})

    card_result: dict[str, Any] = {}
    if "onec.get_document_card" in {t.casefold() for t in phase_tools}:
        documents = search_result.get("documents") or []
        if documents and isinstance(documents[0], dict):
            doc_ref = str(documents[0].get("ref") or "").strip()
            if doc_ref:
                card_result = _request_desktop_tool(
                    emit,
                    run_id=run_id,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    tool="onec.get_document_card",
                    arguments={"document_ref": doc_ref},
                )
                emit({"type": "tool_result", "tool": "onec.get_document_card", "result": card_result})

    return {"search": search_result, "card": card_result}


def _run_hybrid_outlook_phase(
    *,
    task: str,
    context: str,
    phase_tools: list[str],
    phase_handoff: str,
    workflow: Workflow,
    emit: AgentEventCallback,
    run_id: str,
    user_id: str,
    workflow_id: str,
) -> dict[str, Any]:
    phase_task = task
    parts = [context, phase_handoff]
    if any(part.strip() for part in parts):
        phase_task = "\n\n".join([task] + [part for part in parts if part.strip()])

    outlook_tool, outlook_args = _outlook_tool_request(phase_task)
    if "outlook.search_mail" in {t.casefold() for t in phase_tools}:
        outlook_tool = "outlook.search_mail"
    elif "outlook.read_calendar" in {t.casefold() for t in phase_tools}:
        outlook_tool = "outlook.read_calendar"

    emit({"type": "thinking", "text": "Проверяю Outlook по данным из 1С…"})
    tool_result = _request_desktop_tool(
        emit,
        run_id=run_id,
        user_id=user_id,
        workflow_id=workflow_id,
        tool=outlook_tool,
        arguments=outlook_args,
    )
    emit({"type": "tool_result", "tool": outlook_tool, "result": tool_result})
    _ = workflow
    return {"tool": outlook_tool, "result": tool_result}


def _run_hybrid_browser_phase(
    *,
    task: str,
    context: str,
    phase_tools: list[str],
    phase_handoff: str,
    workflow: Workflow,
    emit: AgentEventCallback,
    run_id: str,
    user_id: str,
    workflow_id: str,
) -> dict[str, Any]:
    phase_task = task
    parts = [context, phase_handoff]
    if any(part.strip() for part in parts):
        phase_task = "\n\n".join([task] + [part for part in parts if part.strip()])

    browser_args = _site_browser_args(phase_task, workflow)
    tool_name = "site_browser" if browser_args else "web_search"
    if "site_browser" in {t.casefold() for t in phase_tools} and browser_args:
        tool_name = "site_browser"
    elif "web_search" in {t.casefold() for t in phase_tools}:
        tool_name = "web_search"

    arguments = browser_args or {"query": _search_query(phase_task, workflow), "max_results": 8, "fetch_top": False}
    emit({"type": "thinking", "text": "Обрабатываю browser/web-search фазу…"})
    tool_result = _request_desktop_tool(
        emit,
        run_id=run_id,
        user_id=user_id,
        workflow_id=workflow_id,
        tool=tool_name,
        arguments=arguments,
    )
    emit({"type": "tool_result", "tool": tool_name, "result": tool_result})
    _ = phase_handoff
    return {"tool": tool_name, "result": tool_result}


def _compose_hybrid_onec_summary(result: dict[str, Any]) -> str:
    lines: list[str] = ["1C: данные получены."]
    search = result.get("search") if isinstance(result.get("search"), dict) else {}
    docs = search.get("documents") or []
    if docs:
        first = docs[0] if isinstance(docs[0], dict) else {}
        title = str(first.get("title") or first.get("number") or "документ").strip()
        status = str(first.get("status") or "").strip()
        lines.append(f"Найден документ: {title}" + (f" ({status})" if status else ""))
    card = result.get("card") if isinstance(result.get("card"), dict) else {}
    doc = card.get("document") if isinstance(card.get("document"), dict) else {}
    if doc:
        preview = str(doc.get("content_preview") or "").strip()
        responsible = str(doc.get("responsible") or "").strip()
        author = str(doc.get("author") or "").strip()
        if responsible or author:
            bits = []
            if author:
                bits.append(f"автор: {author}")
            if responsible:
                bits.append(f"ответственный: {responsible}")
            lines.append(", ".join(bits))
        if preview:
            lines.append(f"Суть: {preview}")
    return "\n".join(lines)


def _compose_hybrid_browser_summary(task: str, result: dict[str, Any]) -> str:
    tool_name = str(result.get("tool") or "")
    tool_result = result.get("result") if isinstance(result.get("result"), dict) else {}
    return _compose_answer(task, tool_name, tool_result)


def _compose_hybrid_outlook_summary(result: dict[str, Any]) -> str:
    tool_name = str(result.get("tool") or "")
    tool_result = result.get("result") if isinstance(result.get("result"), dict) else {}
    if not tool_result:
        return "Outlook: данных не получил."
    if tool_name == "outlook.search_mail":
        return _compose_outlook_tool_answer("контекст из 1С", tool_name, tool_result)
    return _compose_outlook_tool_answer("контекст из 1С", tool_name, tool_result)


def _agent_domain(workflow: Workflow) -> str:
    plan_data = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    plan = WorkflowPlan.from_dict(plan_data)
    if getattr(plan.runtime, "phases", []):
        return "hybrid"
    return resolve_workflow_routing(plan, workflow).kind


def _desktop_com_available(workflow: Workflow, domain: str) -> tuple[bool, str]:
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    desktop = local.get("desktop") if isinstance(local.get("desktop"), dict) else {}
    if desktop:
        if domain == "outlook_calendar":
            if bool(desktop.get("outlook_com_available")):
                return True, "Outlook COM доступен"
            reason = str(desktop.get("outlook_com_reason") or "").strip()
            return False, reason or "Outlook COM недоступен"
        if domain == "onec":
            if bool(desktop.get("onec_com_available")):
                return True, "1C COM доступен"
            reason = str(desktop.get("onec_com_reason") or "").strip()
            return False, reason or "1C COMConnector недоступен"
        if bool(desktop.get("com_available")):
            return True, "COM доступен"
        reason = str(desktop.get("com_reason") or "").strip()
        return False, reason or "COM недоступен"
    return False, "нет сведений о desktop COM"


def _fallback_live_answer(domain: str, reason: str) -> str:
    label = "Outlook" if domain == "outlook_calendar" else "1C"
    return f"Live {label} недоступен на этой машине ({reason}). Перехожу в fixtures/stub."


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


def _invoke_imap_server(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.services.imap_tools import ImapToolError, invoke_imap

    try:
        return invoke_imap(tool, arguments)
    except ImapToolError as exc:
        raise AgentRuntimeError(str(exc)) from exc


def _invoke_onec_server(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError, invoke_onec

    try:
        return invoke_onec(tool, arguments)
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
