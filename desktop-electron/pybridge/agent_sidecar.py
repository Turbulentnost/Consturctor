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
import re
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
from app.sdk_agent.files import (  # noqa: E402
    _safe_filename,
    prepare_sdk_workspace,
    seed_workflow_files,
)
from app.tools.runtime_api import configure as configure_runtime_api  # noqa: E402
from app.sdk_agent.prompt import (  # noqa: E402
    build_demo_sdk_prompt,
    build_design_sdk_prompt,
    build_followup_sdk_prompt,
    build_sdk_prompt,
)
from app.sdk_agent.tool_adapter import sdk_tool_specs  # noqa: E402

# HITL classification replicated from app.tools.hitl.needs_confirmation.
# We do NOT import that module because it pulls in PySide6/Qt at import time,
# which is not needed (and not always available) for a headless sidecar.
# Level-1 autonomy: read tools auto-run, write tools need confirmation.
_NEVER_CONFIRM = frozenset(
    {"notify.send", "notify", "code.write_python", "code.run_python"}
)
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


def _stamp_run_event(
    message: dict[str, Any],
    *,
    workflow_id: str = "",
    kind: str = "",
) -> dict[str, Any]:
    """Copy workflowId/kind onto a sidecar event so the UI can attach a live feed."""
    out = dict(message)
    wf = (workflow_id or "").strip()
    if wf and not out.get("workflowId"):
        out["workflowId"] = wf
    folded = (kind or "").strip()
    if folded == "run" and not out.get("kind"):
        out["kind"] = "run"
    return out


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


KEEP_KNOWLEDGE_FILE_NAME = "keepKnowledgeFile"
KEEP_KNOWLEDGE_FILE_SPEC: dict[str, Any] = {
    "name": KEEP_KNOWLEDGE_FILE_NAME,
    "description": (
        "Polozhit fayl iz workspace v dolgosrochnuyu (permanent) bazu znaniy agenta. "
        "Call ONLY for a stable reusable document that is identical on every later run "
        "(regulation table, fixed catalog, standing schedule). "
        "Do NOT call for a per-run input the user attaches this run (for example a yearly "
        "meetings file that changes each run), a one-off example, screenshot, or one-time dump. "
        "Per-run inputs stay temporary automatically; keep only what should be reused as-is."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative or absolute path inside cwd",
            },
            "reason": {
                "type": "string",
                "description": "Why this file is needed on later runs",
            },
        },
        "required": ["path"],
    },
}

KEEP_FILE_HINT = (
    "Files in materials/attachments are per-run inputs: read them now, they are already "
    "stored as temporary for this run only. "
    "Call keepKnowledgeFile ONLY for a stable document that is identical and reusable on "
    "every later run (fixed catalog, regulation table, standing schedule). "
    "Do not keep a per-run input that changes each run (for example a yearly meetings file "
    "the user attaches each time), an example, screenshot, or one-time dump."
)

# Distinctive phrase so the rule is appended once to playbook / agent.md.
OUTLOOK_SERIES_MARKER = "самый ранний удобный свободный день"

OUTLOOK_MEETING_HINT = (
    "If the task is to schedule planned meetings in Outlook, do not stop after reading. "
    "Call outlook.read_calendar (free_slots) first, then outlook.create_event. "
    "Writing the calendar is the result; a plan in chat is not. "
    "Weekly or monthly meeting without a date: pick the earliest convenient free weekday "
    "(prefer Monday if free). Keep that same weekday every week; for monthly keep the "
    "same weekday pattern (for example the first Monday). "
    "outlook.create_event has no recurrence field: pass events[] with one item per "
    "occurrence (about 8 weeks weekly, 6 months monthly). "
    "Wait for HITL approval. Done only after create_event returns ok."
)

OUTLOOK_MEETING_RULE = (
    "Плановые совещания записывай в Outlook: сначала outlook.read_calendar "
    "(свободные слоты), затем outlook.create_event. Не ограничивайся чтением календаря. "
    "Если совещание еженедельное или ежемесячное, а конкретная дата не задана: выбери "
    "самый ранний удобный свободный день (предпочтительно понедельник, если он свободен). "
    "Дальше всегда этот же день недели: каждую неделю в один и тот же день; каждый месяц "
    "тот же день недели (например первый понедельник). "
    "Повторяемости в outlook.create_event нет: передай events[] — отдельную встречу "
    "на каждую дату серии (около 8 недель для еженедельных, 6 месяцев для ежемесячных). "
    "Дождись подтверждения записи. Задача выполнена только после ok от create_event."
)

_MEETING_TIPS = (
    "outlook",
    "календар",
    "совещан",
    "встреч",
    "планерк",
    "create_event",
)


def _is_keep_knowledge_file(name: str) -> bool:
    folded = (name or "").strip().casefold()
    return folded in {"keepknowledgefile", "keep_knowledge_file"}


WHEN_TO_RUN_QUESTION = "Когда запускать этого агента?"
WHEN_TO_RUN_OPTIONS = [
    "только вручную из чата",
    "каждый час",
    "раз в день",
    "при конкретном событии — напишу каком",
]
WHEN_TO_RUN_WHY = (
    "Это расписание запуска агента, не расписание совещаний в Outlook. "
    "Без ответа агент после публикации не стартует сам."
)
WHEN_TO_RUN_HINT = (
    "Always ask via askQuestion: when to run THIS agent. "
    "Options: only from chat; every hour; once a day; on an event I will name. "
    "Outlook meeting cadence (weekly or monthly plannerka) is not the agent trigger. "
    "Write the answer to when_to_run. Do not skip this question."
)
_WHEN_TO_RUN_HINTS = (
    "когда запуска",
    "как часто",
    "по расписан",
    "только вручн",
    WHEN_TO_RUN_QUESTION.casefold(),
)
_AGENT_WHEN_LABELS = (
    "когда запускать",
    "расписание агента",
    "запуск агента",
    "триггер агента",
)

