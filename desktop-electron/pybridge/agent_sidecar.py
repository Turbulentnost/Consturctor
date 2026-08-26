"""Constructor Electron agent sidecar.

A long-lived process that bridges the Electron main process and the local
Cursor SDK. It reuses the existing desktop code (CursorSdkBridge, ApiClient,
sdk_agent, tools) without modifying it, so the Electron UI gets full parity:
real local Cursor SDK runs, local tool execution (1C/Outlook/Excel/...),
askQuestion clarify and HITL write approvals.

Protocol: newline-delimited JSON.
  stdin  (from Electron):
    {"type": "configure", "backendUrl": str, "token": str}
    {"type": "check_ready"}
    {"type": "design", "id": str, "workflowId": str}
    {"type": "demo", "id": str, "workflowId": str}
    {"type": "run", "id": str, "workflowId": str, "message": str,
       "source": str, "triggerId": str, "resumeAgentId": str}
    {"type": "check_trigger", "id": str, "triggerId": str}
    {"type": "answer", "requestId": str, "ok": bool, "answer": str}
    {"type": "hitl", "requestId": str, "approved": bool}
    {"type": "skip", "requestId": str}
    {"type": "cancel", "id": str}
  stdout (to Electron):
    {"type": "ready"}
    {"type": "event", "runId": str, "payload": {...}}   # raw runner event
    {"type": "question", "runId": str, "requestId": str, "question": str,
       "options": [str, ...]}
    {"type": "hitl", "runId": str, "requestId": str, "tool": str,
       "arguments": {...}}
    {"type": "result", "runId": str, "kind": str, "workflow"|"run": {...}}
    {"type": "error", "runId": str, "message": str}
    {"type": "ready_state", "ok": bool, "message": str}

All console/log text is ASCII to stay safe on Windows consoles.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _bootstrap_desktop_path() -> Path:
    """Add the repo desktop/ folder to sys.path so app.* is importable."""
    here = Path(__file__).resolve()
    # .../NewConstructor/desktop-electron/pybridge/agent_sidecar.py
    repo_root = here.parents[2]
    desktop_root = repo_root / "desktop"
    if not desktop_root.is_dir():
        raise RuntimeError(f"desktop folder not found at {desktop_root}")
    path_str = str(desktop_root)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
    return desktop_root


DESKTOP_ROOT = _bootstrap_desktop_path()

# Importing app.config loads desktop/.env (CURSOR_API_KEY, BACKEND_URL, ...).
from app.api_client import ApiClient, ApiError  # noqa: E402
from app.sdk_agent.bridge import CursorSdkBridge, CursorSdkUnavailable  # noqa: E402
from app.sdk_agent.files import prepare_sdk_workspace  # noqa: E402
from app.sdk_agent.prompt import (  # noqa: E402
    build_demo_sdk_prompt,
    build_design_sdk_prompt,
    build_followup_sdk_prompt,
    build_sdk_prompt,
)

# HITL classification replicated from app.tools.hitl.needs_confirmation.
# We do NOT import that module because it pulls in PySide6/Qt at import time,
# which is not needed (and not always available) for a headless sidecar.
# Level-1 autonomy: read tools auto-run, write tools need confirmation.
_NEVER_CONFIRM = frozenset({"notify.send", "notify"})
_READ_EXACT = frozenset(
    {
        "web_search",
        "site_browser",
        "browser.search_web",
        "browser.open_page",
        "browser.list_installed_browsers",
        "browser.screenshot",
        "browser.get_page_html",
        "outlook.search_mail",
        "outlook.read_calendar",
        "excel.list_files",
        "excel.read_workbook",
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.sql_query",
        "onec.erp_tasks_current",
        "onec.erp_tasks_period",
        "onec.erp_subordinate_tasks",
        "onec.docflow_tasks",
        "onec.meeting_service_notes",
        "agent.wait",
        "turboproject",
        "users.list",
        "users.current",
        "users.subordinates",
        "agent.schedule",
        "agent.schedule.cancel",
    }
)
_READ_PREFIXES = ("onec.search_", "onec.get_", "imap.", "turboproject.")


def _is_read_tool(name: str) -> bool:
    tool = (name or "").strip()
    if tool in _NEVER_CONFIRM or tool in _READ_EXACT:
        return True
    return any(tool.startswith(prefix) for prefix in _READ_PREFIXES)


def needs_confirmation(name: str) -> bool:
    tool = (name or "").strip()
    if tool in _NEVER_CONFIRM:
        return False
    return not _is_read_tool(tool)


_STDOUT_LOCK = threading.Lock()


def emit(message: dict[str, Any]) -> None:
    """Write one JSON line to stdout for the Electron main process."""
    line = json.dumps(message, ensure_ascii=False, default=_json_default)
    with _STDOUT_LOCK:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def log(message: str) -> None:
    """ASCII-safe diagnostic to stderr (never stdout, which is the protocol)."""
    safe = message.encode("ascii", errors="replace").decode("ascii")
    sys.stderr.write(safe + "\n")
    sys.stderr.flush()


def _json_default(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return str(value)


class ElectronBridge(CursorSdkBridge):
    """CursorSdkBridge that routes HITL write approvals to Electron.

    The base class only knows how to confirm writes through the Qt UI and
    auto-approves when no QApplication exists. Here we block on an Electron
    round-trip instead, so the desktop-electron UI can show approve/reject.
    """

    def __init__(self, hitl_gate: HitlGate, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._hitl_gate = hitl_gate

    def _confirm_write_tool(
        self, tool: str, args: dict[str, Any]
    ) -> tuple[bool, dict[str, Any] | None]:
        try:
            if not needs_confirmation(tool):
                return True, None
        except Exception:  # noqa: BLE001
            return True, None
        approved = self._hitl_gate.request(tool, args)
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


class HitlGate:
    """Correlates HITL/askQuestion prompts with Electron responses."""

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._hitl: dict[str, queue.Queue[bool]] = {}
        self._answers: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def request(self, tool: str, args: dict[str, Any]) -> bool:
        request_id = uuid.uuid4().hex
        box: queue.Queue[bool] = queue.Queue(maxsize=1)
        with self._lock:
            self._hitl[request_id] = box
        emit(
            {
                "type": "hitl",
                "runId": self._run_id,
                "requestId": request_id,
                "tool": tool,
                "arguments": _safe_args(args),
            }
        )
        try:
            return box.get()
        finally:
            with self._lock:
                self._hitl.pop(request_id, None)

    def resolve_hitl(self, request_id: str, approved: bool) -> None:
        with self._lock:
            box = self._hitl.get(request_id)
        if box is not None:
            try:
                box.put_nowait(approved)
            except queue.Full:
                pass

    def ask_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("requestId") or uuid.uuid4().hex)
        question = str(payload.get("question") or payload.get("text") or "").strip()
        options = payload.get("options")
        if not isinstance(options, list):
            options = []
        box: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._lock:
            self._answers[request_id] = box
        emit(
            {
                "type": "question",
                "runId": self._run_id,
                "requestId": request_id,
                "question": question,
                "options": [str(opt) for opt in options],
            }
        )
        try:
            reply = box.get()
        finally:
            with self._lock:
                self._answers.pop(request_id, None)
        answer = str(reply.get("answer") or reply.get("text") or "").strip()
        ok = bool(reply.get("ok", True)) and bool(answer)
        return {"ok": ok, "answer": answer, "text": answer}

    def resolve_answer(self, request_id: str, reply: dict[str, Any]) -> None:
        with self._lock:
            box = self._answers.get(request_id)
        if box is not None:
            try:
                box.put_nowait(reply)
            except queue.Full:
                pass


def _safe_args(args: dict[str, Any]) -> dict[str, Any]:
    """Trim internal/bulky keys before showing tool arguments in the UI."""
    hidden = {"runtime_context", "agent_id", "workflow_id"}
    out: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if key in hidden:
            continue
        if isinstance(value, str) and len(value) > 2000:
            out[key] = value[:2000] + "..."
        else:
            out[key] = value
    return out


READINESS_AGENTS_MD = """\
# Уточнение регламента Constructor

