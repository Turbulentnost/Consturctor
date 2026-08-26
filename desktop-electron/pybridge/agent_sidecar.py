"""Constructor Electron agent sidecar.

A long-lived process that bridges the Electron main process and the local
Cursor SDK. It reuses the existing desktop code (CursorSdkBridge, ApiClient,
sdk_agent, tools) without modifying it, so the Electron UI gets full parity:
real local Cursor SDK runs, local tool execution (1C/Outlook/Excel/...),
askQuestion clarify and HITL write approvals.

Protocol: newline-delimited JSON.
  stdin  (from Electron):
    {"type": "configure", "backendUrl": str, "token": str,
       "login": str, "password": str}
    {"type": "check_ready"}
    {"type": "design", "id": str, "workflowId": str}
    {"type": "readiness", "id": str, "draftId": str}
    {"type": "demo", "id": str, "workflowId": str}
    {"type": "run", "id": str, "workflowId": str, "message": str,
       "source": str, "triggerId": str, "resumeAgentId": str,
       "filePaths": [str, ...]}
    {"type": "check_trigger", "id": str, "triggerId": str}
    {"type": "answer", "requestId": str, "ok": bool, "answer": str,
       "filePaths": [str, ...]}
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
import os
import queue
import sys
import threading
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
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
from app.sdk_agent.files import _safe_filename, prepare_sdk_workspace  # noqa: E402
from app.tools.runtime_api import configure as configure_runtime_api  # noqa: E402
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
        self.qa_history: list[dict[str, str]] = []
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
        # Runner emits a dedicated "question" event, then tool_request with
        # raw arguments. Parse both shapes the same way as desktop runner.
        question, options = _question_from_payload(payload)
        box: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._lock:
            self._answers[request_id] = box
        emit(
            {
                "type": "question",
                "runId": self._run_id,
                "requestId": request_id,
                "question": question,
                "options": options,
            }
        )
        try:
            reply = box.get()
        finally:
            with self._lock:
                self._answers.pop(request_id, None)
        answer = str(reply.get("answer") or reply.get("text") or "").strip()
        ok = bool(reply.get("ok", True)) and bool(answer)
        if question or answer:
            self.qa_history.append({"question": question, "answer": answer})
        return {"ok": ok, "answer": answer, "text": answer}

    def resolve_answer(self, request_id: str, reply: dict[str, Any]) -> None:
        with self._lock:
            box = self._answers.get(request_id)
        if box is not None:
            try:
                box.put_nowait(reply)
            except queue.Full:
                pass


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        for key in ("label", "text", "value", "question", "title"):
            text = _as_text(value.get(key))
            if text:
                return text
    return ""


def _as_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {}
            if isinstance(parsed, dict):
                return parsed
    return {}


def _as_options(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [item for item in (_as_text(part) for part in raw) if item][:6]
    if isinstance(raw, str):
        found: list[str] = []
        for line in raw.replace(";", "\n").splitlines():
            cleaned = line.strip()
            if cleaned[:1] in {"-", "*", "•"}:
                cleaned = cleaned[1:].strip()
            if cleaned:
                found.append(cleaned)
        return found[:6]
    return []


def _options_from_text(text: str) -> list[str]:
    found: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line[:1] in {"-", "*", "•"}:
            value = line[1:].strip()
        elif len(line) > 2 and line[1] in {")", ".", ":"} and line[0].isalnum():
            value = line[2:].strip()
        else:
            continue
        if value and not value.endswith("?"):
            found.append(value)
        if len(found) >= 6:
            break
    return found


def _question_from_payload(payload: dict[str, Any]) -> tuple[str, list[str]]:
    args = _as_record(payload.get("arguments"))
    nested = _as_record(args.get("arguments") or args.get("input") or args.get("properties"))
    source = {**nested, **args}
    question = (
        _as_text(payload.get("question"))
        or _as_text(payload.get("prompt"))
        or _as_text(payload.get("title"))
        or _as_text(payload.get("message"))
        or _as_text(payload.get("text"))
        or _as_text(source.get("question"))
        or _as_text(source.get("prompt"))
        or _as_text(source.get("title"))
        or _as_text(source.get("message"))
        or _as_text(source.get("text"))
    )
    options = _as_options(payload.get("options"))
    if not options:
        options = _as_options(source.get("options"))
    if not options:
        options = _as_options(source.get("choices"))
    if not options:
        options = _as_options(source.get("answers"))
    if not options:
        options = _as_options(source.get("variants"))
    if not options and question:
        options = _options_from_text(question)
    return question, options


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
- всегда передай 2-6 конкретных вариантов ответа в options;
- не вызывай askQuestion без options;
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
        "В каждом askQuestion передай 2-6 конкретных вариантов в options. "
        "Когда все пробелы закрыты, верни JSON readiness и остановись."
    )


RUN_JOURNAL_RELATIVE = "materials/run_journal.md"


def _run_journal_path(cwd: str) -> Path:
    root = Path(cwd).resolve()
    target = (root / RUN_JOURNAL_RELATIVE).resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"refusing to write outside workspace: {RUN_JOURNAL_RELATIVE}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _with_run_journal_prompt(prompt: str, cwd: str) -> str:
    if not _run_journal_path(cwd).is_file():
        return prompt
    hint = "Read materials/run_journal.md before acting; use it as the prior run route."
    return f"{hint}\n\n{prompt}"


def _append_run_journal(
    cwd: str,
    *,
    message: str,
    answer: str,
    events: list[dict[str, Any]],
    qa_history: list[dict[str, str]],
    status: str,
    run_ref: str,
) -> None:
    path = _run_journal_path(cwd)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    parts = []
    if not existing.strip():
        parts.extend(
            [
                "# Журнал запусков агента",
                "",
                "Этот файл читает Cursor SDK агент перед следующими запусками.",
                "Используй его как маршрут уже согласованной работы, не начинай с нуля.",
                "",
            ]
        )
    parts.extend(
        [
            f"## Запуск {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"- runId: {run_ref or 'local'}",
            f"- status: {status or 'ok'}",
            "",
            "### Задача пользователя",
            (message or "(пусто)").strip(),
            "",
        ]
    )
    questions = _journal_questions(events, qa_history)
    if questions:
        parts.extend(["### Вопросы и ответы", *questions, ""])
    agent_lines = _journal_agent_messages(events)
    if agent_lines:
        parts.extend(["### Что писал агент", *agent_lines, ""])
    tools = _journal_tools(events)
    if tools:
        parts.extend(["### Инструменты", *tools, ""])
    parts.extend(["### Итог", (answer or "(нет ответа)").strip(), ""])
    body = "\n".join(parts).rstrip() + "\n"
    prefix = existing.rstrip() + "\n\n" if existing.strip() else ""
    path.write_text(prefix + body, encoding="utf-8")


def _journal_questions(events: list[dict[str, Any]], qa_history: list[dict[str, str]]) -> list[str]:
    out: list[str] = []
    for item in qa_history:
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if question or answer:
            out.append(f"- Вопрос: {question or '(без текста)'}\n  Ответ: {answer or '(нет ответа)'}")
    pending = ""
    for event in events:
        event_type = str(event.get("type") or "")
        if event_type in {"question", "tool_request"}:
            question = str(event.get("question") or event.get("text") or "").strip()
            args = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
            if not question and isinstance(args, dict):
                question = str(args.get("question") or args.get("text") or "").strip()
            if question:
                pending = question
        elif event_type in {"tool_result", "question_answer"}:
            result = event.get("result")
            answer = ""
            if isinstance(result, dict):
                answer = str(result.get("answer") or result.get("text") or "").strip()
            if not answer:
                answer = str(event.get("answer") or event.get("text") or "").strip()
            if pending and answer:
                out.append(f"- Вопрос: {pending}\n  Ответ: {answer}")
                pending = ""
    return out


def _journal_agent_messages(events: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for event in events:
        if str(event.get("type") or "") not in {"assistant", "agent_message", "final", "work_result"}:
            continue
        text = str(event.get("text") or event.get("message") or "").strip()
        if text:
            lines.append(f"- {text[:2000]}")
    return lines


def _journal_tools(events: list[dict[str, Any]]) -> list[str]:
    tools: list[str] = []
    seen: set[str] = set()
    for event in events:
        if str(event.get("type") or "") not in {"tool_call", "tool_result", "tool_request"}:
            continue
        tool = str(event.get("tool") or event.get("name") or "").strip()
        if not tool or tool in seen:
            continue
        seen.add(tool)
        tools.append(f"- {tool}")
    return tools


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
        token = str(command.get("token") or "").strip() or None
        self._api.set_token(token)
        # Server-side tools (users.current, 1C tasks, ...) read this process-global
        # token. Without it they fail with "no user session" even if the UI is logged in.
        configure_runtime_api(token=token, base_url=self._api.base_url)
        # COM 1C workers read ERP_LOGIN / ERP_PASSWORD from the process env.
        login = str(command.get("login") or "").strip()
        password = str(command.get("password") or "")
        if login:
            os.environ["ERP_LOGIN"] = login
        if password:
            os.environ["ERP_PASSWORD"] = password
        elif "password" in command:
            os.environ.pop("ERP_PASSWORD", None)

    def check_ready(self) -> None:
        try:
            ElectronBridge(HitlGate("probe")).check_ready()
            emit({"type": "ready_state", "ok": True, "message": ""})
        except CursorSdkUnavailable as exc:
            emit({"type": "ready_state", "ok": False, "message": _ascii(str(exc))})
        except Exception as exc:  # noqa: BLE001
            emit({"type": "ready_state", "ok": False, "message": _ascii(str(exc))})

    # -- run dispatch --------------------------------------------------
    @staticmethod
    def _dedup_key(kind: str, command: dict[str, Any]) -> str:
        """Identity of a run so duplicate starts can be collapsed.

        StrictMode double-invoke, double clicks or a resume racing a still
        active run would otherwise spawn two SDK subprocesses that write to the
        same local SDK SQLite at once and fail with "database is locked".
        """
        target = str(
            command.get("workflowId")
            or command.get("draftId")
            or command.get("triggerId")
            or ""
        ).strip()
        return f"{kind}:{target}" if target else ""

    def start(self, kind: str, command: dict[str, Any]) -> None:
        run_id = str(command.get("id") or uuid.uuid4().hex)
        dedup_key = self._dedup_key(kind, command)
        with self._lock:
            if dedup_key:
                for existing in self._active.values():
                    if existing.dedup_key == dedup_key:
                        log(
                            "skip duplicate run: "
                            + _ascii(f"{dedup_key} (active run {existing.run_id})")
                        )
                        emit(
                            {
                                "type": "event",
                                "runId": existing.run_id,
                                "payload": {
                                    "type": "status",
                                    "text": "Продолжаю текущий запуск агента.",
                                },
                            }
                        )
                        return
            gate = HitlGate(run_id)
            stop = threading.Event()
            bridge = ElectronBridge(gate)
            active = ActiveRun(run_id=run_id, gate=gate, stop=stop, bridge=bridge)
            active.dedup_key = dedup_key
            self._active[run_id] = active
        emit(
            {
                "type": "event",
                "runId": run_id,
                "payload": {"type": "status", "text": f"Запускаю агента ({kind})."},
            }
        )
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
        active.run_cwd = run_cwd
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
        active.run_cwd = run_cwd
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
        active.run_cwd = run_cwd
        prepare_sdk_workspace(self._api, workflow_id, run_cwd, workflow=workflow)
        file_paths = [str(p) for p in (command.get("filePaths") or []) if str(p).strip()]
        attachment_paths = _copy_attachments(run_cwd, file_paths)
        events: list[dict[str, Any]] = []
        prompt = (
            build_followup_sdk_prompt(message)
            if resume_agent_id and message
            else build_sdk_prompt(workflow, message)
        )
        note = _attachments_note(attachment_paths)
        if note:
            prompt = prompt + "\n\n" + note
        prompt = _with_run_journal_prompt(prompt, run_cwd)
        status = "ok"
        answer = ""
        agent_id = resume_agent_id
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
            try:
                _append_run_journal(
                    run_cwd,
                    message=message,
                    answer=answer,
                    events=events,
                    qa_history=active.gate.qa_history,
                    status=status,
                    run_ref=run_ref,
                )
            except Exception as journal_exc:  # noqa: BLE001
                log("run journal write failed: " + repr(journal_exc))
            raise
        self._api.finish_local_agent_run(
            workflow_id, run_ref, status=status, answer=answer,
            events=events, message=message,
        )
        try:
            _append_run_journal(
                run_cwd,
                message=message,
                answer=answer,
                events=events,
                qa_history=active.gate.qa_history,
                status=status,
                run_ref=run_ref,
            )
        except Exception as exc:  # noqa: BLE001
            log("run journal write failed: " + repr(exc))
        emit(
            {
                "type": "result",
                "runId": active.run_id,
                "kind": "run",
                "workflowId": workflow_id,
                "runRef": run_ref,
                "agentId": agent_id,
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
        answer_text = str(command.get("answer") or command.get("text") or "")
        file_paths = [str(p) for p in (command.get("filePaths") or []) if str(p).strip()]
        for active in list(self._active.values()):
            note = ""
            if file_paths and active.run_cwd:
                note = _attachments_note(_copy_attachments(active.run_cwd, file_paths))
            reply = {
                "ok": bool(command.get("ok", True)),
                "answer": answer_text + (("\n\n" + note) if note else ""),
            }
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
        self.run_cwd: str = ""
        self.dedup_key: str = ""


def _ascii(text: str) -> str:
    return (text or "").encode("ascii", errors="replace").decode("ascii")


def _copy_attachments(run_cwd: str, file_paths: list[str]) -> list[str]:
    """Copy user-attached files into materials/attachments of the run cwd.

    Returns the list of workspace-relative posix paths so the SDK agent can
    read them (mirrors how seed_workflow_files stages persistent documents).
    """
    cwd = (run_cwd or "").strip()
    if not cwd or not file_paths:
        return []
    root = Path(cwd)
    attachments = root / "materials" / "attachments"
    attachments.mkdir(parents=True, exist_ok=True)
    existing = sum(1 for _ in attachments.glob("*") if _.is_file())
    relative: list[str] = []
    index = existing
    for source in file_paths:
        src = Path(str(source or "").strip())
        if not src.is_file():
            log("attachment not found: " + _ascii(str(source)))
            continue
        index += 1
        filename = _safe_filename(src.name or f"file-{index}")
        target = attachments / f"{index:03d}_{filename}"
        try:
            target.write_bytes(src.read_bytes())
        except Exception as exc:  # noqa: BLE001
            log("attachment copy failed: " + repr(exc))
            continue
        relative.append(target.relative_to(root).as_posix())
    return relative


def _attachments_note(relative_paths: list[str]) -> str:
    if not relative_paths:
        return ""
    listing = ", ".join(relative_paths)
    return (
        "Прикреплённые файлы (прочитай их из рабочей области): "
        + listing
    )


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
        log("command: " + _ascii(ctype))
        try:
            if ctype == "configure":
                sidecar.configure(command)
            elif ctype == "check_ready":
                sidecar.check_ready()
            elif ctype in {"design", "readiness", "demo", "run", "check_trigger"}:
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
                emit(
                    {
                        "type": "error",
                        "runId": str(command.get("id") or ""),
                        "message": "unknown command type: " + _ascii(ctype),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            log("command failed: " + repr(exc))
            log(traceback.format_exc())


if __name__ == "__main__":
    main()
