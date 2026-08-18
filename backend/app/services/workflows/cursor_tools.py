"""Cursor Cloud Agent and desktop tools during workflow creation."""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from typing import Any, Callable

from app.clients import cursor as cursor_client
from app.services.local_mcp import list_tools
from app.services.tool_bridge import DEFAULT_TIMEOUT_S, tool_bridge

logger = logging.getLogger(__name__)

WorkflowEmit = Callable[..., None]

_tool_ctx: ContextVar[tuple[str, str] | None] = ContextVar("creation_tool_ctx", default=None)

_TOOL_BLOCK_RE = re.compile(
    r"```(?:constructor_tool|tool)\s*\n(\{.*?\})\s*```",
    re.DOTALL,
)
_MAX_ROUNDS = 6
_MAX_CALLS_PER_ROUND = 3


def set_tool_context(run_id: str, user_id: str) -> None:
    _tool_ctx.set((run_id, user_id))


def clear_tool_context() -> None:
    _tool_ctx.set(None)


def current_tool_context() -> tuple[str, str] | None:
    return _tool_ctx.get()


def tools_prompt_block() -> str:
    lines = [
        "Доступные инструменты Constructor — реальные вызовы на компьютере пользователя.",
        "Чтобы вызвать инструмент, верни ТОЛЬКО один блок (без плана вокруг):",
        "```constructor_tool",
        '{"name": "outlook.search_mail", "arguments": {"query": "совещание"}}',
        "```",
        "Не выдумывай результат. Дождись ответа системы и только потом продолжи.",
        "Когда данных достаточно — верни финальный ответ (JSON плана или RESULT) "
        "без блока constructor_tool.",
        "Каталог:",
    ]
    for item in list_tools():
        name = str(item.get("name") or "")
        if not name:
            continue
        desc = str(item.get("description") or "").replace("\n", " ")
        schema = item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {}
        props = list((schema.get("properties") or {}).keys())
        required = list(schema.get("required") or [])
        exec_at = str(item.get("execution") or "desktop")
        extra = f" args={props}" if props else ""
        if required:
            extra += f" required={required}"
        lines.append(f"- {name} [{exec_at}]: {desc}{extra}")
    return "\n".join(lines)


def with_tools_if_desktop(prompt: str) -> str:
    if current_tool_context() is None:
        return prompt
    return prompt.rstrip() + "\n\n" + tools_prompt_block() + "\n"


def extract_tool_calls(text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for match in _TOOL_BLOCK_RE.finditer(text or ""):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or data.get("tool") or "").strip()
        if not name:
            continue
        arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        calls.append({"name": name, "arguments": arguments})
    return calls


def should_run_tool_calls(text: str, *, mode: str) -> list[dict[str, Any]]:
    calls = extract_tool_calls(text)
    if not calls:
        return []
    if mode == "plan":
        from app.services.workflows.prompts import parse_plan_from_text

        plan = parse_plan_from_text(text)
        if plan.title.strip() and plan.steps:
            return []
        return calls
    if "TESTS: PASS" in (text or "") or "TESTS: FAIL" in (text or ""):
        return []
    return calls


def invoke_creation_tool(
    *,
    tool: str,
    arguments: dict[str, Any],
    on_event: WorkflowEmit | None,
    workflow_id: str = "",
) -> dict[str, Any]:
    from app.services.agent_runtime import (
        _IMAP_TOOLS,
        _ONEC_TOOLS,
        _invoke_imap_server,
        _invoke_onec_server,
    )

    args = dict(arguments or {})
    if workflow_id:
        args.setdefault("workflow_id", workflow_id)
        args.setdefault("agent_id", workflow_id)
    logger.info("Creation tool invoke start tool=%s workflow_id=%s", tool, workflow_id or "-")
    if tool.startswith("imap.") or tool in _IMAP_TOOLS:
        return _invoke_imap_server(tool, args)
    if tool in _ONEC_TOOLS:
        return _invoke_onec_server(tool, args)

    ctx = current_tool_context()
    if ctx is None:
        raise RuntimeError("Нет desktop-сессии для вызова инструмента")
    run_id, user_id = ctx
    request_id = tool_bridge.new_request_id()
    tool_bridge.begin_wait(request_id=request_id, user_id=user_id)
    _emit(
        on_event,
        "tool_request",
        f"Выполняю на компьютере: {tool}…",
        {
            "run_id": run_id,
            "request_id": request_id,
            "tool": tool,
            "arguments": args,
        },
    )
    payload = tool_bridge.await_result(request_id=request_id, timeout_s=DEFAULT_TIMEOUT_S)
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or f"Ошибка инструмента {tool}"))
    result = payload.get("result")
    logger.info("Creation tool invoke ok tool=%s workflow_id=%s", tool, workflow_id or "-")
    return result if isinstance(result, dict) else {}