Инструменты Constructor уже подключены как customTools. Не ищи проектный MCP или mcp.json.
Работай только на русском.

Твоя задача - закрыть пробелы логики регламента перед созданием ИИ-агентов.
Сначала прочитай materials/regulation.md, materials/functions.md, materials/answers.md и materials/manifest.json.

Иди по каждому функциональному блоку из materials/functions.md.
Для каждого блока проверь, понятны ли: входы, стартовое событие, условия, система, конкретное действие,
ветвления, результат, получатель, контроль выполнения, ошибки и эскалация.
Если без ответа будущий агент будет угадывать, вызови askQuestion.

Правила вопросов:
- один пробел - один вопрос;
- в вопросе называй функциональный блок простыми словами;
- если есть разумные варианты, передай их в options;
- не спрашивай то, что уже есть в материалах или в ответах пользователя;
- после ответа продолжай с учетом этого ответа, не начинай заново;
- если пользователь упомянул прикрепленные файлы, считай их обязательными материалами.

Когда все блоки закрыты, напиши строго JSON без markdown:
{
  "status": "ready",
  "blocks": [
    {"functionId": "...", "title": "...", "closedGaps": ["..."], "logic": "..."}
  ],
  "required_clarifications": []
}
После JSON остановись.
"""


def _write_text(cwd: str, relative: str, text: str) -> str:
    root = Path(cwd).resolve()
    target = (root / relative).resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"refusing to write outside workspace: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return relative.replace("\\", "/")


def _prepare_readiness_workspace(api: ApiClient, draft: Any, cwd: str) -> None:
    regulation = api.get_regulation(draft.regulation_id)
    suggestions = list(draft.agent_suggestions or [])
    by_block = {item.fragment_id: item for item in regulation.fragments}

    _write_text(cwd, "AGENTS.md", READINESS_AGENTS_MD)
    regulation_lines = [f"# {regulation.file_name}", ""]
    for fragment in regulation.fragments:
        text = (fragment.text or "").strip()
        if not text:
            continue
        section = (fragment.section or "").strip()
        header = f"## {fragment.fragment_id}"
        if section:
            header += f" - {section}"
        regulation_lines.extend([header, text, ""])
    _write_text(cwd, "materials/regulation.md", "\n".join(regulation_lines).strip() + "\n")

    function_lines = ["# Функциональные блоки", ""]
    for index, item in enumerate(suggestions, start=1):
        source = by_block.get(item.source_block_id)
        function_lines.extend(
            [
                f"## {index}. {item.title}",
                f"functionId: {item.function_id}",
                f"sourceBlockId: {item.source_block_id}",
            ]
        )
        if item.description:
            function_lines.extend(["", item.description.strip()])
        if source is not None and source.text:
            function_lines.extend(["", "Цитата регламента:", source.text.strip()])
        function_lines.append("")
    if not suggestions:
        function_lines.append("Функциональные блоки не найдены в черновике. Сначала уточни общий процесс.")
    _write_text(cwd, "materials/functions.md", "\n".join(function_lines).strip() + "\n")

    data = getattr(draft, "result_json", None)
    if not isinstance(data, dict):
        data = {}
    readiness = data.get("sdkReadiness") if isinstance(data.get("sdkReadiness"), dict) else {}
    previous = str(readiness.get("answer") or "").strip()
    _write_text(
        cwd,
        "materials/answers.md",
        (previous or "Ответов пользователя пока нет.") + "\n",
    )
    _write_text(cwd, "materials/manifest.json", json.dumps({"files": []}, ensure_ascii=False, indent=2) + "\n")


def _build_readiness_prompt() -> str:
    return (
        "Прочитай AGENTS.md и все файлы в materials. "
        "Закрой через askQuestion пробелы логики по каждому функциональному блоку. "
        "Когда все пробелы закрыты, верни JSON readiness и остановись."
    )


class Sidecar:
    def __init__(self) -> None:
        self._api = ApiClient()
        self._active: dict[str, ActiveRun] = {}
        self._lock = threading.Lock()

    # -- configuration -------------------------------------------------
    def configure(self, command: dict[str, Any]) -> None:
        backend_url = str(command.get("backendUrl") or "").strip()
        if backend_url:
            self._api = ApiClient(base_url=backend_url)
        token = command.get("token")
        self._api.set_token(str(token) if token else None)

    def check_ready(self) -> None:
        try:
            ElectronBridge(HitlGate("probe")).check_ready()
            emit({"type": "ready_state", "ok": True, "message": ""})
        except CursorSdkUnavailable as exc:
            emit({"type": "ready_state", "ok": False, "message": _ascii(str(exc))})
        except Exception as exc:  # noqa: BLE001
            emit({"type": "ready_state", "ok": False, "message": _ascii(str(exc))})

    # -- run dispatch --------------------------------------------------
    def start(self, kind: str, command: dict[str, Any]) -> None:
        run_id = str(command.get("id") or uuid.uuid4().hex)
        gate = HitlGate(run_id)
        stop = threading.Event()
        bridge = ElectronBridge(gate)
        active = ActiveRun(run_id=run_id, gate=gate, stop=stop, bridge=bridge)
        with self._lock:
            self._active[run_id] = active
        worker = threading.Thread(
            target=self._run_safe,
            args=(kind, command, active),
            daemon=True,
        )
        active.thread = worker
        worker.start()

    def _run_safe(self, kind: str, command: dict[str, Any], active: ActiveRun) -> None:
        try:
            if kind == "design":
                self._run_design(command, active)
            elif kind == "readiness":
                self._run_readiness(command, active)
            elif kind == "demo":
                self._run_demo(command, active)
            elif kind == "run":
                self._run_agent(command, active)
            elif kind == "check_trigger":
                self._run_trigger(command, active)
            else:
                emit({"type": "error", "runId": active.run_id, "message": f"unknown run kind: {kind}"})
        except CursorSdkUnavailable as exc:
            emit(
                {
                    "type": "error",
                    "runId": active.run_id,
                    "code": "sdk_unavailable",
                    "message": _ascii(str(exc)),
                }
            )
        except ApiError as exc:
            emit({"type": "error", "runId": active.run_id, "message": _ascii(exc.message)})
        except Exception as exc:  # noqa: BLE001
            log("run failed: " + repr(exc))
            log(traceback.format_exc())
            emit({"type": "error", "runId": active.run_id, "message": _ascii(str(exc))})
        finally:
            with self._lock:
                self._active.pop(active.run_id, None)

    def _forward_events(self, active: ActiveRun, events: list[dict[str, Any]]):
        """Build an on_event callback that streams raw runner events."""

        def on_event(payload: dict[str, Any]) -> None:
            if not isinstance(payload, dict):
                return
            event_type = str(payload.get("type") or "")
            if event_type not in {"ready", "done"}:
                events.append(payload)
            # Interactive question/tool_request are handled via HITL gate.
            if event_type in {"question", "tool_request"}:
                return
            emit({"type": "event", "runId": active.run_id, "payload": payload})

        return on_event

    def _run_design(self, command: dict[str, Any], active: ActiveRun) -> None:
        workflow_id = str(command.get("workflowId") or "").strip()
        if not workflow_id:
            raise ValueError("design requires workflowId")
        bridge = active.bridge
        bridge.check_ready()
        record = self._api.get_workflow(workflow_id)
        try:
            design_prompt = self._api.local_design_prompt(workflow_id)
        except ApiError as exc:
            if exc.status_code not in {404, 405}:
                raise
            design_prompt = ""
        run_cwd = bridge.workspace_cwd(workflow_id)
        prepare_sdk_workspace(
            self._api,
            workflow_id,
            run_cwd,
            workflow=record,
            extra_brief=design_prompt,
        )
        events: list[dict[str, Any]] = []
        result = bridge.run(
            prompt=build_design_sdk_prompt(record, design_prompt),
            workflow_id=workflow_id,
            cwd=run_cwd,
            mode="design",
            on_event=self._forward_events(active, events),
            on_question=active.gate.ask_question,
            should_stop=active.stop.is_set,
            confirm_writes=True,
        )
        answer = str(result.get("answer") or "").strip()
        agent_id = str(result.get("agent_id") or "").strip()
        self._store_agent_id(workflow_id, agent_id)
        try:
            self._api.finish_local_design_workflow(
                workflow_id, answer=answer, events=events
            )
        except ApiError as exc:
            if exc.status_code not in {404, 405}:
                raise
        emit(
            {
                "type": "result",
                "runId": active.run_id,
                "kind": "design",
                "workflowId": workflow_id,
                "agentId": agent_id,
                "answer": answer,
            }
        )

    def _run_readiness(self, command: dict[str, Any], active: ActiveRun) -> None:
        draft_id = str(command.get("draftId") or "").strip()
        if not draft_id:
            raise ValueError("readiness requires draftId")
        bridge = active.bridge
        bridge.check_ready()
        draft = self._api.get_agent_draft(draft_id)
        run_cwd = bridge.workspace_cwd(f"draft-{draft_id}")
        _prepare_readiness_workspace(self._api, draft, run_cwd)
        events: list[dict[str, Any]] = []
        result = bridge.run(
            prompt=_build_readiness_prompt(),
            workflow_id=f"draft-{draft_id}",
            cwd=run_cwd,
            mode="design",
            on_event=self._forward_events(active, events),
            on_question=active.gate.ask_question,
            should_stop=active.stop.is_set,
            confirm_writes=True,
        )
        answer = str(result.get("answer") or "").strip()
        updated = self._api.finish_sdk_readiness(draft_id, answer=answer, events=events)
        emit(
            {
                "type": "result",
                "runId": active.run_id,
                "kind": "readiness",
                "draftId": draft_id,
                "status": updated.status,
                "answer": answer,
            }
        )

    def _run_demo(self, command: dict[str, Any], active: ActiveRun) -> None:
        workflow_id = str(command.get("workflowId") or "").strip()
        if not workflow_id:
            raise ValueError("demo requires workflowId")
        bridge = active.bridge
        bridge.check_ready()
        record = self._api.get_workflow(workflow_id)
        resume_agent_id = str((record.local_run or {}).get("sdk_agent_id") or "").strip()
        run_cwd = bridge.workspace_cwd(workflow_id)
        prepare_sdk_workspace(self._api, workflow_id, run_cwd, workflow=record)
        events: list[dict[str, Any]] = []
        result = bridge.run(
            prompt=build_demo_sdk_prompt(record, resume=bool(resume_agent_id)),
            workflow_id=workflow_id,
            cwd=run_cwd,
            resume_agent_id=resume_agent_id,
            on_event=self._forward_events(active, events),
            on_question=active.gate.ask_question,
            should_stop=active.stop.is_set,
            confirm_writes=True,
        )
        answer = str(result.get("answer") or "").strip()
        agent_id = str(result.get("agent_id") or resume_agent_id).strip()
        self._store_agent_id(workflow_id, agent_id)
        try:
            self._api.finish_local_demo_workflow(
                workflow_id, answer=answer, events=events
            )
        except ApiError as exc:
            if exc.status_code not in {404, 405}:
                raise
        emit(
            {
                "type": "result",
                "runId": active.run_id,
                "kind": "demo",
                "workflowId": workflow_id,
                "agentId": agent_id,
                "answer": answer,
            }
        )

    def _run_agent(self, command: dict[str, Any], active: ActiveRun) -> None:
        workflow_id = str(command.get("workflowId") or "").strip()
        if not workflow_id:
            raise ValueError("run requires workflowId")
        message = str(command.get("message") or "").strip()
        source = str(command.get("source") or "chat").strip() or "chat"
        # Trigger/scheduled runs are headless: there is no UI to approve writes,
        # so they run autonomously like the desktop HeadlessRunner.
        autonomous = source == "trigger"
        trigger_id = str(command.get("triggerId") or "").strip()
        evidence = str(command.get("evidence") or "").strip()
        resume_agent_id = str(command.get("resumeAgentId") or "").strip()
        bridge = active.bridge
        bridge.check_ready()
        workflow = self._api.get_workflow(workflow_id)
        if not resume_agent_id:
            resume_agent_id = str((workflow.local_run or {}).get("sdk_agent_id") or "").strip()
        run_record = self._api.start_local_agent_run(
            workflow_id,
            message=message,
            source=source,
            trigger_id=trigger_id,
            evidence=evidence,
        )
        run_ref = getattr(run_record, "id", "") or getattr(run_record, "run_id", "")
        emit({"type": "event", "runId": active.run_id, "payload": {"type": "run", "run_id": run_ref}})
        run_cwd = bridge.workspace_cwd(workflow_id)
        prepare_sdk_workspace(self._api, workflow_id, run_cwd, workflow=workflow)
        events: list[dict[str, Any]] = []
        prompt = (
            build_followup_sdk_prompt(message)
            if resume_agent_id and message
            else build_sdk_prompt(workflow, message)
        )
        status = "ok"
        answer = ""
        try:
            result = bridge.run(
                prompt=prompt,
                workflow_id=workflow_id,
                cwd=run_cwd,
                resume_agent_id=resume_agent_id,
                on_event=self._forward_events(active, events),
                on_question=active.gate.ask_question,
                should_stop=active.stop.is_set,
                confirm_writes=not autonomous,
            )
            answer = str(result.get("answer") or "").strip()
            agent_id = str(result.get("agent_id") or resume_agent_id).strip()
            self._store_agent_id(workflow_id, agent_id)
        except Exception as exc:  # noqa: BLE001
            status = "error"
            answer = str(exc)
            try:
                self._api.finish_local_agent_run(
                    workflow_id, run_ref, status="error", answer=answer,
                    events=events, message=message,
                )
            except ApiError:
                pass
            raise
        self._api.finish_local_agent_run(
            workflow_id, run_ref, status=status, answer=answer,
            events=events, message=message,
        )
        emit(
            {
                "type": "result",
                "runId": active.run_id,
                "kind": "run",
                "workflowId": workflow_id,
                "runRef": run_ref,
                "status": status,
                "answer": answer,
            }
        )

    def _run_trigger(self, command: dict[str, Any], active: ActiveRun) -> None:
        trigger_id = str(command.get("triggerId") or "").strip()
        if not trigger_id:
            raise ValueError("check_trigger requires triggerId")

        def on_check(payload: dict[str, Any]) -> None:
            emit({"type": "event", "runId": active.run_id, "payload": payload})

        check = self._api.stream_trigger_check(trigger_id, on_check)
        fired = bool(check.get("matched") or check.get("fired"))
        workflow_id = str(
            command.get("workflowId") or check.get("workflow_id") or ""
        ).strip()
        evidence = str(check.get("changed") or check.get("evidence") or "")
        emit(
            {
                "type": "event",
                "runId": active.run_id,
                "payload": {
                    "type": "decision",
                    "text": "Trigger fired" if fired else "Trigger condition not met",
                },
            }
        )
        if not fired:
            emit(
                {
                    "type": "result",
                    "runId": active.run_id,
                    "kind": "trigger",
                    "fired": False,
                    "workflowId": workflow_id,
                }
            )
            return
        try:
            self._api.ack_trigger_fired(trigger_id, evidence=evidence)
        except ApiError:
            pass
        self._run_agent(
            {
                "id": active.run_id,
                "workflowId": workflow_id,
                "message": str(command.get("message") or check.get("message") or ""),
                "source": "trigger",
                "triggerId": trigger_id,
                "evidence": evidence,
            },
            active,
        )

    def _store_agent_id(self, workflow_id: str, agent_id: str) -> None:
        if not agent_id:
            return
        try:
            record = self._api.get_workflow(workflow_id)
            local = dict(record.local_run or {})
            if local.get("sdk_agent_id") == agent_id:
                return
            local["sdk_agent_id"] = agent_id
            self._api.update_workflow_local_run(workflow_id, local)
        except ApiError:
            pass

    # -- responses -----------------------------------------------------
    def answer(self, command: dict[str, Any]) -> None:
        request_id = str(command.get("requestId") or "")
        reply = {
            "ok": bool(command.get("ok", True)),
            "answer": str(command.get("answer") or command.get("text") or ""),
        }
        for active in list(self._active.values()):
            active.gate.resolve_answer(request_id, reply)

    def hitl(self, command: dict[str, Any]) -> None:
        request_id = str(command.get("requestId") or "")
        approved = bool(command.get("approved"))
        for active in list(self._active.values()):
            active.gate.resolve_hitl(request_id, approved)

    def skip(self, command: dict[str, Any]) -> None:
        request_id = str(command.get("requestId") or "")
        for active in list(self._active.values()):
            try:
                active.bridge.skip_tool(request_id)
            except Exception:  # noqa: BLE001
                pass

    def cancel(self, command: dict[str, Any]) -> None:
        run_id = str(command.get("id") or "")
        for active in list(self._active.values()):
            if not run_id or active.run_id == run_id:
                active.stop.set()


class ActiveRun:
    def __init__(
        self,
        run_id: str,
        gate: HitlGate,
        stop: threading.Event,
        bridge: ElectronBridge,
    ) -> None:
        self.run_id = run_id
        self.gate = gate
        self.stop = stop
        self.bridge = bridge
        self.thread: threading.Thread | None = None


def _ascii(text: str) -> str:
    return (text or "").encode("ascii", errors="replace").decode("ascii")


def main() -> None:
    sidecar = Sidecar()
    emit({"type": "ready"})
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            command = json.loads(line)
        except json.JSONDecodeError:
            log("bad json command: " + _ascii(line[:200]))
            continue
        if not isinstance(command, dict):
            continue
        ctype = str(command.get("type") or "")
        try:
            if ctype == "configure":
                sidecar.configure(command)
            elif ctype == "check_ready":
                sidecar.check_ready()
            elif ctype in {"design", "demo", "run", "check_trigger"}:
                sidecar.start(ctype, command)
            elif ctype == "answer":
                sidecar.answer(command)
            elif ctype == "hitl":
                sidecar.hitl(command)
            elif ctype == "skip":
                sidecar.skip(command)
            elif ctype == "cancel":
                sidecar.cancel(command)
            elif ctype == "shutdown":
                break
            else:
                log("unknown command type: " + _ascii(ctype))
        except Exception as exc:  # noqa: BLE001
            log("command failed: " + repr(exc))
            log(traceback.format_exc())


if __name__ == "__main__":
    main()
