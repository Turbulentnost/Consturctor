from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import DESKTOP_ROOT
from app.sdk_agent.tool_adapter import invoke_sdk_tool, sdk_tool_specs
from app.tools import ToolHostError

DEFAULT_SDK_MODEL = "grok-4.6"


class CursorSdkError(RuntimeError):
    pass


class CursorSdkUnavailable(CursorSdkError):
    pass


SdkEventCallback = Callable[[dict[str, Any]], None]


class CursorSdkBridge:
    def __init__(self, *, node: str = "node", runner: Path | None = None) -> None:
        self._node = node
        self._sdk_root = DESKTOP_ROOT / "sdk-agent"
        self._runner = runner or self._sdk_root / "src" / "runner.ts"

    def run(
        self,
        *,
        prompt: str,
        workflow_id: str,
        model: str = "",
        cwd: str = "",
        mode: str = "run",
        tools: list[dict[str, Any]] | None = None,
        on_event: SdkEventCallback | None = None,
    ) -> dict[str, Any]:
        self._ensure_ready()
        run_id = str(uuid.uuid4())
        cmd = self._command()
        process = subprocess.Popen(
            cmd,
            cwd=str(self._sdk_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._env(),
        )
        stderr_lines: list[str] = []
        stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process, stderr_lines),
            daemon=True,
        )
        stderr_thread.start()
        try:
            final: dict[str, Any] | None = None
            self._send(
                process,
                {
                    "type": "run",
                    "id": run_id,
                    "prompt": prompt,
                    "model": model or os.getenv("CURSOR_SDK_MODEL", DEFAULT_SDK_MODEL),
                    "cwd": cwd or self._workspace_cwd(),
                    "mode": "design" if mode == "design" else "run",
                    "tools": sdk_tool_specs() if tools is None else tools,
                    "workflowId": workflow_id,
                },
            )
            assert process.stdout is not None
            for line in process.stdout:
                payload = self._parse_line(line)
                if not payload:
                    continue
                event_type = str(payload.get("type") or "")
                if event_type == "ready":
                    continue
                if event_type == "tool_request":
                    self._handle_tool_request(process, payload, workflow_id=workflow_id)
                    continue
                if event_type == "done":
                    final = payload
                    if on_event is not None:
                        on_event(payload)
                    break
                if on_event is not None:
                    on_event(payload)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
            if final is None:
                err = "\n".join(stderr_lines[-20:]).strip()
                raise CursorSdkError(err or "Cursor SDK runner завершился без результата")
            status = str(final.get("status") or "")
            answer = str(final.get("answer") or "")
            if status == "error":
                raise CursorSdkError(answer or "Cursor SDK run failed")
            return {"answer": answer, "status": status or "ok", "run_id": run_id}
        finally:
            if process.poll() is None:
                process.kill()

    def _ensure_ready(self) -> None:
        if not os.getenv("CURSOR_API_KEY", "").strip():
            raise CursorSdkUnavailable("CURSOR_API_KEY не задан в desktop/.env")
        if not self._runner.is_file():
            raise CursorSdkUnavailable(f"Cursor SDK runner не найден: {self._runner}")
        node_modules = self._sdk_root / "node_modules"
        if not node_modules.is_dir():
            raise CursorSdkUnavailable(
                "Зависимости Cursor SDK не установлены. Выполните npm install в desktop/sdk-agent."
            )
        try:
            result = subprocess.run(
                [self._node, "--version"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise CursorSdkUnavailable(f"Node.js не найден: {exc}") from exc
        if result.returncode != 0:
            raise CursorSdkUnavailable("Node.js не запускается")
        version = (result.stdout or "").strip().lstrip("v")
        major, minor = self._node_version(version)
        if major < 22 or (major == 22 and minor < 13):
            raise CursorSdkUnavailable("Для Cursor SDK нужен Node.js 22.13 или новее")

    def check_ready(self) -> None:
        self._ensure_ready()

    def _workspace_cwd(self) -> str:
        path = self._sdk_root / "workspace"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _command(self) -> list[str]:
        tsx = self._sdk_root / "node_modules" / ".bin" / (
            "tsx.cmd" if sys.platform == "win32" else "tsx"
        )
        if tsx.is_file():
            return [str(tsx), str(self._runner)]
        return ["tsx", str(self._runner)]

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.setdefault("NODE_NO_WARNINGS", "1")
        return env

    def _send(self, process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
        if process.stdin is None:
            raise CursorSdkError("Cursor SDK runner stdin закрыт")
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def _handle_tool_request(
        self,
        process: subprocess.Popen[str],
        payload: dict[str, Any],
        *,
        workflow_id: str,
    ) -> None:
        request_id = str(payload.get("requestId") or "")
        tool = str(payload.get("tool") or "")
        args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        args = dict(args)
        if workflow_id:
            args.setdefault("workflow_id", workflow_id)
            args.setdefault("agent_id", workflow_id)
            args.setdefault("runtime_context", {"workflow_id": workflow_id, "agent_id": workflow_id})
        try:
            result = invoke_sdk_tool(tool, args)
            self._send(
                process,
                {
                    "type": "tool_result",
                    "requestId": request_id,
                    "ok": True,
                    "result": result,
                },
            )
        except ToolHostError as exc:
            self._send(
                process,
                {
                    "type": "tool_result",
                    "requestId": request_id,
                    "ok": False,
                    "error": str(exc),
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._send(
                process,
                {
                    "type": "tool_result",
                    "requestId": request_id,
                    "ok": False,
                    "error": f"Ошибка инструмента {tool}: {exc}",
                },
            )

    @staticmethod
    def _parse_line(line: str) -> dict[str, Any]:
        text = (line or "").strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"type": "status", "text": text}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _drain_stderr(process: subprocess.Popen[str], lines: list[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            lines.append(line.rstrip())

    @staticmethod
    def _node_version(value: str) -> tuple[int, int]:
        parts = value.split(".")
        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
        except (TypeError, ValueError):
            return 0, 0
        return major, minor
