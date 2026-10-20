"""Контекст окна модели по шагам запуска — то, что TurboTester показывает на вкладке «Контекст».

Части окна: определения инструментов, промпт хода, размышления, ответы, аргументы и результаты
вызовов. После каждого шага — снимок: какие части сейчас в окне. Снимок хранится диапазоном
order[from:to] (плюс инструменты): новый агент начинает окно заново, продолжение (resume) дописывает.
Размеры — в символах; точные токены хода приходят от SDK событием usage.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

FLUSH_EVERY_SECONDS = 15.0
TEXT_CHARS = 1_500
ITEM_LIMIT = 1_000
SNAPSHOT_LIMIT = 2_000
_STREAMED = {"assistant": "ответ", "thinking": "размышление"}
_DONE_STATUSES = {"completed", "complete", "done", "finished", "ok", "success", "error", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


class RunContext:
    def __init__(self, on_flush: Callable[[dict[str, Any]], None]) -> None:
        self._on_flush = on_flush
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._items: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._snapshots: list[dict[str, Any]] = []
        self._usage: dict[int, dict[str, int]] = {}
        self._turn = 0
        self._start = 0
        self._steps = 0
        self._open: str | None = None
        self._spec_chars = 0
        self._spec_names: list[str] = []
        self._sdk_names: list[str] = []
        self._dirty = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="run-context", daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            self._close_step()
            return self._export()

    def begin_turn(self, prompt: str, tools: list[Any], *, resumed: bool) -> None:
        """Команда run раннеру: новый ход с этим промптом и этими определениями инструментов."""
        with self._lock:
            self._close_step()
            self._turn += 1
            if not resumed:
                self._start = len(self._order)
            specs = [item for item in tools if isinstance(item, dict)]
            self._spec_chars = len(_as_text(specs)) if specs else 0
            self._spec_names = [str(item.get("name") or "") for item in specs if item.get("name")]
            self._set_tools()
            self._add(f"{self._turn}:user", "user", "Промпт хода", prompt, len(prompt))
            self._snapshot("промпт", "user")

    def observe(self, payload: dict[str, Any]) -> None:
        kind = str(payload.get("type") or "")
        with self._lock:
            if not self._turn or payload.get("parentId"):
                return
            if kind in _STREAMED:
                self._stream(kind, str(payload.get("text") or ""))
            elif kind == "tool_call":
                self._tool_call(payload)
            elif kind == "tool_result":
                self._tool_result(payload)
            elif kind == "usage" and isinstance(payload.get("usage"), dict):
                self._set_usage(payload["usage"])
            elif kind == "status" and isinstance(payload.get("tools"), list):
                self._set_tools([str(name) for name in payload["tools"] if name])
            elif kind in {"final", "done", "error"}:
                self._close_step()

    def _stream(self, kind: str, text: str) -> None:
        if not text:
            return
        current = self._items.get(self._open or "")
        if current is None or current["type"] != kind:
            self._close_step()
            self._steps += 1
            item_id = f"{self._turn}:s{self._steps}"
            if not self._add(item_id, kind, _STREAMED[kind].capitalize(), "", 0):
                return
            self._open = item_id
            current = self._items[item_id]
        current["chars"] += len(text)
        if len(current["text"]) < TEXT_CHARS:
            current["text"] = (current["text"] + text)[:TEXT_CHARS]

    def _tool_call(self, payload: dict[str, Any]) -> None:
        self._close_step()
        tool = str(payload.get("tool") or "инструмент")
        request_id = str(payload.get("requestId") or "")
        if not request_id:
            self._steps += 1
            request_id = f"call{self._steps}"
        args_id = f"{self._turn}:{request_id}:args"
        if args_id not in self._items:
            args = _as_text(payload.get("arguments") or {})
            if self._add(args_id, "tool_call", f"{tool} · аргументы", args, len(args)):
                self._snapshot(f"вызов · {tool}", "tool_call")
        status = str(payload.get("status") or "").lower()
        if payload.get("result") is not None and status in _DONE_STATUSES:
            self._result(request_id, tool, payload.get("result"), failed=status in {"error", "failed"})

    def _tool_result(self, payload: dict[str, Any]) -> None:
        self._close_step()
        tool = str(payload.get("tool") or "инструмент")
        request_id = str(payload.get("requestId") or "")
        failed = payload.get("ok") is False
        body = payload.get("error") if failed and payload.get("error") else payload.get("result")
        self._result(request_id or f"result{self._steps}", tool, body, failed=failed)

    def _result(self, request_id: str, tool: str, body: Any, *, failed: bool) -> None:
        item_id = f"{self._turn}:{request_id}:result"
        if item_id in self._items:
            return
        text = _as_text(body)
        if self._add(item_id, "tool_result", f"{tool} · результат", text, len(text)):
            self._snapshot(f"{'ошибка' if failed else 'результат'} · {tool}", "tool_result")

    def _set_tools(self, sdk_names: list[str] | None = None) -> None:
        if sdk_names is not None:
            self._sdk_names = sdk_names
        names = list(dict.fromkeys([*self._spec_names, *self._sdk_names]))
        if not names and not self._spec_chars:
            return
        extra = sum(len(name) + 2 for name in names if name not in self._spec_names)
        self._items["tools"] = {
            "id": "tools",
            "turn": 0,
            "type": "tools",
            "label": f"Определения инструментов ({len(names)})",
            "chars": self._spec_chars + extra,
            "text": ", ".join(names)[:TEXT_CHARS],
        }
        self._dirty = True

    def _set_usage(self, usage: dict[str, Any]) -> None:
        clean = {
            str(key): int(value)
            for key, value in usage.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        self._usage[self._turn] = clean
        for snapshot in reversed(self._snapshots):
            if snapshot["turn"] != self._turn:
                break
            snapshot["usage"] = clean
        self._dirty = True

    def _add(self, item_id: str, kind: str, label: str, text: str, chars: int) -> bool:
        if len(self._order) >= ITEM_LIMIT:
            return False
        self._items[item_id] = {
            "id": item_id,
            "turn": self._turn,
            "type": kind,
            "label": label,
            "chars": chars,
            "text": text[:TEXT_CHARS],
        }
        self._order.append(item_id)
        self._dirty = True
        return True

    def _close_step(self) -> None:
        item_id = self._open
        self._open = None
        item = self._items.get(item_id or "")
        if item is not None and item["chars"]:
            self._snapshot(_STREAMED.get(item["type"], "шаг"), item["type"])

    def _snapshot(self, reason: str, kind: str) -> None:
        if len(self._snapshots) >= SNAPSHOT_LIMIT:
            return
        self._snapshots.append(
            {
                "seq": len(self._snapshots) + 1,
                "at": _now(),
                "turn": self._turn,
                "reason": reason,
                "kind": kind,
                "from": self._start,
                "to": len(self._order),
                "usage": self._usage.get(self._turn),
            }
        )
        self._dirty = True

    def _export(self) -> dict[str, Any]:
        self._dirty = False
        return {
            "items": {key: dict(item) for key, item in self._items.items()},
            "order": list(self._order),
            "snapshots": [dict(item) for item in self._snapshots],
        }

    def _loop(self) -> None:
        while not self._stop.wait(FLUSH_EVERY_SECONDS):
            with self._lock:
                if not self._dirty or not self._snapshots:
                    continue
                body = self._export()
            try:
                self._on_flush(body)
            except Exception:  # noqa: BLE001
                logger.warning("run context flush failed", exc_info=True)
