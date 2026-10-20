from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import DESKTOP_ROOT, reload_cursor_api_key
from app.sdk_agent.prompt import strip_to_work_result
from app.sdk_agent.tool_adapter import (
    invoke_sdk_tool,
    is_ask_question,
    sdk_kpi_tool_specs,
    sdk_tool_specs,
    tool_timeout_seconds,
)
from app.tools import ToolHostError

DEFAULT_SDK_MODEL = "grok-4.7"
REGULATION_SDK_MODEL = "grok-4.6"
# grok-4.7: Extra High + Fast. reasoning_effort, не effort (это параметр grok-4.6).
WORKFLOW_SDK_MODEL_PARAMS = (
    {"id": "reasoning_effort", "value": "xhigh"},
    {"id": "fast", "value": "true"},
)
REGULATION_PREFETCH_MODEL = "composer-2.5"
REGULATION_SDK_MODEL_PARAMS = (
    {"id": "effort", "value": "low"},
    {"id": "fast", "value": "true"},
)
REGULATION_SDK_QUESTION_PARAMS = (
    {"id": "effort", "value": "low"},
    {"id": "fast", "value": "true"},
)
KPI_SDK_MODEL_PARAMS = (
    {"id": "effort", "value": "low"},
    {"id": "fast", "value": "true"},
)
LARGE_TOOL_RESULT_BYTES = 6_000
ENVELOPE_LIST_MIN = 50
EXTERNALIZED_NEXT_STEP = (
    "Full JSON is in result_file relative to cwd. "
    "Open it with the built-in Read tool in pages (offset/limit) or search inside it; "
    "do not load the whole file at once. "
    "Do not call the same Constructor tool again for this data."
)


class CursorSdkError(RuntimeError):
    pass


class CursorSdkUnavailable(CursorSdkError):
    pass


RUNNER_CRASH_PREFIX = "Процесс Cursor SDK аварийно завершился"

_TRANSIENT_SDK_MARKERS = (
    RUNNER_CRASH_PREFIX.casefold(),
    "network request failed",
    "cursor sdk run failed",
    "econnreset",
    "etimedout",
    "socket hang up",
    "fetch failed",
    "database is locked",
    "without result",
    "завершился без результата",
)


def is_transient_cursor_error(exc: BaseException | str) -> bool:
    blob = str(exc or "").casefold()
    return any(token in blob for token in _TRANSIENT_SDK_MARKERS)


_NATIVE_FRAME = re.compile(r"^\s*\d+:\s+[0-9A-Fa-f]{8,}\b")


def runner_stderr_reason(lines: list[str]) -> str:
    """Readable reason from runner stderr; a native Node crash keeps its cause above the frames."""
    rows = [line.rstrip() for line in lines if line and line.strip()]
    if not rows:
        return ""
    tail = rows[-20:]
    frames = sum(1 for line in tail if _NATIVE_FRAME.match(line))
    if frames * 2 < len(tail):
        return "\n".join(tail)
    head = [line.strip() for line in rows if not _NATIVE_FRAME.match(line)]
    cause = "\n".join(head[:6]).strip() or "сбой Node.js без описания"
    return f"{RUNNER_CRASH_PREFIX}: {cause}"


def save_runner_stderr(run_id: str, lines: list[str]) -> Path | None:
    if not any(line.strip() for line in lines):
        return None
    local = os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(local) / "Constructor" / "logs" / f"sdk-runner-{run_id}.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        return None
    return path


def cursor_sdk_error_text(
    *,
    status: str,
    answer: str,
    error_events: list[str],
    stderr: str = "",
) -> str:
    if (status or "").strip().casefold() != "error":
        return ""
    for item in (answer, *(error_events[-1:] if error_events else []), stderr.strip()):
        text = str(item or "").strip()
        if text:
            return text
    return "Cursor SDK run failed"


def is_complete_kpi_list_answer(text: str) -> bool:
    """Accept a complete KPI list even when the SDK reports a late transport error."""
    blob = str(text or "")
    if re.search(r"generated/|score_\w+_kpi|def\s+score_", blob):
        return False
    lines = blob.splitlines()
    try:
        done_at = next(
            index
            for index, line in enumerate(lines)
            if re.fullmatch(r"\s*СПИСОК_ГОТОВ\s*", line)
        )
    except StopIteration:
        return False
    weighted = re.compile(r"\s*(?:(?:\d+[\).]|[-*•])\s*)?.+\d{1,3}\s*%")
    numbered = re.compile(r"\s*(?:\d+[\).]|[-*•])\s*\S")
    count = 0
    for line in lines[:done_at]:
        if numbered.match(line) and not weighted.match(line):
            return False
        if weighted.match(line):
            count += 1
    return count > 0


