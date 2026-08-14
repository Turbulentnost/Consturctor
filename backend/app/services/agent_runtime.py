from __future__ import annotations

import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.services.local_mcp import list_tools
from app.services.plan_run import (
    PlanRunError,
    build_plan_export_arguments,
    format_plan_run_answer,
    uses_plan_export,
)
from app.services.tool_bridge import DEFAULT_TIMEOUT_S, tool_bridge


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

    # Rules come from THIS agent's plan (runtime / constraints / answers), not globals.
    if uses_plan_export(workflow):
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


def _request_desktop_tool(
    emit: AgentEventCallback,
    *,
    run_id: str,
    user_id: str,
    tool: str,
    arguments: dict[str, Any],
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    if tool.startswith("imap.") or tool in _IMAP_TOOLS:
        return _invoke_imap_server(tool, arguments)
    if tool.startswith("onec.") or tool in _ONEC_TOOLS:
        return _invoke_onec_server(tool, arguments)

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
