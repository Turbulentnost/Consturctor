"""Agent tool-calling loop."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4

from agent.llm_client import LLMClient, load_system_prompt
from agent.tool_registry import ToolContext, execute_tool, get_tool_schemas, is_read_only_tool
from agent.tools.browser_client import BrowserToolClient
from agent.tools.todo_write import TodoStore
from agent.types import AgentConfig, AgentRunResult, Message, ToolCall

logger = logging.getLogger(__name__)


def run_agent(
    goal: str,
    config: AgentConfig,
    llm: LLMClient,
    *,
    system_prompt: str | None = None,
) -> AgentRunResult:
    run_id = config.run_id or str(uuid4())
    browser = BrowserToolClient(config.browser_url) if config.browser_enabled else None
    ctx = ToolContext(
        config=config,
        todo_store=TodoStore(),
        run_id=run_id,
        browser=browser,
    )
    schemas = get_tool_schemas(browser_enabled=config.browser_enabled)
    messages: list[Message] = [
        Message(role="system", content=system_prompt or load_system_prompt()),
        Message(role="user", content=goal),
    ]

    steps = 0
    final_answer: str | None = None
    aborted = False
    abort_reason: str | None = None

    try:
        while steps < config.max_steps:
            steps += 1
            if config.debug:
                logger.debug("Step %s — sending %s messages to LLM (run_id=%s)", steps, len(messages), run_id)

            response = llm.complete(messages, schemas)
            if response.tool_calls:
                assistant = Message(role="assistant", content=response.content, tool_calls=response.tool_calls)
                messages.append(assistant)
                _execute_tool_batch(ctx, messages, response.tool_calls, config.debug)
                continue

            final_answer = response.content or ""
            messages.append(Message(role="assistant", content=final_answer))
            break
        else:
            aborted = True
            abort_reason = f"Reached max_steps={config.max_steps}"
            final_answer = final_answer or abort_reason
    finally:
        if browser is not None:
            try:
                browser.close_session(run_id)
            except Exception as exc:  # pragma: no cover
                logger.debug("browser.close_session failed: %s", exc)

    return AgentRunResult(
        final_answer=final_answer,
        steps=steps,
        messages=messages,
        aborted=aborted,
        abort_reason=abort_reason,
    )


def _execute_tool_batch(
    ctx: ToolContext,
    messages: list[Message],
    tool_calls: list[ToolCall],
    debug: bool,
) -> None:
    read_only = [c for c in tool_calls if is_read_only_tool(c.name)]
    mutating = [c for c in tool_calls if not is_read_only_tool(c.name)]

    results: list[tuple[ToolCall, str]] = []

    if read_only:
        with ThreadPoolExecutor(max_workers=min(8, len(read_only))) as pool:
            futures = {pool.submit(_run_single_tool, ctx, call, debug): call for call in read_only}
            for future in as_completed(futures):
                call = futures[future]
                results.append((call, future.result()))

    for call in mutating:
        results.append((call, _run_single_tool(ctx, call, debug)))

    order = {call.id: idx for idx, call in enumerate(tool_calls)}
    results.sort(key=lambda pair: order[pair[0].id])

    for call, payload in results:
        messages.append(
            Message(role="tool", content=payload, tool_call_id=call.id, name=call.name)
        )


def _run_single_tool(ctx: ToolContext, call: ToolCall, debug: bool) -> str:
    if debug:
        logger.debug("Tool %s args=%s", call.name, call.arguments)
    result = execute_tool(ctx, call.name, call.arguments)
    if debug:
        logger.debug("Tool %s ok=%s", call.name, result.ok)
    return json.dumps(result.to_dict(), ensure_ascii=False)