SdkEventCallback = Callable[[dict[str, Any]], None]

_SDK_OWNER_ENV = "CONSTRUCTOR_SDK_OWNER"


def _norm_cmd(text: str) -> str:
    return text.replace("/", "\\").casefold()


def foreign_runner_pids(
    rows: list[tuple[int, int, str]],
    *,
    owner: str,
    me: int,
) -> list[int]:
    """Pids of SDK runners that belong to a previous sidecar of this app, or to none.

    A runner whose parent chain still reaches this process is kept. A runner
    owned by another app (a different sidecar path) is kept too.
    """
    owner_norm = _norm_cmd(owner)
    if not owner_norm:
        return []
    by_pid = {pid: (ppid, cmd) for pid, ppid, cmd in rows}
    doomed: list[int] = []
    seen: set[int] = set()
    for pid, _ppid, cmd in rows:
        folded = cmd.casefold()
        if "runner.ts" not in folded or "sdk-agent" not in folded:
            continue
        kill_pid, sidecar_pid, sidecar_cmd = _runner_owner(pid, by_pid)
        if kill_pid is None or sidecar_pid == me:
            continue
        if sidecar_pid and owner_norm not in _norm_cmd(sidecar_cmd):
            continue
        if kill_pid in seen:
            continue
        seen.add(kill_pid)
        doomed.append(kill_pid)
    return doomed


def _runner_owner(
    runner_pid: int, by_pid: dict[int, tuple[int, str]]
) -> tuple[int | None, int, str]:
    """Return (pid to kill, sidecar pid or 0, sidecar command)."""
    seen: set[int] = set()
    current = runner_pid
    child_of_sidecar = runner_pid
    while current and current not in seen:
        seen.add(current)
        row = by_pid.get(current)
        if row is None:
            return runner_pid, 0, ""
        ppid, cmd = row
        if "agent_sidecar.py" in cmd.casefold():
            return child_of_sidecar, current, cmd
        if ppid <= 0 or ppid == current or ppid not in by_pid:
            return current, 0, ""
        child_of_sidecar = current
        current = ppid
    return None, 0, ""