def stream_cursor_with_tools(
    *,
    agent_id: str,
    run_id: str,
    on_event: WorkflowEmit | None,
    workflow_id: str = "",
    mode: str = "plan",
    stream_run,
) -> Any:
    """Stream a Cursor run; if it asks for constructor_tool, execute and continue."""
    last = stream_run(agent_id, run_id, on_event=on_event)
    if current_tool_context() is None:
        return last
    for round_n in range(_MAX_ROUNDS):
        calls = should_run_tool_calls(last.text or "", mode=mode)
        if not calls:
            return last
        logger.info(
            "Cursor tool round=%s mode=%s calls=%s",
            round_n + 1,
            mode,
            [str(call.get("name") or "") for call in calls[:_MAX_CALLS_PER_ROUND]],
        )
        results: list[dict[str, Any]] = []
        for call in calls[:_MAX_CALLS_PER_ROUND]:
            name = str(call.get("name") or "")
            _emit(on_event, "decision", f"Cursor вызывает «{name}»…")
            try:
                result = invoke_creation_tool(
                    tool=name,
                    arguments=call.get("arguments") or {},
                    on_event=on_event,
                    workflow_id=workflow_id,
                )
                results.append({"name": name, "ok": True, "result": _clip_result(result)})
                _emit(on_event, "decision", f"«{name}»: готово.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Creation tool %s failed: %s", name, exc)
                results.append({"name": name, "ok": False, "error": str(exc)})
                _emit(on_event, "decision", f"«{name}»: {exc}")
        follow = _followup_prompt(results, mode=mode)
        run = cursor_client.create_run(agent_id, prompt=follow, mode="agent")
        run_id = str(run.get("id") or "")
        if not run_id:
            return last
        last = stream_run(agent_id, run_id, on_event=on_event)
        _ = round_n
    return last


def _followup_prompt(results: list[dict[str, Any]], *, mode: str) -> str:
    blob = json.dumps(results, ensure_ascii=False, indent=2, default=str)
    if mode == "plan":
        tail = (
            "Учти результаты инструментов. "
            "Если нужно ещё проверить — снова верни только ```constructor_tool. "
            "Иначе верни финальный JSON плана по схеме, без блока constructor_tool."
        )
    else:
        tail = (
            "Учти результаты инструментов и продолжи реализацию. "
            "Если нужно ещё вызвать инструмент — только ```constructor_tool. "
            "Иначе заверши работу (artifacts / RESULT.md / TESTS: PASS|FAIL)."
        )
    return (
        "Результаты вызовов инструментов Constructor (это факты с компьютера пользователя):\n"
        f"{blob}\n\n{tail}"
    )


def _clip_result(result: dict[str, Any], limit: int = 8000) -> dict[str, Any]:
    try:
        raw = json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return {"text": str(result)[:limit]}
    if len(raw) <= limit:
        return result
    return {"truncated": True, "preview": raw[:limit] + "…"}


def _emit(
    on_event: WorkflowEmit | None,
    event_type: str,
    text: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    preview = (text or "").replace("\n", " ").strip()
    if len(preview) > 240:
        preview = preview[:240] + "…"
    if extra:
        logger.info("Cursor event type=%s text=%s extra_keys=%s", event_type, preview, sorted(extra.keys()))
    elif preview:
        logger.info("Cursor event type=%s text=%s", event_type, preview)
    else:
        logger.info("Cursor event type=%s", event_type)
    if on_event is None:
        return
    if extra:
        try:
            on_event(event_type, text, extra)
            return
        except TypeError:
            pass
    if text:
        on_event(event_type, text)
