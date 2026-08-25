from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import DESKTOP_ROOT
from app.sdk_agent.tool_adapter import (
    invoke_sdk_tool,
    is_ask_question,
    sdk_tool_specs,
)
from app.tools import ToolHostError

DEFAULT_SDK_MODEL = "grok-4.6"
LARGE_TOOL_RESULT_BYTES = 8_000
EXTERNALIZED_SAMPLE_ITEMS = 8
EXTERNALIZED_NEXT_STEP = (
    "Full JSON is in result_file relative to cwd. "
    "Extract the fields you need with Cursor Read or by writing and running Python. "
    "Do not call the same Constructor tool again for this data."
)


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
        self._skip_lock = threading.Lock()
        self._stdin_lock = threading.Lock()
        self._skip_ids: set[str] = set()
        self._active_request_ids: set[str] = set()
        self._active_tool_names: dict[str, str] = {}
        self._process: subprocess.Popen[str] | None = None

    def skip_tool(self, request_id: str = "") -> bool:
        rid = (request_id or "").strip()
        with self._skip_lock:
            targets = set(self._active_request_ids)
            if rid:
                targets.add(rid)
            if not targets:
                return bool(rid)
            self._skip_ids.update(targets)
            names = dict(self._active_tool_names)
        self._stop_skipped_tool()
        self._flush_skipped_results(targets, names)
        return True

    def _flush_skipped_results(
        self,
        request_ids: set[str],
        names: dict[str, str] | None = None,
    ) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            return
        tool_names = names or {}
        for request_id in request_ids:
            rid = (request_id or "").strip()
            if not rid:
                continue
            try:
                self._send(
                    process,
                    {
                        "type": "tool_result",
                        "requestId": rid,
                        "ok": True,
                        "result": self.skipped_tool_result(tool_names.get(rid, "tool")),
                    },
                )
            except CursorSdkError:
                return

    @staticmethod
    def _stop_skipped_tool() -> None:
        try:
            from app.tools.ac.workers.subprocess_com_worker import SubprocessComWorker

            SubprocessComWorker.cancel_all()
        except Exception:
            return

    def _is_skipped(self, request_id: str) -> bool:
        with self._skip_lock:
            return request_id in self._skip_ids

    def _mark_active(self, request_id: str, tool: str = "") -> None:
        rid = (request_id or "").strip()
        if not rid:
            return
        with self._skip_lock:
            self._active_request_ids.add(rid)
            if tool.strip():
                self._active_tool_names[rid] = tool.strip()

    def _clear_active(self, request_id: str) -> None:
        rid = (request_id or "").strip()
        if not rid:
            return
        with self._skip_lock:
            self._active_request_ids.discard(rid)
            self._skip_ids.discard(rid)
            self._active_tool_names.pop(rid, None)

    @staticmethod
    def _confirm_write_tool(tool: str, args: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
        """Ask the user before a write tool runs. Returns (allowed, rejected_result).

        Reuses the existing HITL card infra. If there is no Qt UI (headless
        scheduled run) or HITL is unavailable, the call proceeds autonomously.
        """
        try:
            from app.tools.hitl import confirm_level1_tool, needs_confirmation
        except Exception:
            return True, None
        if not needs_confirmation(tool):
            return True, None
        try:
            from PySide6.QtWidgets import QApplication

            if QApplication.instance() is None:
                return True, None
        except Exception:
            return True, None
        try:
            approved = confirm_level1_tool(tool, args)
        except Exception:
            return True, None
        if approved:
            return True, None
        return False, {
            "rejected": True,
            "tool": tool,
            "summary": (
                "User rejected this tool. Do not retry it. "
                "Continue with the task or finish without this action."
            ),
        }

    @staticmethod
    def skipped_tool_result(tool: str) -> dict[str, Any]:
        name = (tool or "").strip() or "tool"
        return {
            "skipped": True,
            "tool": name,
            "summary": (
                "User skipped this tool. Continue the task without waiting for its result."
            ),
        }

    def run(
        self,
        *,
        prompt: str,
        workflow_id: str,
        model: str = "",
        cwd: str = "",
        mode: str = "run",
        tools: list[dict[str, Any]] | None = None,
        resume_agent_id: str = "",
        on_event: SdkEventCallback | None = None,
        on_question: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        should_stop: Callable[[], bool] | None = None,
        confirm_writes: bool = False,
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
        run_cwd = cwd or self._workspace_cwd(workflow_id)
        agent_id = resume_agent_id.strip()
        stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process, stderr_lines),
            daemon=True,
        )
        stderr_thread.start()
        self._process = process
        try:
            final: dict[str, Any] | None = None
            self._send(
                process,
                {
                    "type": "run",
                    "id": run_id,
                    "prompt": prompt,
                    "model": model or os.getenv("CURSOR_SDK_MODEL", DEFAULT_SDK_MODEL),
                    "cwd": run_cwd,
                    "mode": "design" if mode == "design" else "run",
                    "tools": sdk_tool_specs() if tools is None else tools,
                    "resumeAgentId": agent_id or None,
                    "workflowId": workflow_id,
                },
            )
            assert process.stdout is not None
            answer_parts: list[str] = []
            for line in process.stdout:
                payload = self._parse_line(line)
                if not payload:
                    continue
                event_type = str(payload.get("type") or "")
                if event_type == "ready":
                    continue
                if event_type == "tool_request":
                    self._handle_tool_request(
                        process,
                        payload,
                        workflow_id=workflow_id,
                        cwd=run_cwd,
                        on_question=on_question,
                        should_stop=should_stop,
                        confirm_writes=confirm_writes,
                    )
                    continue
                if event_type == "agent":
                    agent_id = str(payload.get("agentId") or agent_id).strip()
                if event_type in {"assistant", "final"}:
                    text = str(payload.get("text") or payload.get("answer") or "").strip()
                    if text:
                        answer_parts.append(text)
                if event_type == "done":
                    final = payload
                    if on_event is not None:
                        on_event(payload)
                    break
                if on_event is not None:
                    on_event(payload)
                if should_stop is not None and should_stop():
                    try:
                        self._send(process, {"type": "cancel", "id": run_id})
                    except CursorSdkError:
                        pass
                    process.kill()
                    collected = "\n\n".join(answer_parts).strip()
                    return {
                        "answer": collected,
                        "status": "ok",
                        "run_id": run_id,
                        "agent_id": agent_id,
                    }
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
            if final is None:
                collected = "\n\n".join(answer_parts).strip()
                if collected:
                    return {
                        "answer": collected,
                        "status": "ok",
                        "run_id": run_id,
                        "agent_id": agent_id,
                    }
                err = "\n".join(stderr_lines[-20:]).strip()
                raise CursorSdkError(err or "Cursor SDK runner завершился без результата")
            status = str(final.get("status") or "")
            answer = str(final.get("answer") or "") or "\n\n".join(answer_parts).strip()
            if status == "error":
                raise CursorSdkError(answer or "Cursor SDK run failed")
            return {
                "answer": answer,
                "status": status or "ok",
                "run_id": run_id,
                "agent_id": agent_id,
            }
        finally:
            self._process = None
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

    def _workspace_cwd(self, workflow_id: str = "") -> str:
        root = self._workspaces_root()
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", (workflow_id or "default").strip()) or "default"
        path = root / safe_id
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def workspace_cwd(self, workflow_id: str = "") -> str:
        return self._workspace_cwd(workflow_id)

    @staticmethod
    def _workspaces_root() -> Path:
        local = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(local) / "Constructor" / "agent_workspaces"

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
        with self._stdin_lock:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()

    def _handle_tool_request(
        self,
        process: subprocess.Popen[str],
        payload: dict[str, Any],
        *,
        workflow_id: str,
        cwd: str,
        on_question: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        should_stop: Callable[[], bool] | None = None,
        confirm_writes: bool = False,
    ) -> None:
        request_id = str(payload.get("requestId") or "")
        tool = str(payload.get("tool") or "")
        args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        args = dict(args)
        if is_ask_question(tool):
            reply = {"ok": False, "answer": "", "error": "No UI waiter for askQuestion"}
            if on_question is not None:
                try:
                    incoming = on_question(payload)
                    if isinstance(incoming, dict):
                        reply = incoming
                except Exception as exc:  # noqa: BLE001
                    reply = {"ok": False, "answer": "", "error": str(exc)}
            answer = str(reply.get("answer") or reply.get("text") or "").strip()
            error = str(reply.get("error") or "").strip()
            ok = bool(reply.get("ok", True)) and bool(answer)
            self._send(
                process,
                {
                    "type": "tool_result",
                    "requestId": request_id,
                    "ok": ok,
                    "result": {"answer": answer, "text": answer},
                    "error": error or None,
                },
            )
            return
        if workflow_id:
            args.setdefault("workflow_id", workflow_id)
            args.setdefault("agent_id", workflow_id)
            args.setdefault("runtime_context", {"workflow_id": workflow_id, "agent_id": workflow_id})
        self._mark_active(request_id, tool)
        send_lock = threading.Lock()
        sent = False

        def send_result(message: dict[str, Any]) -> bool:
            nonlocal sent
            with send_lock:
                if sent:
                    return False
                sent = True
                self._send(process, message)
                return True

        if self._is_skipped(request_id) or (should_stop is not None and should_stop()):
            send_result(
                {
                    "type": "tool_result",
                    "requestId": request_id,
                    "ok": True,
                    "result": self.skipped_tool_result(tool),
                }
            )
            self._clear_active(request_id)
            return

        done = threading.Event()
        box: dict[str, Any] = {"result": None, "error": None}

        def work() -> None:
            try:
                if self._is_skipped(request_id) or (
                    should_stop is not None and should_stop()
                ):
                    box["result"] = self.skipped_tool_result(tool)
                    return
                if confirm_writes:
                    allowed, rejected = self._confirm_write_tool(tool, args)
                    if not allowed:
                        box["result"] = rejected
                        return
                    if self._is_skipped(request_id) or (
                        should_stop is not None and should_stop()
                    ):
                        box["result"] = self.skipped_tool_result(tool)
                        return
                result = invoke_sdk_tool(tool, args)
                if self._is_skipped(request_id) or (
                    should_stop is not None and should_stop()
                ):
                    box["result"] = self.skipped_tool_result(tool)
                    return
                try:
                    from app.tools.result_files import publish_result_files

                    publish_result_files(result, tool=tool, workflow_id=workflow_id)
                except Exception:
                    pass
                result = self._externalize_large_result(
                    tool=tool,
                    request_id=request_id,
                    result=result,
                    cwd=cwd,
                )
                box["result"] = result
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc
            finally:
                done.set()

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        while not done.wait(timeout=0.12):
            if self._is_skipped(request_id) or (should_stop is not None and should_stop()):
                send_result(
                    {
                        "type": "tool_result",
                        "requestId": request_id,
                        "ok": True,
                        "result": self.skipped_tool_result(tool),
                    }
                )
                self._clear_active(request_id)
                return

        if self._is_skipped(request_id) or (should_stop is not None and should_stop()):
            send_result(
                {
                    "type": "tool_result",
                    "requestId": request_id,
                    "ok": True,
                    "result": self.skipped_tool_result(tool),
                }
            )
            self._clear_active(request_id)
            return

        error = box.get("error")
        if error is not None:
            if isinstance(error, ToolHostError):
                message = str(error)
            else:
                message = f"Ошибка инструмента {tool}: {error}"
            send_result(
                {
                    "type": "tool_result",
                    "requestId": request_id,
                    "ok": False,
                    "error": message,
                }
            )
        else:
            send_result(
                {
                    "type": "tool_result",
                    "requestId": request_id,
                    "ok": True,
                    "result": box.get("result") or {},
                }
            )
        self._clear_active(request_id)

    def _externalize_large_result(
        self,
        *,
        tool: str,
        request_id: str,
        result: dict[str, Any],
        cwd: str,
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            return result
        try:
            raw = json.dumps(result, ensure_ascii=False, default=str)
        except TypeError:
            return result
        raw_bytes = len(raw.encode("utf-8", errors="replace"))
        if raw_bytes <= LARGE_TOOL_RESULT_BYTES:
            return result
        base = Path(cwd).resolve()
        out_dir = base / "tool_results"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_tool = re.sub(r"[^A-Za-z0-9_.-]", "_", tool or "tool") or "tool"
        safe_request = re.sub(r"[^A-Za-z0-9_.-]", "_", request_id or "")[:12] or uuid.uuid4().hex[:12]
        filename = f"{safe_tool}_{safe_request}.json"
        target = (out_dir / filename).resolve()
        if base != target and base not in target.parents:
            return result
        target.write_text(raw, encoding="utf-8")
        rel_path = target.relative_to(base).as_posix()
        return {
            "summary": self._result_summary(result),
            "sample": self._result_sample(result),
            "tool": tool,
            "result_file": rel_path,
            "result_bytes": raw_bytes,
            "externalized": True,
            "next_step": EXTERNALIZED_NEXT_STEP,
        }

    @staticmethod
    def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        text = result.get("summary")
        if isinstance(text, str) and text.strip():
            summary["summary"] = text.strip()
        for key, value in result.items():
            if isinstance(value, (int, float, bool)) or value is None:
                summary[key] = value
            elif isinstance(value, str):
                summary[key] = value[:500]
            elif isinstance(value, list):
                summary[f"{key}_count"] = len(value)
            elif isinstance(value, dict):
                summary[f"{key}_keys"] = list(value.keys())[:20]
        return summary

    @staticmethod
    def _result_sample(result: dict[str, Any]) -> dict[str, Any]:
        sample: dict[str, Any] = {}
        for key, value in result.items():
            if isinstance(value, list):
                sample[key] = [
                    CursorSdkBridge._shrink_sample_item(item)
                    for item in value[:EXTERNALIZED_SAMPLE_ITEMS]
                ]
            elif isinstance(value, dict):
                sample[key] = {
                    inner_key: CursorSdkBridge._shrink_sample_item(inner)
                    for inner_key, inner in list(value.items())[:12]
                }
            elif isinstance(value, str):
                sample[key] = value[:500]
            else:
                sample[key] = value
        return sample

    @staticmethod
    def _shrink_sample_item(value: Any) -> Any:
        if isinstance(value, str):
            return value[:240]
        if isinstance(value, dict):
            return {
                key: CursorSdkBridge._shrink_sample_item(inner)
                for key, inner in list(value.items())[:12]
            }
        if isinstance(value, list):
            return [CursorSdkBridge._shrink_sample_item(item) for item in value[:4]]
        return value

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