def _kill_pid_tree(pid: int) -> None:
    if not pid or pid == os.getpid():
        return
    if sys.platform != "win32":
        try:
            os.kill(pid, 15)
        except OSError:
            return
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def _win_process_rows() -> list[tuple[int, int, str]]:
    script = (
        "Get-CimInstance Win32_Process | "
        "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.ParentProcessId, "
        "(($_.CommandLine) -replace '[\\r\\n|]', ' ') }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: list[tuple[int, int, str]] = []
    for line in (result.stdout or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        rows.append((pid, ppid, parts[2]))
    return rows


def reap_foreign_sdk_runners() -> None:
    """Drop model processes left behind by a replaced or killed sidecar."""
    owner = os.environ.get(_SDK_OWNER_ENV, "").strip()
    if sys.platform != "win32" or not owner:
        return
    rows = _win_process_rows()
    for pid in foreign_runner_pids(rows, owner=owner, me=os.getpid()):
        _kill_pid_tree(pid)


class CursorSdkBridge:
    def __init__(self, *, node: str = "node", runner: Path | None = None) -> None:
        self._node = os.getenv("CONSTRUCTOR_NODE", "").strip() or node
        self._sdk_root = DESKTOP_ROOT / "sdk-agent"
        self._runner = runner or self._sdk_root / "src" / "runner.ts"
        self._skip_lock = threading.Lock()
        self._stdin_lock = threading.Lock()
        self._workers_lock = threading.Lock()
        self._skip_ids: set[str] = set()
        self._active_request_ids: set[str] = set()
        self._active_tool_names: dict[str, str] = {}
        self._tool_workers: list[threading.Thread] = []
        self._process: subprocess.Popen[str] | None = None

    def close(self) -> None:
        """Stop the SDK runner and the model process it spawned."""
        self._kill_tree(self._process)

    def _kill_tree(self, process: subprocess.Popen[str] | None) -> None:
        if process is None or process.poll() is not None:
            return
        pid = process.pid
        if sys.platform == "win32" and pid:
            # tsx.cmd is cmd.exe. Killing only that pid leaves the node model running.
            _kill_pid_tree(pid)
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    return
            return
        try:
            process.kill()
        except OSError:
            return

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

    def _after_tool_result(
        self, tool: str, result: dict[str, Any], workflow_id: str
    ) -> None:
        """Hook after a local tool returns. Sidecar uploads created files here."""
        return

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

    @staticmethod
    def _emit_event(on_event: SdkEventCallback | None, payload: dict[str, Any]) -> None:
        if on_event is None:
            return
        try:
            on_event(payload)
        except Exception:
            return

    def run(
        self,
        *,
        prompt: str,
        workflow_id: str,
        model: str = "",
        model_params: list[dict[str, str]] | None = None,
        cwd: str = "",
        mode: str = "run",
        tools: list[dict[str, Any]] | None = None,
        write_document: bool = False,
        use_tools: bool = False,
        resume_agent_id: str = "",
        on_event: SdkEventCallback | None = None,
        on_question: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        should_stop: Callable[[], bool] | None = None,
        confirm_writes: bool = False,
        restrict_builtins: bool = False,
        images: list[dict[str, Any]] | None = None,
        stop_on_kpi_list: bool = True,
        kpi_allow_read: bool = False,
    ) -> dict[str, Any]:
        reload_cursor_api_key()
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
        self._writes_action_tracker = tools is None or any(
            isinstance(spec, dict) and spec.get("name") == "excel.write_action_tracker"
            for spec in tools
        )
        run_cwd = cwd or self._workspace_cwd(workflow_id)
        agent_id = resume_agent_id.strip()
        stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process, stderr_lines),
            daemon=True,
        )
        stderr_thread.start()
        self._process = process

        def stderr_reason() -> str:
            stderr_thread.join(timeout=2)
            reason = runner_stderr_reason(stderr_lines)
            saved = save_runner_stderr(run_id, stderr_lines)
            if saved is not None and reason.startswith(RUNNER_CRASH_PREFIX):
                reason += f"\nПолный вывод: {saved}"
            return reason

        if should_stop is not None:
            def _watch_stop() -> None:
                # The stdout loop only notices a stop when the next line arrives.
                # A model waiting on the network emits nothing, so the previous
                # runner has to be killed from here or it stays beside the next one.
                while process.poll() is None:
                    try:
                        stopped = bool(should_stop())
                    except Exception:
                        return
                    if stopped:
                        self._kill_tree(process)
                        return
                    time.sleep(0.4)

            threading.Thread(
                target=_watch_stop,
                name="sdk-stop-watch",
                daemon=True,
            ).start()
        try:
            final: dict[str, Any] | None = None
            interview = mode == "interview"
            run_model = (
                model
                or (
                    os.getenv("CURSOR_REGULATION_SDK_MODEL", REGULATION_SDK_MODEL)
                    if interview
                    else os.getenv("CURSOR_SDK_MODEL", DEFAULT_SDK_MODEL)
                )
            )
            if model_params is not None:
                run_params = list(model_params)
            elif interview:
                run_params = [dict(item) for item in REGULATION_SDK_MODEL_PARAMS]
            elif (mode or "").strip().casefold() == "kpi":
                run_params = [dict(item) for item in KPI_SDK_MODEL_PARAMS]
            else:
                run_params = [dict(item) for item in WORKFLOW_SDK_MODEL_PARAMS]
            try:
                self._send(
                    process,
                    {
                        "type": "run",
                        "id": run_id,
                        "prompt": prompt,
                        "model": run_model,
                        "modelParams": run_params,
                        "cwd": run_cwd,
                        "mode": (
                            "interview"
                            if interview
                            else "design"
                            if mode == "design"
                            else "kpi"
                            if (mode or "").strip().casefold() == "kpi"
                            else "run"
                        ),
                        "writeDocument": bool(write_document),
                        "useTools": bool(use_tools or write_document),
                        "tools": (
                            sdk_kpi_tool_specs()
                            if tools is None and (mode or "").strip().casefold() == "kpi"
                            else sdk_tool_specs()
                            if tools is None
                            else tools
                        ),
                        "resumeAgentId": agent_id or None,
                        "workflowId": workflow_id,
                        "restrictBuiltins": bool(restrict_builtins),
                        "stopOnKpiList": bool(stop_on_kpi_list),
                        "kpiAllowRead": bool(kpi_allow_read),
                        "images": [
                            item
                            for item in (images or [])
                            if isinstance(item, dict) and (item.get("path") or item.get("data"))
                        ],
                    },
                )
            except CursorSdkError as exc:
                # The runner died before reading the task; its stderr holds the reason.
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                raise CursorSdkError(stderr_reason() or str(exc)) from exc
            assert process.stdout is not None
            # "assistant" events are raw stream deltas of one message: join them
            # as-is (no strip / separators) or words get split in half.
            # "final" carries the runner's cleaned answer and wins when present.
            answer_parts: list[str] = []
            error_events: list[str] = []
            final_text = ""

            def collected_answer() -> str:
                text = final_text.strip() or "".join(answer_parts).strip()
                if mode == "run":
                    text = strip_to_work_result(text)
                return text

            for line in process.stdout:
                payload = self._parse_line(line)
                if not payload:
                    continue
                event_type = str(payload.get("type") or "")
                if event_type == "ready":
                    continue
                if event_type == "error":
                    message = str(payload.get("message") or payload.get("error") or "").strip()
                    if message:
                        error_events.append(message)
                if should_stop is not None and should_stop():
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
                    try:
                        self._send(process, {"type": "cancel", "id": run_id})
                    except CursorSdkError:
                        pass
                    self._kill_tree(process)
                    return {
                        "answer": collected_answer(),
                        "status": "ok",
                        "run_id": run_id,
                        "agent_id": agent_id,
                    }
                if event_type == "tool_request":
                    # Do not block the stdout reader: Cursor can emit several
                    # tool_request lines at once. One hung tool must not stall
                    # the rest in the pipe until Node times them all out.
                    self._start_tool_request(
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
                if event_type == "assistant":
                    text = str(payload.get("text") or "")
                    if text:
                        answer_parts.append(text)
                elif event_type == "final":
                    text = str(payload.get("answer") or payload.get("text") or "").strip()
                    if text:
                        final_text = text
                if event_type == "done":
                    final = payload
                    self._emit_event(on_event, payload)
                    break
                self._emit_event(on_event, payload)
                if should_stop is not None and should_stop():
                    try:
                        self._send(process, {"type": "cancel", "id": run_id})
                    except CursorSdkError:
                        pass
                    self._kill_tree(process)
                    return {
                        "answer": collected_answer(),
                        "status": "ok",
                        "run_id": run_id,
                        "agent_id": agent_id,
                    }
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._kill_tree(process)
            if final is None:
                collected = collected_answer()
                if collected:
                    return {
                        "answer": collected,
                        "status": "ok",
                        "run_id": run_id,
                        "agent_id": agent_id,
                    }
                raise CursorSdkError(
                    stderr_reason() or "Cursor SDK runner завершился без результата"
                )
            status = str(final.get("status") or "")
            answer = (
                str(final.get("answer") or "")
                or final_text.strip()
                or "".join(answer_parts).strip()
            )
            if status == "error":
                if (
                    (mode or "").strip().casefold() == "kpi"
                    and stop_on_kpi_list
                    and is_complete_kpi_list_answer(answer)
                ):
                    return {
                        "answer": answer,
                        "status": "ok",
                        "run_id": run_id,
                        "agent_id": agent_id,
                    }
                raise CursorSdkError(
                    cursor_sdk_error_text(
                        status=status,
                        answer=answer,
                        error_events=error_events,
                        stderr=stderr_reason(),
                    )
                )
            if mode == "run":
                answer = strip_to_work_result(answer)
            return {
                "answer": answer,
                "status": status or "ok",
                "run_id": run_id,
                "agent_id": agent_id,
            }
        finally:
            self._process = None
            if process.poll() is None:
                self._kill_tree(process)

    def _ensure_ready(self) -> None:
        reload_cursor_api_key()
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
        key = reload_cursor_api_key()
        if key:
            env["CURSOR_API_KEY"] = key
        env.setdefault("NODE_NO_WARNINGS", "1")
        return env

    def _send(self, process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
        if process.stdin is None:
            raise CursorSdkError("Cursor SDK runner stdin закрыт")
        with self._stdin_lock:
            try:
                process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise CursorSdkError(f"Cursor SDK runner завершился: {exc}") from exc

    def _reap_tool_workers(self) -> None:
        with self._workers_lock:
            self._tool_workers = [item for item in self._tool_workers if item.is_alive()]

    def _start_tool_request(
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
        self._reap_tool_workers()
        tool = str(payload.get("tool") or "tool").strip() or "tool"
        thread = threading.Thread(
            target=self._run_tool_request,
            kwargs={
                "process": process,
                "payload": payload,
                "workflow_id": workflow_id,
                "cwd": cwd,
                "on_question": on_question,
                "should_stop": should_stop,
                "confirm_writes": confirm_writes,
            },
            daemon=True,
            name=f"sdk-tool-{tool[:48]}",
        )
        with self._workers_lock:
            self._tool_workers.append(thread)
        thread.start()

    def _run_tool_request(
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
        tool = str(payload.get("tool") or "tool")
        try:
            self._handle_tool_request(
                process,
                payload,
                workflow_id=workflow_id,
                cwd=cwd,
                on_question=on_question,
                should_stop=should_stop,
                confirm_writes=confirm_writes,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                self._send(
                    process,
                    {
                        "type": "tool_result",
                        "requestId": request_id,
                        "ok": False,
                        "error": f"Ошибка инструмента {tool}: {exc}",
                    },
                )
            except CursorSdkError:
                pass
            self._clear_active(request_id)

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
        tool_limit = float(tool_timeout_seconds(tool, args))
        started_at = time.monotonic()
        # Confirmation can wait on a person. The tool budget starts after it.
        phase: dict[str, Any] = {"invoke": False, "t0": 0.0}

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
                    args["human_approved"] = True
                    runtime = args.get("runtime_context")
                    if isinstance(runtime, dict):
                        runtime["human_approved"] = True
                    else:
                        args["runtime_context"] = {
                            "workflow_id": workflow_id,
                            "agent_id": workflow_id,
                            "human_approved": True,
                        }
                    if self._is_skipped(request_id) or (
                        should_stop is not None and should_stop()
                    ):
                        box["result"] = self.skipped_tool_result(tool)
                        return
                phase["t0"] = time.monotonic()
                phase["invoke"] = True
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
                # Unblock the SDK before uploading the file. A slow backend
                # must not turn a finished export into "Tool result timeout".
                box["result"] = result
                done.set()
                try:
                    self._after_tool_result(tool, result, workflow_id)
                except Exception:
                    pass
                return
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
            if phase["invoke"]:
                elapsed = time.monotonic() - float(phase["t0"])
                limit = tool_limit
            else:
                elapsed = time.monotonic() - started_at
                limit = max(tool_limit, 600.0)
            if elapsed >= limit:
                send_result(
                    {
                        "type": "tool_result",
                        "requestId": request_id,
                        "ok": False,
                        "error": f"Инструмент {tool} не ответил за {int(limit)} с",
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
        if result.get("externalized") and isinstance(result.get("result_file"), str):
            return result
        journal_extract = (
            tool in {"onec.erp_assignments", "onec.meeting_protocols"}
            and not result.get("error")
            and getattr(self, "_writes_action_tracker", True)
        )
        if not journal_extract and not self._should_externalize_result(result, raw_bytes):
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
        next_step = EXTERNALIZED_NEXT_STEP
        if journal_extract:
            next_step = (
                "Не читай result_file и не открывай tool_results. "
                "После обеих выборок один раз вызови excel.write_action_tracker "
                "с filename=ActionTracker.xlsx. Строки не передавай: инструмент запишет все карточки сам."
            )
        return {
            "summary": self._result_summary(result),
            "tool": tool,
            "result_file": rel_path,
            "result_bytes": raw_bytes,
            "externalized": True,
            "next_step": next_step,
        }

    @staticmethod
    def _should_externalize_result(result: dict[str, Any], raw_bytes: int) -> bool:
        if result.get("vision") and result.get("vision_pages"):
            return False
        if raw_bytes > LARGE_TOOL_RESULT_BYTES:
            return True
        for value in result.values():
            if isinstance(value, list) and len(value) >= ENVELOPE_LIST_MIN:
                return True
        return False

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
                # Ready-made tables the agent must paste verbatim stay whole.
                summary[key] = value[:12_000] if key.endswith("_markdown") else value[:500]
            elif isinstance(value, list):
                summary[f"{key}_count"] = len(value)
            elif isinstance(value, dict):
                summary[f"{key}_keys"] = list(value.keys())[:20]
        return summary

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