RUN_INPUTS_QUESTION = (
    "Нужен ли этому агенту файл, который пользователь будет прикладывать при каждом запуске?"
)
RUN_INPUTS_YES = "Да — сейчас прикреплю образец, чтобы проанализировать"
RUN_INPUTS_NO = "Нет — все данные агент берёт из систем"
RUN_INPUTS_SAMPLE_QUESTION = "Прикрепите образец временного файла"
RUN_INPUTS_WHY = (
    "Если агенту на каждый запуск нужен свежий файл пользователя, образец "
    "нужен сейчас: проектировщик прочитает его и задаст уточнения. "
    "Файл временный, в базу знаний не попадает."
)
RUN_INPUTS_HINT = (
    "If the future agent needs a user file on EVERY run (a table, export, or "
    "document that changes each time), you MUST call askQuestion with needsFile=true "
    "NOW, then read the sample, then ask follow-up questions about its structure. "
    "Do not invent the file and do not replace a missing user file with another "
    "tool or system. Record confirmed inputs into playbook_draft.run_inputs as "
    "{name, description, accept}. These stay temporary: never keepKnowledgeFile. "
    "If no per-run file is required, leave run_inputs empty."
)
RUN_INPUTS_RUN_HINT = (
    "If playbook.run_inputs lists a required per-run file and it is not already "
    "in materials/attachments, stop and ask via askQuestion with needsFile=true. "
    "Do not substitute another tool or system for a missing user file."
)
_RUN_INPUT_GATE_HINTS = (
    "файл, который пользователь будет прикладывать",
    "прикладывать при каждом запуске",
    RUN_INPUTS_QUESTION.casefold(),
)


def _with_sidecar_prompt(prompt: str, *, mode: str = "run") -> str:
    parts = [KEEP_FILE_HINT, OUTLOOK_MEETING_HINT]
    if (mode or "").strip().casefold() == "design":
        parts.append(WHEN_TO_RUN_HINT)
        parts.append(RUN_INPUTS_HINT)
    else:
        parts.append(RUN_INPUTS_RUN_HINT)
    text = (prompt or "").strip()
    if text:
        parts.append(text)
    return "\n\n".join(parts)


def _with_keep_file_prompt(prompt: str) -> str:
    return _with_sidecar_prompt(prompt)


def _meeting_blob(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts).casefold()


def _is_meeting_text(*parts: Any) -> bool:
    blob = _meeting_blob(*parts)
    return any(tip in blob for tip in _MEETING_TIPS)


def _is_meeting_workflow(record: Any) -> bool:
    parts: list[Any] = [
        getattr(record, "title", "") or "",
        getattr(record, "notes", "") or "",
        getattr(record, "document_text", "") or "",
        getattr(record, "last_result", "") or "",
    ]
    plan = getattr(record, "plan", None)
    if plan is not None:
        parts.extend(
            [
                getattr(plan, "title", "") or "",
                getattr(plan, "goal", "") or "",
            ]
        )
    local = getattr(record, "local_run", None) or {}
    if isinstance(local, dict):
        for key in ("playbook", "playbook_draft"):
            raw = local.get(key)
            if isinstance(raw, dict):
                parts.extend(
                    str(raw.get(item) or "")
                    for item in (
                        "instructions",
                        "name",
                        "expected_result",
                        "when_to_run",
                        "example_run",
                    )
                )
    return _is_meeting_text(*parts)


