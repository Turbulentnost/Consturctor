from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Protocol

from app.agent.prompts import build_action_message, build_runtime_system, build_user_message, with_integration_hint
from app.config import cursor_api_key, cursor_model
from app.models import Card
from app.tools.bridge import build_unified_custom_tool, set_confirm_callback

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], None]


class CancelCheck(Protocol):
    def __call__(self) -> bool: ...


class RuntimeAgentError(RuntimeError):
    pass


class AgentRunCancelled(RuntimeAgentError):
    pass


class CardAgentSession:
    """Cursor SDK local agent bound to one card."""

    def __init__(self, card: Card) -> None:
        self.card = card
        self._agent = None
        self._api_key = cursor_api_key()
        self._current_run: Any | None = None

    def _options(self):
        from cursor_sdk import AgentOptions, LocalAgentOptions

        workspace = self.card.workspace_dir or "."
        custom = {"constructor_integrations": build_unified_custom_tool()}
        return AgentOptions(
            api_key=self._api_key,
            model=cursor_model(),
            local=LocalAgentOptions(cwd=workspace, custom_tools=custom),
        )

    def open(self) -> None:
        if not self._api_key:
            raise RuntimeAgentError("CURSOR_API_KEY не задан в .env")
        from cursor_sdk import Agent

        opts = self._options()
        agent_id = (self.card.cursor_agent_id or "").strip()
        system = build_runtime_system(self.card)
        if agent_id:
            try:
                self._agent = Agent.resume(agent_id, opts)
                return
            except Exception as exc:
                logger.warning("Resume failed, creating new agent: %s", exc)

        self._agent = Agent.create(opts)
        run = self._agent.send(system)
        run.wait()

    def close(self) -> None:
        if self._agent is not None:
            try:
                self._agent.close()
            except Exception:
                pass
            self._agent = None

    @property
    def agent_id(self) -> str:
        if self._agent is None:
            return ""
        return str(getattr(self._agent, "agent_id", "") or "")

    def cancel_current_run(self) -> None:
        run = self._current_run
        if run is None:
            return
        try:
            run.cancel()
        except Exception:
            pass

    def send(
        self,
        message: str,
        on_event: EventCallback | None = None,
        *,
        attachment_paths: list[str] | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> str:
        if self._agent is None:
            raise RuntimeAgentError("Агент не открыт")
        payload = build_user_message(message, attachment_paths=attachment_paths)
        run = self._agent.send(with_integration_hint(payload))
        self._current_run = run
        final_text = ""
        try:
            for msg in run.messages():
                if cancel_check is not None and cancel_check():
                    self.cancel_current_run()
                    break
                _emit_sdk_message(msg, on_event)
                if getattr(msg, "type", "") == "assistant":
                    content = getattr(getattr(msg, "message", None), "content", None)
                    if content:
                        for block in content:
                            if getattr(block, "type", "") == "text":
                                final_text += getattr(block, "text", "")
            result = run.wait()
            if cancel_check is not None and cancel_check():
                raise AgentRunCancelled("Остановлено пользователем")
            if result.status == "cancelled":
                raise AgentRunCancelled("Остановлено пользователем")
            if result.status == "error":
                detail = (result.result or "").strip()
                raise RuntimeAgentError(
                    "Прогон завершился с ошибкой" + (f": {detail}" if detail else "")
                )
            return (result.result or final_text or "").strip()
        except AgentRunCancelled:
            raise
        except Exception as exc:
            if cancel_check is not None and cancel_check():
                raise AgentRunCancelled("Остановлено пользователем") from exc
            raise
        finally:
            self._current_run = None

    def send_action(
        self,
        prompt: str,
        on_event: EventCallback | None = None,
        *,
        attachment_paths: list[str] | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> str:
        return self.send(
            build_action_message(prompt, attachment_paths=attachment_paths),
            on_event,
            cancel_check=cancel_check,
        )


def _emit_sdk_message(msg: Any, on_event: EventCallback | None) -> None:
    if on_event is None:
        return
    kind = getattr(msg, "type", "")
    if kind == "assistant":
        text = _assistant_text(msg)
        if text:
            on_event({"type": "agent_message", "text": text})
    elif kind == "thinking":
        on_event({"type": "thinking", "text": getattr(msg, "text", "")})
    elif kind == "tool_call":
        on_event(
            {
                "type": "tool",
                "name": getattr(msg, "name", ""),
                "status": getattr(msg, "status", ""),
                "args": getattr(msg, "args", None),
                "result": getattr(msg, "result", None),
            }
        )
    elif kind == "status":
        text = str(getattr(msg, "message", "") or getattr(msg, "status", "") or "").strip()
        if not text or text.upper() in {"FINISHED", "DONE", "COMPLETED", "RUNNING"}:
            return
        on_event({"type": "status", "text": text})
    elif kind == "usage":
        usage = getattr(msg, "usage", None)
        if usage:
            on_event({"type": "usage", "tokens": getattr(usage, "total_tokens", 0)})


def _assistant_text(msg: Any) -> str:
    content = getattr(getattr(msg, "message", None), "content", None)
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", "") == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts)