def _merge_outlook_rule_into_playbook(local_run: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return updated local_run if the series rule was added, else None."""
    local = dict(local_run or {})
    changed = False
    for key in ("playbook", "playbook_draft"):
        raw = local.get(key)
        if not isinstance(raw, dict):
            continue
        current = str(raw.get("instructions") or "").strip()
        if OUTLOOK_SERIES_MARKER in current:
            continue
        updated = dict(raw)
        updated["instructions"] = (
            f"{current}\n\n{OUTLOOK_MEETING_RULE}".strip() if current else OUTLOOK_MEETING_RULE
        )
        local[key] = updated
        changed = True
    return local if changed else None


def _ensure_outlook_rule_in_brief(cwd: str) -> None:
    path = Path(cwd) / "materials" / "agent.md"
    if not cwd or not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if OUTLOOK_SERIES_MARKER in text:
        return
    path.write_text(
        text.rstrip() + "\n\n## Плановые совещания в Outlook\n" + OUTLOOK_MEETING_RULE + "\n",
        encoding="utf-8",
    )


def _is_when_to_run_question(question: str) -> bool:
    folded = (question or "").casefold().replace("ё", "е")
    return bool(folded) and any(hint in folded for hint in _WHEN_TO_RUN_HINTS)


def _labeled_agent_when(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip(" -\t")
        if not stripped:
            continue
        folded = stripped.casefold().replace("ё", "е")
        for label in _AGENT_WHEN_LABELS:
            if not folded.startswith(label):
                continue
            parts = re.split(r"[:\-–]", stripped, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return ""


def _when_to_run_from_local(local: dict[str, Any] | None) -> str:
    data = local if isinstance(local, dict) else {}
    for key in ("playbook", "playbook_draft"):
        raw = data.get(key)
        if isinstance(raw, dict):
            value = str(raw.get("when_to_run") or "").strip()
            if value:
                return value
    for item in data.get("design_answers") or []:
        if not isinstance(item, dict):
            continue
        if _is_when_to_run_question(str(item.get("question") or "")):
            answer = str(item.get("answer") or "").strip()
            if answer:
                return answer
    return ""


def _when_to_run_known(record: Any) -> bool:
    if _when_to_run_from_local(getattr(record, "local_run", None)):
        return True
    blob = "\n".join(
        part
        for part in (
            getattr(record, "notes", "") or "",
            getattr(record, "document_text", "") or "",
            getattr(record, "title", "") or "",
        )
        if str(part or "").strip()
    )
    return bool(_labeled_agent_when(blob))


def _when_to_run_user_answered(record: Any) -> bool:
    """True only if the trigger was genuinely answered or is in materials.

    Unlike _when_to_run_known, an LLM-invented playbook_draft.when_to_run does
    NOT count. Used to decide whether we still owe the user the explicit
    trigger question, so a model that never called askQuestion cannot suppress
    it.
    """
    local = getattr(record, "local_run", None) or {}
    for item in local.get("design_answers") or []:
        if (
            isinstance(item, dict)
            and _is_when_to_run_question(str(item.get("question") or ""))
            and str(item.get("answer") or "").strip()
        ):
            return True
    blob = "\n".join(
        part
        for part in (
            getattr(record, "notes", "") or "",
            getattr(record, "document_text", "") or "",
            getattr(record, "title", "") or "",
        )
        if str(part or "").strip()
    )
    return bool(_labeled_agent_when(blob))


def _merge_when_to_run(local_run: dict[str, Any] | None, answer: str) -> dict[str, Any] | None:
    text = (answer or "").strip()
    if not text:
        return None
    local = dict(local_run or {})
    if _when_to_run_from_local(local) == text:
        return None
    answers = [item for item in (local.get("design_answers") or []) if isinstance(item, dict)]
    if not any(
        _is_when_to_run_question(str(item.get("question") or "")) and str(item.get("answer") or "").strip()
        for item in answers
    ):
        answers.append({"question": WHEN_TO_RUN_QUESTION, "answer": text})
        local["design_answers"] = answers
    for key in ("playbook_draft", "playbook"):
        raw = local.get(key)
        if key == "playbook" and not isinstance(raw, dict):
            continue
        updated = dict(raw) if isinstance(raw, dict) else {}
        updated["when_to_run"] = text
        local[key] = updated
    return local


def _normalize_run_input(item: Any) -> dict[str, str] | None:
    """Normalize a single run_inputs entry into {name, description, accept}."""
    if isinstance(item, str):
        name = item.strip()
        return {"name": name, "description": "", "accept": ""} if name else None
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or item.get("title") or item.get("label") or "").strip()
    if not name:
        return None
    return {
        "name": name,
        "description": str(item.get("description") or item.get("why") or "").strip(),
        "accept": str(item.get("accept") or item.get("extensions") or "").strip(),
    }


def _run_inputs_from_local(local: dict[str, Any] | None) -> list[dict[str, str]]:
    """Return the declared per-run required inputs from playbook/playbook_draft."""
    data = local if isinstance(local, dict) else {}
    for key in ("playbook", "playbook_draft"):
        raw = data.get(key)
        if not isinstance(raw, dict):
            continue
        entries = raw.get("run_inputs")
        if isinstance(entries, list) and entries:
            result: list[dict[str, str]] = []
            seen: set[str] = set()
            for entry in entries:
                normalized = _normalize_run_input(entry)
                if normalized is None:
                    continue
                key_name = normalized["name"].casefold()
                if key_name in seen:
                    continue
                seen.add(key_name)
                result.append(normalized)
            if result:
                return result
    return []


def _is_run_input_gate_question(question: str) -> bool:
    folded = (question or "").casefold().replace("ё", "е")
    return bool(folded) and any(hint in folded for hint in _RUN_INPUT_GATE_HINTS)


def _is_run_input_yes(answer: str) -> bool:
    folded = (answer or "").casefold().replace("ё", "е")
    return folded.startswith("да") or "прикреплю образец" in folded or "проанализ" in folded


def _is_run_input_no(answer: str) -> bool:
    folded = (answer or "").casefold().replace("ё", "е")
    return folded.startswith("нет") or "из систем" in folded


def _run_input_gate_from_local(local: dict[str, Any] | None) -> str:
    data = local if isinstance(local, dict) else {}
    for item in data.get("design_answers") or []:
        if not isinstance(item, dict):
            continue
        if _is_run_input_gate_question(str(item.get("question") or "")):
            answer = str(item.get("answer") or "").strip()
            if answer:
                return answer
    return ""


def _run_inputs_user_answered(record: Any) -> bool:
    """True if the user already closed the design-time file-input gate.

    A yes without a persisted run_inputs list does not count: we still owe
    the sample-file question. An LLM-invented playbook_draft.run_inputs
    without a design_answers gate also does not count.
    """
    local = getattr(record, "local_run", None) or {}
    answer = _run_input_gate_from_local(local)
    if not answer:
        return False
    if _is_run_input_no(answer):
        return True
    return bool(_run_inputs_from_local(local))


def _run_input_from_filename(name: str) -> dict[str, str] | None:
    clean = Path(str(name or "").strip()).name
    clean = re.sub(r"^\d{3}_", "", clean).strip()
    if not clean:
        return None
    suffix = Path(clean).suffix
    return {
        "name": clean,
        "description": "Образец временного файла, приложенный при формировании.",
        "accept": suffix,
    }


def _run_inputs_from_answer(answer: str) -> list[dict[str, str]]:
    """Extract run_inputs specs from a ClarifyCard / attachments note."""
    text = (answer or "").replace("ё", "е").replace("Ё", "Е")
    names: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        spec = _run_input_from_filename(raw.strip().strip(".,;"))
        if spec is None:
            return
        key = spec["name"].casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(spec["name"])

    for match in re.finditer(r"materials/attachments/([^\s,]+)", text):
        _add(match.group(1))
    marker = re.search(
        r"прикрепленн\w*\s+файлы:\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if marker:
        for part in marker.group(1).split(","):
            _add(part)
    result: list[dict[str, str]] = []
    for name in names:
        spec = _run_input_from_filename(name)
        if spec is not None:
            result.append(spec)
    return result


def _merge_run_input_gate(local_run: dict[str, Any] | None, answer: str) -> dict[str, Any] | None:
    """Persist the yes/no file-input answer. Does not write run_inputs."""
    text = (answer or "").strip()
    if not text:
        return None
    local = dict(local_run or {})
    if _run_input_gate_from_local(local) == text:
        return None
    answers = [item for item in (local.get("design_answers") or []) if isinstance(item, dict)]
    if not any(
        _is_run_input_gate_question(str(item.get("question") or ""))
        and str(item.get("answer") or "").strip()
        for item in answers
    ):
        answers.append({"question": RUN_INPUTS_QUESTION, "answer": text})
        local["design_answers"] = answers
        return local
    return None


def _merge_run_inputs(
    local_run: dict[str, Any] | None,
    entries: list[dict[str, str]],
    *,
    gate_answer: str = "",
) -> dict[str, Any] | None:
    specs = [_normalize_run_input(item) for item in entries]
    specs = [item for item in specs if item is not None]
    if not specs and not (gate_answer or "").strip():
        return None
    local = dict(local_run or {})
    changed = False
    if (gate_answer or "").strip():
        gated = _merge_run_input_gate(local, gate_answer)
        if gated is not None:
            local = gated
            changed = True
    if specs:
        current = _run_inputs_from_local(local)
        if [item["name"] for item in current] != [item["name"] for item in specs]:
            for key in ("playbook_draft", "playbook"):
                raw = local.get(key)
                if key == "playbook" and not isinstance(raw, dict):
                    continue
                updated = dict(raw) if isinstance(raw, dict) else {}
                updated["run_inputs"] = specs
                local[key] = updated
            changed = True
    return local if changed else None


class ElectronBridge(CursorSdkBridge):
    """CursorSdkBridge that routes HITL write approvals to Electron.

    The base class only knows how to confirm writes through the Qt UI and
    auto-approves when no QApplication exists. Here we block on an Electron
    round-trip instead, so the desktop-electron UI can show approve/reject.
    """

    def __init__(self, hitl_gate: HitlGate, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._hitl_gate = hitl_gate
        self._knowledge_api: ApiClient | None = None
        self._knowledge_workflow_id = ""
        self._knowledge_cwd = ""
        self._knowledge_run_id = ""

    def bind_knowledge(
        self,
        api: ApiClient | None,
        workflow_id: str,
        cwd: str,
        run_id: str = "",
    ) -> None:
        self._knowledge_api = api
        self._knowledge_workflow_id = (workflow_id or "").strip()
        self._knowledge_cwd = (cwd or "").strip()
        self._knowledge_run_id = (run_id or "").strip()

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
        on_event: Any = None,
        on_question: Any = None,
        should_stop: Any = None,
        confirm_writes: bool = False,
    ) -> dict[str, Any]:
        specs = list(tools) if tools is not None else list(sdk_tool_specs())
        if not any(_is_keep_knowledge_file(str(item.get("name") or "")) for item in specs):
            specs.append(dict(KEEP_KNOWLEDGE_FILE_SPEC))
        if workflow_id:
            self._knowledge_workflow_id = workflow_id
        if cwd:
            self._knowledge_cwd = cwd
        return super().run(
            prompt=_with_sidecar_prompt(prompt, mode=mode),
            workflow_id=workflow_id,
            model=model,
            cwd=cwd,
            mode=mode,
            tools=specs,
            resume_agent_id=resume_agent_id,
            on_event=on_event,
            on_question=on_question,
            should_stop=should_stop,
            confirm_writes=confirm_writes,
        )

    def _handle_tool_request(
        self,
        process: Any,
        payload: dict[str, Any],
        *,
        workflow_id: str,
        cwd: str,
        on_question: Any = None,
        should_stop: Any = None,
        confirm_writes: bool = False,
    ) -> None:
        tool = str(payload.get("tool") or "")
        if _is_keep_knowledge_file(tool):
            request_id = str(payload.get("requestId") or "")
            args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
            result = self._keep_knowledge_file(dict(args), workflow_id=workflow_id, cwd=cwd)
            self._send(
                process,
                {
                    "type": "tool_result",
                    "requestId": request_id,
                    "ok": bool(result.get("ok", True)),
                    "result": result,
                    "error": result.get("error"),
                },
            )
            return
        return super()._handle_tool_request(
            process,
            payload,
            workflow_id=workflow_id,
            cwd=cwd,
            on_question=on_question,
            should_stop=should_stop,
            confirm_writes=confirm_writes,
        )

    def _keep_knowledge_file(
        self,
        args: dict[str, Any],
        *,
        workflow_id: str,
        cwd: str,
    ) -> dict[str, Any]:
        raw = str(args.get("path") or args.get("file") or args.get("filePath") or "").strip()
        reason = str(args.get("reason") or "").strip()
        target = _resolve_workspace_file(cwd or self._knowledge_cwd, raw)
        wf = (workflow_id or self._knowledge_workflow_id).strip()
        if target is None:
            return {"ok": False, "error": "File not found in workspace", "path": raw}
        if self._knowledge_api is None or not wf:
            return {"ok": False, "error": "Workflow is not bound", "path": raw}
        ok = _upload_knowledge_files(
            self._knowledge_api,
            wf,
            cwd or self._knowledge_cwd,
            [str(target)],
            run_id=self._knowledge_run_id,
            origin="keep_knowledge",
        )
        if not ok:
            return {"ok": False, "error": "Failed to save file to knowledge base", "path": raw}
        return {
            "ok": True,
            "kept": True,
            "path": raw,
            "reason": reason,
            "summary": "File saved to the agent knowledge base",
        }

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

    def _after_tool_result(
        self, tool: str, result: dict[str, Any], workflow_id: str
    ) -> None:
        _persist_run_outputs(
            self._knowledge_api,
            workflow_id or self._knowledge_workflow_id,
            self._knowledge_cwd,
            tool=tool,
            result=result if isinstance(result, dict) else {},
            run_id=self._knowledge_run_id,
        )


class HitlGate:
    """Correlates HITL/askQuestion prompts with Electron responses."""

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._workflow_id = ""
        self._kind = ""
        self._hitl: dict[str, queue.Queue[bool]] = {}
        self._answers: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._needs_file: dict[str, bool] = {}
        self.qa_history: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def bind(self, *, workflow_id: str = "", kind: str = "") -> None:
        if workflow_id:
            self._workflow_id = workflow_id
        if kind:
            self._kind = kind

    def request(self, tool: str, args: dict[str, Any]) -> bool:
        request_id = uuid.uuid4().hex
        box: queue.Queue[bool] = queue.Queue(maxsize=1)
        with self._lock:
            self._hitl[request_id] = box
        emit(
            _stamp_run_event(
                {
                    "type": "hitl",
                    "runId": self._run_id,
                    "requestId": request_id,
                    "tool": tool,
                    "arguments": _safe_args(args),
                },
                workflow_id=self._workflow_id,
                kind=self._kind,
            )
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

    def ask_question(
        self,
        payload: dict[str, Any],
        should_stop: Any = None,
    ) -> dict[str, Any]:
        request_id = str(payload.get("requestId") or uuid.uuid4().hex)
        # Runner emits a dedicated "question" event, then tool_request with
        # raw arguments. Parse both shapes the same way as desktop runner.
        question, options = _question_from_payload(payload)
        needs_file, accept = _file_request_from_payload(payload)
        box: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._lock:
            self._answers[request_id] = box
            self._needs_file[request_id] = needs_file
        emit(
            _stamp_run_event(
                {
                    "type": "question",
                    "runId": self._run_id,
                    "requestId": request_id,
                    "question": question,
                    "options": options,
                    "needsFile": needs_file,
                    "accept": accept,
                },
                workflow_id=self._workflow_id,
                kind=self._kind,
            )
        )
        reply: dict[str, Any] = {}
        try:
            while True:
                if should_stop and should_stop():
                    return {"ok": False, "answer": "", "text": ""}
                try:
                    reply = box.get(timeout=0.4)
                    break
                except queue.Empty:
                    continue
        finally:
            with self._lock:
                self._answers.pop(request_id, None)
        answer = str(reply.get("answer") or reply.get("text") or "").strip()
        ok = bool(reply.get("ok", True)) and bool(answer)
        if question or answer:
            self.qa_history.append({"question": question, "answer": answer})
        return {"ok": ok, "answer": answer, "text": answer}

    def consume_needs_file(self, request_id: str) -> bool:
        with self._lock:
            return bool(self._needs_file.pop(request_id, False))

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
    if not options and question and not _file_request_from_payload(payload)[0]:
        options = _options_from_text(question)
    return question, options


_KB_ACCEPT = ("xlsx", "xlsm", "docx")


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes"} or text == "да"


def _accept_extensions(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else [raw] if raw else []
    out: list[str] = []
    for item in items:
        ext = str(item or "").strip().lower().lstrip(".")
        if ext in _KB_ACCEPT and ext not in out:
            out.append(ext)
    return out


def _file_request_from_payload(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    args = _as_record(payload.get("arguments"))
    nested = _as_record(args.get("arguments") or args.get("input") or args.get("properties"))
    source = {**nested, **args, **payload}
    needs = _as_bool(
        source.get("needsFile")
        or source.get("needs_file")
        or source.get("expectFile")
    )
    accept = _accept_extensions(source.get("accept") or source.get("allowedExtensions"))
    if needs and not accept:
        accept = list(_KB_ACCEPT)
    return needs, accept


def _emit_files_updated(workflow_id: str, run_id: str = "") -> None:
    wf = (workflow_id or "").strip()
    if not wf:
        return
    emit({"type": "files_updated", "workflowId": wf, "runId": (run_id or "").strip()})


def _upload_knowledge_files(
    api: ApiClient,
    workflow_id: str,
    run_cwd: str,
    file_paths: list[str],
    run_id: str = "",
    origin: str = "",
) -> bool:
    allowed = [str(path) for path in file_paths if Path(str(path)).is_file()]
    if not (workflow_id.strip() and allowed):
        return False
    try:
        api.upload_workflow_files(workflow_id, allowed, origin=origin)
        if run_cwd.strip():
            seed_workflow_files(api, workflow_id, run_cwd)
        _emit_files_updated(workflow_id, run_id)
        return True
    except Exception as exc:  # noqa: BLE001
        log("knowledge upload failed: " + _ascii(repr(exc)))
        return False


def _upload_run_outputs(
    api: ApiClient,
    workflow_id: str,
    file_paths: list[str],
    run_id: str = "",
) -> bool:
    """Upload documents the agent created so history and Files can show them."""
    allowed = [str(path) for path in file_paths if Path(str(path)).is_file()]
    if not (workflow_id.strip() and allowed):
        return False
    try:
        api.register_workflow_run_files(workflow_id, (run_id or "").strip() or "local", allowed)
        _emit_files_updated(workflow_id, run_id)
        return True
    except Exception as exc:  # noqa: BLE001
        log("run output upload failed: " + _ascii(repr(exc)))
        return False


def _persist_run_outputs(
    api: ApiClient | None,
    workflow_id: str,
    run_cwd: str,
    tool: str = "",
    result: dict[str, Any] | None = None,
    run_id: str = "",
) -> list[str]:
    if api is None or not (workflow_id or "").strip():
        return []
    from app.tools.result_files import (
        collect_output_files_from_dir,
        collect_workspace_output_files,
        extract_result_files,
    )

    found: list[Path] = []
    folded = (tool or "").strip()
    if result is not None:
        found.extend(extract_result_files(result, tool=folded, workflow_id=workflow_id))
    should_sweep = not folded
    if (
        not found
        and isinstance(result, dict)
        and any(result.get(key) for key in ("file", "path", "filename", "result_file", "files"))
    ):
        should_sweep = True
    if should_sweep:
        found.extend(collect_workspace_output_files(workflow_id))
        cwd = Path(run_cwd) if run_cwd else None
        found.extend(collect_output_files_from_dir(cwd))
    paths = [str(path) for path in found if path.is_file()]
    if not paths:
        return []
    _upload_run_outputs(api, workflow_id, paths, run_id=run_id)
    return paths


def _upload_run_attachments(
    api: ApiClient,
    workflow_id: str,
    file_paths: list[str],
    run_id: str = "",
) -> bool:
    """Upload files as temporary per-run attachments (not permanent knowledge)."""
    allowed = [str(path) for path in file_paths if Path(str(path)).is_file()]
    if not (workflow_id.strip() and run_id.strip() and allowed):
        return False
    try:
        api.register_run_attachments(workflow_id, run_id, allowed)
        _emit_files_updated(workflow_id, run_id)
        return True
    except Exception as exc:  # noqa: BLE001
        log("run attachment upload failed: " + _ascii(repr(exc)))
        return False


def _persist_run_attachment(
    api: ApiClient,
    workflow_id: str,
    run_cwd: str,
    file_paths: list[str],
    run_id: str = "",
) -> list[str]:
    """Stage per-run files into the workspace and store them as temporary.

    Files attached mid-run are inputs for THIS run only. They are copied into
    materials/attachments so the SDK agent can read them and uploaded as
    run_attachment (tied to run_id) - never to the permanent knowledge base.
    Only the explicit keepKnowledgeFile tool writes permanent knowledge.
    """
    copied = _copy_attachments(run_cwd, file_paths)
    _upload_run_attachments(api, workflow_id, file_paths, run_id=run_id)
    return copied


def _persist_knowledge_files(
    api: ApiClient,
    workflow_id: str,
    run_cwd: str,
    file_paths: list[str],
    keep: bool = False,
    run_id: str = "",
) -> list[str]:
    copied = _copy_attachments(run_cwd, file_paths)
    if keep:
        _upload_knowledge_files(api, workflow_id, run_cwd, file_paths, run_id=run_id)
    return copied


def _resolve_workspace_file(cwd: str, raw: str) -> Path | None:
    text = (raw or "").strip()
    root = Path((cwd or "").strip()).resolve() if (cwd or "").strip() else None
    if not text:
        return None
    candidate = Path(text)
    if not candidate.is_absolute() and root is not None:
        candidate = (root / text).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.is_file():
        return None
    if root is not None:
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
    return candidate


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


def _is_trigger_command(command: dict[str, Any]) -> bool:
    source = str(command.get("source") or "").strip().lower()
    if source == "trigger":
        return True
    return bool(str(command.get("triggerId") or command.get("trigger_id") or "").strip())


def _sdk_run_alive(active: "ActiveRun") -> bool:
    thread = active.thread
    if thread is None or not thread.is_alive():
        return False
    process = getattr(active.bridge, "_process", None)
    if process is not None and process.poll() is not None:
        return False
    return True


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
        overlap_run_id = ""
        skip_run_id = ""
        with self._lock:
            if dedup_key:
                for existing in list(self._active.values()):
                    if existing.dedup_key != dedup_key:
                        continue
                    if _is_trigger_command(command) and _sdk_run_alive(existing):
                        log(
                            "skip duplicate run: "
                            + _ascii(f"{dedup_key} (active run {existing.run_id})")
                        )
                        overlap_run_id = existing.run_id
                        break
                    if _is_trigger_command(command) and not _sdk_run_alive(existing):
                        log(
                            "replace dead run: "
                            + _ascii(f"{dedup_key} (stale run {existing.run_id})")
                        )
                        self._active.pop(existing.run_id, None)
                        break
                    log(
                        "skip duplicate run: "
                        + _ascii(f"{dedup_key} (active run {existing.run_id})")
                    )
                    skip_run_id = existing.run_id
                    break
            if not overlap_run_id and not skip_run_id:
                gate = HitlGate(run_id)
                stop = threading.Event()
                bridge = ElectronBridge(gate)
                active = ActiveRun(run_id=run_id, gate=gate, stop=stop, bridge=bridge)
                active.dedup_key = dedup_key
                active.kind = kind
                active.workflow_id = str(command.get("workflowId") or "").strip()
                if active.workflow_id:
                    gate.bind(workflow_id=active.workflow_id, kind=kind)
                self._active[run_id] = active
        if overlap_run_id:
            self._cancel_overlap_slot(command)
            emit(
                {
                    "type": "event",
                    "runId": overlap_run_id,
                    "payload": {
                        "type": "status",
                        "text": "Продолжаю текущий запуск агента.",
                    },
                }
            )
            return
        if skip_run_id:
            emit(
                {
                    "type": "event",
                    "runId": skip_run_id,
                    "payload": {
                        "type": "status",
                        "text": "Продолжаю текущий запуск агента.",
                    },
                }
            )
            return
        emit(
            _stamp_run_event(
                {
                    "type": "event",
                    "runId": run_id,
                    "payload": {"type": "status", "text": f"Запускаю агента ({kind})."},
                },
                workflow_id=str(command.get("workflowId") or ""),
                kind=kind,
            )
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
            self._finish_active_history(active, "Cursor SDK не отвечает")
            emit(
                {
                    "type": "error",
                    "runId": active.run_id,
                    "code": "sdk_unavailable",
                    "message": _ascii(str(exc)),
                }
            )
        except ApiError as exc:
            self._finish_active_history(active, "Cursor SDK не отвечает")
            emit({"type": "error", "runId": active.run_id, "message": _ascii(exc.message)})
        except Exception as exc:  # noqa: BLE001
            self._finish_active_history(active, "Cursor SDK не отвечает")
            log("run failed: " + repr(exc))
            log(traceback.format_exc())
            emit({"type": "error", "runId": active.run_id, "message": _ascii(str(exc))})
        finally:
            with self._lock:
                self._active.pop(active.run_id, None)

    def _forward_events(self, active: ActiveRun, events: list[dict[str, Any]]):
        """Build an on_event callback that streams raw runner events."""

        last_flush = 0

        def on_event(payload: dict[str, Any]) -> None:
            nonlocal last_flush
            if not isinstance(payload, dict):
                return
            event_type = str(payload.get("type") or "")
            if event_type not in {"ready", "done"}:
                events.append(payload)
            # Interactive question/tool_request are handled via HITL gate.
            if event_type in {"question", "tool_request"}:
                return
            emit(
                _stamp_run_event(
                    {"type": "event", "runId": active.run_id, "payload": payload},
                    workflow_id=active.workflow_id,
                    kind=active.kind,
                )
            )
            run_ref = (active.history_run_id or "").strip()
            if (
                run_ref
                and active.workflow_id
                and len(events) - last_flush >= 3
            ):
                last_flush = len(events)
                try:
                    self._api.update_local_agent_run_events(
                        active.workflow_id,
                        run_ref,
                        events,
                    )
                except ApiError:
                    pass

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
        active.workflow_id = workflow_id
        prepare_sdk_workspace(
            self._api,
            workflow_id,
            run_cwd,
            workflow=record,
            extra_brief=design_prompt,
        )
        if _is_meeting_workflow(record) or _is_meeting_text(design_prompt):
            _ensure_outlook_rule_in_brief(run_cwd)
        bridge.bind_knowledge(self._api, workflow_id, run_cwd, active.run_id)
        # Ask for a per-run file sample before the designer writes the draft,
        # so the SDK run can read it and ask follow-up questions.
        self._ensure_run_input_sample_asked(active, workflow_id)
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
        self._ensure_outlook_rule_in_playbook(workflow_id)
        self._ensure_when_to_run_asked(active, workflow_id)
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
        active.run_cwd = run_cwd
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
        active.workflow_id = workflow_id
        prepare_sdk_workspace(self._api, workflow_id, run_cwd, workflow=record)
        if _is_meeting_workflow(record):
            _ensure_outlook_rule_in_brief(run_cwd)
        bridge.bind_knowledge(self._api, workflow_id, run_cwd, active.run_id)
        # Trial run is still interactive: ask for a per-run sample if design
        # skipped it, then for each declared run_input. Otherwise the model
        # invents a substitute data source (for example another system).
        self._ensure_run_input_sample_asked(active, workflow_id)
        try:
            record = self._api.get_workflow(workflow_id)
        except ApiError:
            pass
        run_input_notes = self._ensure_run_inputs_provided(active, record, provided_count=0)
        events: list[dict[str, Any]] = []
        prompt = build_demo_sdk_prompt(record, resume=bool(resume_agent_id))
        for extra_note in run_input_notes:
            if extra_note:
                prompt = prompt + "\n\n" + extra_note
        result = bridge.run(
            prompt=prompt,
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
        self._ensure_outlook_rule_in_playbook(workflow_id)
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
        active.workflow_id = workflow_id
        active.kind = "run"
        active.gate.bind(workflow_id=workflow_id, kind="run")
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
        self._fail_unbacked_started(workflow_id, except_run_id=active.run_id)
        run_record = self._api.start_local_agent_run(
            workflow_id,
            message=message,
            source=source,
            trigger_id=trigger_id,
            evidence=evidence,
        )
        run_ref = getattr(run_record, "id", "") or getattr(run_record, "run_id", "")
        active.history_run_id = str(run_ref or "")
        emit(
            _stamp_run_event(
                {
                    "type": "event",
                    "runId": active.run_id,
                    "payload": {"type": "run", "run_id": run_ref},
                },
                workflow_id=workflow_id,
                kind="run",
            )
        )
        run_cwd = bridge.workspace_cwd(workflow_id)
        active.run_cwd = run_cwd
        active.workflow_id = workflow_id
        prepare_sdk_workspace(self._api, workflow_id, run_cwd, workflow=workflow)
        if _is_meeting_workflow(workflow):
            _ensure_outlook_rule_in_brief(run_cwd)
            self._ensure_outlook_rule_in_playbook(workflow_id, record=workflow)
        output_run_id = str(run_ref or active.run_id).strip()
        bridge.bind_knowledge(self._api, workflow_id, run_cwd, output_run_id)
        file_paths = [str(p) for p in (command.get("filePaths") or []) if str(p).strip()]
        # Files attached to a run are inputs for THIS run only: store them as
        # temporary run_attachments, not in the permanent knowledge base.
        attachment_paths = _persist_run_attachment(
            self._api, workflow_id, run_cwd, file_paths, run_id=output_run_id
        )
        # Manual runs: hard-ask for each declared per-run input the user did not
        # already attach. Trigger/autonomous runs have no UI, so we skip them.
        run_input_notes: list[str] = []
        if not autonomous:
            run_input_notes = self._ensure_run_inputs_provided(
                active, workflow, provided_count=len(file_paths)
            )
        events: list[dict[str, Any]] = []
        prompt = (
            build_followup_sdk_prompt(message)
            if resume_agent_id and message
            else build_sdk_prompt(workflow, message)
        )
        note = _attachments_note(attachment_paths)
        if note:
            prompt = prompt + "\n\n" + note
        for extra_note in run_input_notes:
            if extra_note:
                prompt = prompt + "\n\n" + extra_note
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
                active.history_finished = True
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
        active.history_finished = True
        try:
            _persist_run_outputs(
                self._api,
                workflow_id,
                run_cwd,
                run_id=str(run_ref or active.run_id).strip(),
            )
        except Exception as exc:  # noqa: BLE001
            log("run output sweep failed: " + repr(exc))
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
        if workflow_id:
            active.workflow_id = workflow_id
            active.gate.bind(workflow_id=workflow_id)
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

    def _cancel_overlap_slot(self, command: dict[str, Any]) -> None:
        workflow_id = str(command.get("workflowId") or "").strip()
        trigger_id = str(command.get("triggerId") or command.get("trigger_id") or "").strip()
        if not workflow_id or not trigger_id:
            return
        try:
            self._api.cancel_overlapping_slot(
                workflow_id,
                trigger_id,
                answer="Агент уже выполняется",
            )
        except ApiError as exc:
            log("overlap cancel failed: " + _ascii(exc.message))

    def _has_live_workflow(self, workflow_id: str, except_run_id: str = "") -> bool:
        wid = (workflow_id or "").strip()
        skip = (except_run_id or "").strip()
        if not wid:
            return False
        with self._lock:
            for active in self._active.values():
                if active.run_id == skip:
                    continue
                if active.workflow_id != wid:
                    continue
                if _sdk_run_alive(active):
                    return True
        return False

    def _fail_unbacked_started(self, workflow_id: str, *, except_run_id: str = "") -> None:
        if self._has_live_workflow(workflow_id, except_run_id):
            return
        try:
            items = self._api.list_agent_runs(workflow_id)
        except ApiError:
            return
        for item in items:
            if (item.status or "").strip().lower() != "started":
                continue
            try:
                self._api.finish_local_agent_run(
                    workflow_id,
                    item.id,
                    status="error",
                    answer="Cursor SDK не отвечает",
                )
            except ApiError:
                continue

    def _finish_active_history(self, active: ActiveRun, answer: str) -> None:
        if active.history_finished or not active.history_run_id or not active.workflow_id:
            return
        try:
            self._api.finish_local_agent_run(
                active.workflow_id,
                active.history_run_id,
                status="error",
                answer=answer,
            )
            active.history_finished = True
        except ApiError:
            return

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

    def _persist_when_to_run(self, workflow_id: str, answer: str) -> None:
        wid = (workflow_id or "").strip()
        text = (answer or "").strip()
        if not wid or not text:
            return
        try:
            record = self._api.get_workflow(wid)
            merged = _merge_when_to_run(dict(getattr(record, "local_run", None) or {}), text)
            if merged is None:
                return
            self._api.update_workflow_local_run(wid, merged)
        except ApiError:
            pass

    def _ensure_when_to_run_asked(self, active: ActiveRun, workflow_id: str) -> None:
        if active.stop.is_set():
            return
        try:
            record = self._api.get_workflow(workflow_id)
        except ApiError:
            return
        if _when_to_run_user_answered(record):
            return
        reply = active.gate.ask_question(
            {
                "question": WHEN_TO_RUN_QUESTION,
                "options": list(WHEN_TO_RUN_OPTIONS),
                "why": WHEN_TO_RUN_WHY,
            },
            should_stop=active.stop.is_set,
        )
        answer = str(reply.get("answer") or "").strip()
        if not answer or active.stop.is_set():
            return
        self._persist_when_to_run(workflow_id, answer)

    def _persist_run_input_gate(self, workflow_id: str, answer: str) -> None:
        wid = (workflow_id or "").strip()
        text = (answer or "").strip()
        if not wid or not text:
            return
        try:
            record = self._api.get_workflow(wid)
            merged = _merge_run_input_gate(
                dict(getattr(record, "local_run", None) or {}), text
            )
            if merged is None:
                return
            self._api.update_workflow_local_run(wid, merged)
        except ApiError:
            pass

    def _persist_run_inputs(
        self,
        workflow_id: str,
        entries: list[dict[str, str]],
        *,
        gate_answer: str = "",
    ) -> None:
        wid = (workflow_id or "").strip()
        if not wid:
            return
        try:
            record = self._api.get_workflow(wid)
            merged = _merge_run_inputs(
                dict(getattr(record, "local_run", None) or {}),
                entries,
                gate_answer=gate_answer,
            )
            if merged is None:
                return
            self._api.update_workflow_local_run(wid, merged)
        except ApiError:
            pass

    def _ensure_run_input_sample_asked(self, active: ActiveRun, workflow_id: str) -> None:
        if active.stop.is_set():
            return
        try:
            record = self._api.get_workflow(workflow_id)
        except ApiError:
            return
        if _run_inputs_user_answered(record):
            return
        local = dict(getattr(record, "local_run", None) or {})
        gate = _run_input_gate_from_local(local)
        if not gate:
            reply = active.gate.ask_question(
                {
                    "question": RUN_INPUTS_QUESTION,
                    "options": [RUN_INPUTS_YES, RUN_INPUTS_NO],
                    "why": RUN_INPUTS_WHY,
                },
                should_stop=active.stop.is_set,
            )
            gate = str(reply.get("answer") or "").strip()
            if not gate or active.stop.is_set():
                return
            self._persist_run_input_gate(workflow_id, gate)
            if _is_run_input_no(gate):
                return
        sample = active.gate.ask_question(
            {
                "question": RUN_INPUTS_SAMPLE_QUESTION,
                "options": [],
                "needsFile": True,
                "why": (
                    "Образец нужен проектировщику, чтобы прочитать структуру "
                    "и задать уточнения. Файл временный, в базу знаний не попадает."
                ),
            },
            should_stop=active.stop.is_set,
        )
        if active.stop.is_set():
            return
        specs = _run_inputs_from_answer(str(sample.get("answer") or ""))
        if not specs:
            return
        self._persist_run_inputs(workflow_id, specs, gate_answer=gate or RUN_INPUTS_YES)

    def _ensure_run_inputs_provided(
        self,
        active: ActiveRun,
        workflow: Any,
        provided_count: int,
    ) -> list[str]:
        """Ask the user to attach each declared per-run input at manual run start.

        Files come back as temporary run_attachments (handled by answer()).
        Returns note strings that describe the attached files for the SDK prompt.
        Skipped for autonomous/trigger runs, which have no UI to attach files.
        """
        run_inputs = _run_inputs_from_local(dict(getattr(workflow, "local_run", None) or {}))
        if not run_inputs:
            return []
        notes: list[str] = []
        for idx, spec in enumerate(run_inputs):
            if idx < provided_count:
                continue
            if active.stop.is_set():
                break
            name = spec.get("name") or "файл"
            description = spec.get("description") or ""
            accept = spec.get("accept") or ""
            question = "Прикрепите файл для этого запуска: " + name
            if description:
                question = question + ". " + description
            reply = active.gate.ask_question(
                {
                    "question": question,
                    "options": [],
                    "needsFile": True,
                    "accept": accept,
                    "why": (
                        "Это временный файл только для текущего запуска, "
                        "он не сохраняется в базу знаний."
                    ),
                },
                should_stop=active.stop.is_set,
            )
            answer = str(reply.get("answer") or "").strip()
            if answer:
                notes.append(answer)
        return notes

    def _ensure_outlook_rule_in_playbook(
        self,
        workflow_id: str,
        record: Any = None,
    ) -> None:
        wid = (workflow_id or "").strip()
        if not wid:
            return
        try:
            current = record if record is not None else self._api.get_workflow(wid)
            if not _is_meeting_workflow(current):
                return
            merged = _merge_outlook_rule_into_playbook(
                dict(getattr(current, "local_run", None) or {})
            )
            if merged is None:
                return
            self._api.update_workflow_local_run(wid, merged)
        except ApiError:
            pass

    # -- responses -----------------------------------------------------
    def answer(self, command: dict[str, Any]) -> None:
        request_id = str(command.get("requestId") or "")
        answer_text = str(command.get("answer") or command.get("text") or "")
        file_paths = [str(p) for p in (command.get("filePaths") or []) if str(p).strip()]
        for active in list(self._active.values()):
            note = ""
            # A file attached in reply to a mid-run question is an input for
            # THIS run only. Store it as a temporary run_attachment, never in the
            # permanent knowledge base. keepKnowledgeFile is the only permanent path.
            active.gate.consume_needs_file(request_id)
            if file_paths and active.run_cwd:
                note = _attachments_note(
                    _persist_run_attachment(
                        self._api,
                        active.workflow_id,
                        active.run_cwd,
                        file_paths,
                        run_id=active.run_id,
                    )
                )
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

    def shutdown(self) -> None:
        with self._lock:
            actives = list(self._active.values())
            self._active.clear()
        workflows = {active.workflow_id for active in actives if active.workflow_id}
        for active in actives:
            active.stop.set()
            self._finish_active_history(active, "Cursor SDK не отвечает")
        for workflow_id in workflows:
            self._fail_unbacked_started(workflow_id)


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
        self.workflow_id: str = ""
        self.kind: str = ""
        self.dedup_key: str = ""
        self.history_run_id: str = ""
        self.history_finished: bool = False


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
                sidecar.shutdown()
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
