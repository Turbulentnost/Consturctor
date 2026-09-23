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
    {"type": "form_orchestrator", "id": str}
    {"type": "calc_orchestrator", "id": str, "tileIds": [str, ...]}
    {"type": "kpi_module", "id": str, "buildId": str, "workflowId": str,
       "prompt": str, "filePaths": [str, ...]}
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

Diagnostics on stderr use UTF-8 (Electron reads stderr as utf-8).
Protocol on stdout is UTF-8 JSON lines.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _is_orchestrator_desktop(path: Path) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return normalized.endswith("/orchestrator/desktop") or "/orchestrator/orchestrator/desktop" in normalized


def _strip_other_desktop_roots(keep: Path) -> None:
    """Avoid importing app.* from Consturctor/desktop when Orchestrator desktop is intended."""
    keep_resolved = keep.resolve()
    for entry in list(sys.path):
        if not entry:
            continue
        try:
            candidate = Path(entry).resolve()
        except OSError:
            continue
        if candidate == keep_resolved:
            continue
        if (candidate / "app" / "config.py").is_file():
            try:
                sys.path.remove(entry)
            except ValueError:
                pass


def _use_desktop_root(desktop_root: Path) -> Path:
    desktop_root = desktop_root.resolve()
    if not desktop_root.is_dir():
        raise RuntimeError(f"desktop folder not found at {desktop_root}")
    _strip_other_desktop_roots(desktop_root)
    path_str = str(desktop_root)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)
    return desktop_root


def _bootstrap_desktop_path() -> Path:
    """Add the desktop/ folder to sys.path so app.* is importable."""
    env_root = os.environ.get("CONSTRUCTOR_DESKTOP_ROOT", "").strip()
    if env_root:
        return _use_desktop_root(Path(env_root))

    here = Path(__file__).resolve()
    sidecar_is_orchestrator = "orchestrator" in str(here).replace("\\", "/").lower()
    candidates: list[Path] = []
    for parent in here.parents:
        candidates.append(parent / "Consturctor" / "desktop")
        candidates.append(parent / "desktop")
    found = [path for path in candidates if (path / "app" / "config.py").is_file()]
    if sidecar_is_orchestrator:
        orchestrator_desktops = [path for path in found if _is_orchestrator_desktop(path)]
        if orchestrator_desktops:
            return _use_desktop_root(orchestrator_desktops[0])
    for desktop_root in found:
        if (desktop_root / ".env").is_file():
            return _use_desktop_root(desktop_root)
    if found:
        return _use_desktop_root(found[0])
    raise RuntimeError(f"desktop folder not found near {here}")


DESKTOP_ROOT = _bootstrap_desktop_path()
_AC_REGISTRY_LOGGED = False

# Importing app.config loads desktop/.env (ONEC_COM_*, CURSOR_API_KEY, ...).
from app.envfile import load_env_file  # noqa: E402

load_env_file(DESKTOP_ROOT / ".env", override=True)
import app.config as _app_config  # noqa: E402, F401

from app.api_client import ApiClient, ApiError  # noqa: E402
from app.orchestrator.json_blob import extract_json_object  # noqa: E402
from app.sdk_agent.bridge import (  # noqa: E402
    CursorSdkBridge,
    CursorSdkError,
    CursorSdkUnavailable,
    is_transient_cursor_error,
)
from app.sdk_agent.files import (  # noqa: E402
    _safe_filename,
    prepare_sdk_workspace,
    reset_run_scratch,
    seed_workflow_files,
)
from app.tools.runtime_api import configure as configure_runtime_api  # noqa: E402
from app.sdk_agent.prompt import (  # noqa: E402
    build_continue_run_prompt,
    build_demo_sdk_prompt,
    build_design_sdk_prompt,
    build_sdk_prompt,
    text_has_finished_work_result,
)
from app.sdk_agent.kpi_attach import (  # noqa: E402
    KPI_SOURCE_OPTIONS,
    catalog_from_jobs,
    kpi_repair_prompt,
    kpi_write_jobs,
    needs_source_detail,
    parse_kpi_rows,
    unasked_kpi_rows,
    write_kpi_example_files,
)
from app.sdk_agent.tool_adapter import (  # noqa: E402
    sdk_kpi_tool_specs,
    sdk_kpi_write_tool_specs,
    sdk_tool_specs,
)

# HITL classification replicated from app.tools.hitl.needs_confirmation.
# We do NOT import that module because it pulls in PySide6/Qt at import time,
# which is not needed (and not always available) for a headless sidecar.
# Level-1 autonomy: read tools auto-run, write tools need confirmation.
_NEVER_CONFIRM = frozenset(
    {
        "notify.send",
        "notify",
        "code.write_python",
        "code.run_python",
        "report.export_document",
        "office.format_document",
    }
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
        "calendar.show_meetings",
        "excel.list_files",
        "excel.read_workbook",
        "office.read_file",
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.sql_query",
        "onec.erp_assignments",
        "onec.download_artifact",
        "onec.erp_write_probe",
        "onec.erp_tasks_current",
        "onec.erp_tasks_odata",
        "onec.erp_tasks_period",
        "onec.erp_subordinate_tasks",
        "onec.docflow_tasks",
        "onec.meeting_service_notes",
        "onec.meeting_protocols",
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


def _compact_tool_name(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _matches_known_tool(name: str, known: frozenset[str]) -> bool:
    tool = (name or "").strip()
    if tool in known:
        return True
    compact = _compact_tool_name(tool)
    return any(_compact_tool_name(item) == compact for item in known)


def _is_read_tool(name: str) -> bool:
    tool = (name or "").strip()
    if _matches_known_tool(tool, _NEVER_CONFIRM | _READ_EXACT):
        return True
    return any(tool.startswith(prefix) for prefix in _READ_PREFIXES)


_MAX_WORK_CONTINUES = 2


def _text_has_finished_work_result(text: str) -> bool:
    return text_has_finished_work_result(text)


def needs_confirmation(name: str) -> bool:
    tool = (name or "").strip()
    if _matches_known_tool(tool, _NEVER_CONFIRM):
        return False
    return not _is_read_tool(tool)


def _tool_wait_title(tool: str) -> str:
    name = (tool or "").strip()
    if name.startswith("onec."):
        return "Доступ к 1С"
    if name.startswith("excel."):
        return "Действие в Excel"
    if "outlook" in name or name.startswith("email."):
        return "Действие в почте"
    return name or "Действие агента"


_STDOUT_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _with_at(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("at") or "").strip():
        return payload
    out = dict(payload)
    out["at"] = _now_iso()
    return out


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
    if folded in {"run", "eval"} and not out.get("kind"):
        out["kind"] = folded
    return out


def emit(message: dict[str, Any]) -> None:
    """Write one JSON line to stdout for the Electron main process."""
    line = json.dumps(message, ensure_ascii=False, default=_json_default) + "\n"
    payload = line.encode("utf-8")
    with _STDOUT_LOCK:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(payload)
            buffer.flush()
        else:
            sys.stdout.write(line)
            sys.stdout.flush()


def log(message: str) -> None:
    """UTF-8 diagnostic to stderr (never stdout, which is the protocol)."""
    line = str(message) + "\n"
    payload = line.encode("utf-8")
    with _STDOUT_LOCK:
        buffer = getattr(sys.stderr, "buffer", None)
        if buffer is not None:
            buffer.write(payload)
            buffer.flush()
        else:
            sys.stderr.write(line)
            sys.stderr.flush()


def _log_ac_registry_once() -> None:
    """Log registered outlook.* AC tools on first invoke (helps debug wrong desktop root)."""
    global _AC_REGISTRY_LOGGED
    if _AC_REGISTRY_LOGGED:
        return
    _AC_REGISTRY_LOGGED = True
    try:
        from app.tools.ac.dispatch import get_registry

        names = sorted(
            name
            for name in get_registry().list_tool_names()
            if name.startswith("outlook.")
        )
        log(f"ac_tools outlook.* ({len(names)}): " + ", ".join(names))
    except Exception as exc:  # noqa: BLE001
        log("ac_tools registry log failed: " + repr(exc))


log(f"desktop root: {DESKTOP_ROOT}")


def _json_default(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return str(value)


def _exc_text(exc: Exception, fallback: str) -> str:
    text = str(exc).strip()
    if not text:
        text = repr(exc).strip()
    return text or fallback


from app.tools.ac.workers.onec_com_session import (  # noqa: E402
    apply_onec_session_credentials,
    com_session_auth_ready,
    missing_com_auth_message,
    snapshot_desktop_com_env,
)

_DESKTOP_COM_ENV = snapshot_desktop_com_env()


def _apply_onec_session_credentials(raw: dict[str, Any] | None) -> None:
    apply_onec_session_credentials(raw, desktop_snapshot=_DESKTOP_COM_ENV)


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
    "Word (.docx), PDF and images: office.read_file with filename or saved_path from "
    "onec.download_artifact. Excel: excel.read_workbook. "
    "Scans and photos are passed to Cursor SDK vision in the tool result — "
    "do not use built-in Read or Grep on docx/pdf/xlsx/jpg and do not look for OCR. "
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
    "Pass people[] to read those employees' calendars. "
    "Pass attendees[] (who must attend) and organizer (whose calendar) to create_event. "
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
    "(свободные слоты; people[] — календари этих сотрудников), затем outlook.create_event "
    "с attendees[] (кто должен прийти) и при необходимости organizer (чей календарь). "
    "Не ограничивайся чтением календаря. "
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

_CALENDAR_CONTROL_TIPS = (
    "подготовка псд",
    "контроль календаря",
    "устный список",
    "без окон",
    "окна в рабочее",
    "на планёрку",
    "на планерку",
    "календаря псд",
    "сдвиг уже стоящих",
)

_SERIES_SCHEDULE_TIPS = (
    "плановые совещани",
    "развёртк",
    "развертк",
    "запланируй",
    "запиши встреч",
)

_RK_TIPS = (
    "ревизионной комиссии",
    "ревизионная комиссия",
    "заседаний ревизион",
    "заседания ревизион",
    "пл-01-001",
    "пл 01-001",
)
_ARTIFACT_CLOSE_TIPS = (
    "проверка артефактов",
    "предложение поручений к закрытию",
    "предложение к закрытию поручений",
)

RK_RUN_HINT = (
    "This is RK meeting prep (ПЛ-01-001), not calendar control. "
    "1C is read-only: never call onec.odata_post, onec.odata_patch, or onec.attach_file. "
    "One data pass only: do not restart outlook/1C/excel/network reads or say data is stale. "
    "Exclude Constructor test probes from 1C (title/comment/number contains Constructor or "
    "проба Constructor). "
    "Network folder: one workspace.powershell_run attempt (dir/list only); on 90s timeout "
    "continue with 1C and materials/attachments. "
    "If Outlook has no Tuesday RK meeting, write «Недостаточно данных: дата заседания не найдена» "
    "but still export partial lists via report.export_document. "
    "Do not call outlook.search_mail or imap.*. "
    "Call report.export_document with the agenda/lists BEFORE ## WORK_RESULT. "
    "If the meeting date is unconfirmed, still export the file, then WORK_RESULT "
    "with «Недостаточно данных». Finish with TESTS: PASS; no step narration in chat."
)
ARTIFACT_CLOSE_HINT = (
    "This is artifact check and close proposal, not RK meeting prep. "
    "Do not search a meeting date, agenda, or \\\\192.168.1.198 RK folders. "
    "Do not ask for an Excel registry or launch files. "
    "Call onec.erp_assignments action=list only_open=true include_files=true limit=100. "
    "If that times out, retry once without include_files, then action=files per card. "
    "Download executor files with onec.download_artifact one file_id at a time. "
    "Read Word/PDF/images via office.read_file, Excel via excel.read_workbook. "
    "Decide per card: recommend close / partial / no / insufficient data. "
    "Export Word, then ## WORK_RESULT. No 1C write without HITL."
)

DAILY_ASSIGNMENT_HINT = (
    "This is the ACT00 journal plus PSD protocols into Action Tracker, "
    "not artifact close and not an open-cards-only sync. "
    "Call onec.erp_assignments action=list customer=Амураль Игорь Борисович "
    "include_all=true only_open=false. Every status goes to the tracker. "
    "Call onec.meeting_protocols meeting_kind=sd psd_mark=true review_only=false "
    "include_closed=true. PSD mark means the number starts with ПСД; "
    "the tool returns the whole series, including closed. "
    "Write every returned assignment and every returned protocol into Action Tracker. "
    "WORK_RESULT counts must equal the tool counts. Do not keep only open cards."
)

CALENDAR_CONTROL_HINT = (
    "This is calendar control / morning briefing, not a meeting-series job. "
    "Morning: users.current, outlook.read_calendar for today, outlook.search_mail once "
    "(query отпуск), calendar.show_meetings. If slots overlap or a window exists, "
    "add «Предложение» and call outlook.create_event — wait for HITL approval. "
    "Do not ask the same via askQuestion. Then ## WORK_RESULT with the oral list. "
    "If search_mail returned 0 messages, absences are empty — do not call it again. "
    "Do not ask what the agent should do. "
    "Evening after 16:00 MSK: same reads for tomorrow, show keep/add/cancel, "
    "propose shifts and call create_event the same way — still wait for HITL. "
    "After WORK_RESULT call no more tools."
)

_SD_MEETING_TIPS = (
    "заседаний совета",
    "заседания совета",
    "подготовка заседаний совета",
    "совета директоров",
    "сд гк",
    "пл-34-242",
    "пл 34-242",
    "пл34-242",
)

_RK_MEETING_TIPS = (
    "ревизионной комиссии",
    "ревизионная комиссия",
    "заседаний ревизион",
    "заседания ревизион",
    "пл-01-001",
    "пл 01-001",
    "пл01-001",
)

_SD_MEETING_TOOLS = {
    "outlook.read_calendar",
    "calendar.show_meetings",
    "onec.meeting_service_notes",
    "onec.meeting_protocols",
    "onec.search_documents",
    "onec.get_document_card",
    "onec.list_attachments",
    "onec.read_attachment",
    "onec.odata_catalog",
    "onec.odata_get",
    "onec.sql_query",
    "onec.erp_tasks_current",
    "onec.erp_tasks_period",
    "onec.docflow_tasks",
    "excel.list_files",
    "excel.read_workbook",
    "office.read_file",
    "report.build_meeting_summary",
    "report.export_document",
    "users.current",
}

_RK_MEETING_TOOLS = {
    "outlook.read_calendar",
    "calendar.show_meetings",
    "onec.meeting_protocols",
    "onec.erp_tasks_current",
    "onec.erp_tasks_period",
    "onec.docflow_tasks",
    "onec.search_documents",
    "onec.get_document_card",
    "onec.list_attachments",
    "onec.read_attachment",
    "onec.odata_get",
    "onec.sql_query",
    "excel.list_files",
    "excel.read_workbook",
    "office.read_file",
    "report.build_task_report",
    "report.build_meeting_summary",
    "report.export_document",
    "workspace.powershell_run",
    "users.current",
}

SD_MEETING_HINT = (
    "This is board-meeting completeness (SD / PL-34-242), not mail search and not "
    "a meeting-series job. 1C is read-only: never call onec.odata_post, onec.odata_patch, "
    "or onec.attach_file. Find the meeting with ONE outlook.read_calendar "
    "(or read the dumped calendar JSON once if COM already wrote it). "
    "Then onec.meeting_service_notes (OData), onec.meeting_protocols (meeting_kind=sd, OData; "
    "numbers ПСД_001_О_*, not manual odata_get with startswith СД/СПГ), "
    "and onec.search_documents (OData) for «совет директоров по гк». Do not use COM 1C. "
    "Do not call outlook.search_mail, imap.search, imap.list_unread, glob/grep loops, "
    "onec.odata_get on Document_ТД_Протокол, or onec.odata_catalog without entity+filter. "
    "If COM is down, one odata_catalog then onec.meeting_protocols; "
    "if 1C is fully unavailable, record the gap in WORK_RESULT and stop. "
    "After WORK_RESULT call no more tools."
)

RK_MEETING_HINT = (
    "This is revision-commission prep (RK / PL-01-001), not mail search. "
    "1C is read-only: never call onec.odata_post, onec.odata_patch, or onec.attach_file. "
    "Use Outlook calendar, onec.meeting_protocols (meeting_kind=rk), 1C tasks/documents, "
    "and the RK share folders. "
    "Do not call outlook.search_mail or imap.*. "
    "If a source is unavailable, record the gap and write ## WORK_RESULT. "
    "After WORK_RESULT call no more tools."
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
RUN_INPUT_WAIT_SECONDS = 30
FILE_QUESTION_SKIP_ANSWER = (
    "Файла нет. Продолжай без вложения: ищи данные в 1С, Outlook, Excel "
    "и сетевых папках по playbook агента. Не спрашивай этот файл снова."
)
RK_FOLDER_SKIP_ANSWER = (
    "Файла нет. Ищи план работ в \\\\192.168.1.198\\Files\\24.Ревизионная комиссия\\Отдел\\8. Планы работ, "
    "реестр в \\\\192.168.1.198\\Files\\24.Ревизионная комиссия\\Отдел\\10. Секретарь РК\\РЕЕСТР ПОРУЧЕНИЙ "
    "и поручения в 1С ERP. Не спрашивай файл снова."
)
RUN_INPUT_SKIP_ANSWER = FILE_QUESTION_SKIP_ANSWER
_RUN_INPUT_GATE_HINTS = (
    "файл, который пользователь будет прикладывать",
    "прикладывать при каждом запуске",
    RUN_INPUTS_QUESTION.casefold(),
)


def _is_calendar_control_text(*parts: Any) -> bool:
    blob = _meeting_blob(*parts)
    return any(tip in blob for tip in _CALENDAR_CONTROL_TIPS)


def _is_artifact_close_text(*parts: Any) -> bool:
    blob = _meeting_blob(*parts)
    return any(tip in blob for tip in _ARTIFACT_CLOSE_TIPS)


def _is_daily_assignment_prompt(prompt: str) -> bool:
    blob = (prompt or "").casefold().replace("ё", "е")
    if _is_artifact_close_text(blob):
        return False
    return any(
        tip in blob
        for tip in (
            "ежедневный контроль поручений",
            "контроль поручений по 1с",
            "аст00 и action tracker",
            "action tracker",
        )
    )


def _is_assignment_journal_text(*parts: Any) -> bool:
    """Журнал поручений — не серия совещаний Outlook; playbook не подменяем."""
    blob = _meeting_blob(*parts)
    if _is_artifact_close_text(blob):
        return True
    if _is_rk_text(blob) or _is_sd_meeting_text(blob):
        return False
    return any(tip in blob for tip in ("аст00", "action tracker", "журнал поруч"))


def _is_rk_text(*parts: Any) -> bool:
    blob = _meeting_blob(*parts)
    if _is_artifact_close_text(blob):
        return False
    if any(hint in blob for hint in ("совета директоров", "пл-34-242", "пл 34-242")):
        return False
    return any(tip in blob for tip in _RK_TIPS)


def _is_sd_meeting_text(*parts: Any) -> bool:
    blob = _meeting_blob(*parts)
    return any(tip in blob for tip in _SD_MEETING_TIPS)


def _workflow_text_parts(record: Any) -> list[Any]:
    parts: list[Any] = [
        getattr(record, "title", "") or "",
        getattr(record, "notes", "") or "",
    ]
    local = getattr(record, "local_run", None) or {}
    if isinstance(local, dict):
        for key in ("playbook", "playbook_draft"):
            raw = local.get(key)
            if isinstance(raw, dict):
                parts.extend(
                    [
                        str(raw.get("name") or ""),
                        str(raw.get("instructions") or ""),
                    ]
                )
    return parts


def _is_sd_meeting_workflow(record: Any) -> bool:
    return _is_sd_meeting_text(*_workflow_text_parts(record))


def _is_rk_meeting_workflow(record: Any) -> bool:
    return _is_rk_text(*_workflow_text_parts(record))


def _is_calendar_control_workflow(record: Any) -> bool:
    parts: list[Any] = [
        getattr(record, "title", "") or "",
        getattr(record, "notes", "") or "",
    ]
    local = getattr(record, "local_run", None) or {}
    if isinstance(local, dict):
        for key in ("playbook", "playbook_draft"):
            raw = local.get(key)
            if isinstance(raw, dict):
                parts.extend(
                    [
                        str(raw.get("name") or ""),
                        str(raw.get("instructions") or ""),
                    ]
                )
    return _is_calendar_control_text(*parts)


_CALENDAR_CONTROL_TOOLS = {
    "users.current",
    "outlook.read_calendar",
    "outlook.search_mail",
    "calendar.show_meetings",
    "outlook.create_event",
    "users.list",
    "notify.send",
}


def _whitelist_tool_names(record: Any) -> list[str]:
    """Playbook / draft tools saved at formation. Empty means the catalog is still open."""
    local = getattr(record, "local_run", None) or {}
    if not isinstance(local, dict):
        local = {}
    book = local.get("playbook") if isinstance(local.get("playbook"), dict) else {}
    draft = local.get("playbook_draft") if isinstance(local.get("playbook_draft"), dict) else {}
    names: list[str] = []
    seen: set[str] = set()
    builtins = {
        "read",
        "grep",
        "glob",
        "ls",
        "shell",
        "edit",
        "delete",
        "applyAgentDiff",
        "code.run_python",
        "write",
    }

    def add(value: object) -> None:
        name = str(value or "").strip()
        if not name or name in seen or name in builtins:
            return
        seen.add(name)
        names.append(name)

    def add_all(values: object) -> None:
        if isinstance(values, (list, tuple, set)):
            for item in values:
                add(item)

    add_all(book.get("tools"))
    add_all(local.get("live_tools_invoked"))
    for blob in (book, draft):
        for step in blob.get("steps") or []:
            if not isinstance(step, dict):
                continue
            add(step.get("tool") or step.get("tool_name"))
            add_all(step.get("tool_candidates"))
    if names and any(
        item in seen
        for item in (
            "onec.download_artifact",
            "excel.read_workbook",
            "onec.erp_assignments",
            "onec.list_attachments",
            "onec.read_attachment",
        )
    ):
        add("office.read_file")
    if names:
        return names
    add_all(local.get("tools"))
    return names


def _tool_specs_for_workflow(record: Any) -> list[dict[str, Any]] | None:
    """Limit an agent to its formation whitelist; fall back to SD/RK/calendar packs."""
    allowed: set[str] | None = None
    names = _whitelist_tool_names(record)
    if names:
        allowed = set(names)
    elif _is_calendar_control_workflow(record):
        allowed = _CALENDAR_CONTROL_TOOLS
    elif _is_sd_meeting_workflow(record):
        allowed = _SD_MEETING_TOOLS
    elif _is_rk_meeting_workflow(record):
        allowed = _RK_MEETING_TOOLS
    if allowed is None:
        return None
    return [
        item
        for item in sdk_tool_specs()
        if str(item.get("name") or "") in allowed
    ]


def _is_outlook_series_prompt(prompt: str) -> bool:
    blob = (prompt or "").casefold()
    if (
        _is_calendar_control_text(blob)
        or _is_sd_meeting_text(blob)
        or _is_rk_text(blob)
        or _is_assignment_journal_text(blob)
    ):
        return False
    return any(tip in blob for tip in _SERIES_SCHEDULE_TIPS)


KPI_MODULE_HINT = (
    "This is a one-shot KPI constructor, not a published agent. "
    "Do not ask when to run, Outlook cadence, triggers, schedule, or per-run files. "
    "Do not design a recurring agent and do not call keepKnowledgeFile. "
    "Step 1: read the PDF in chunks via office.read_file on the file path "
    "from the prompt (start_page=2 skip cover, max_pages=1). Never pass the folder "
    "materials/attachments — only the .pdf filename. "
    "If next_start is present — immediately read the next chunk. "
    "Do not request more than one page per call. "
    "Do not Read extracted.json, methodology.txt or AGENTS.md. "
    "Step 2: from the pages find ONLY KPIs for THIS logged-in position. "
    "Step 3: if that job title is not in the document, write it in chat and STOP. "
    "No more tools, no askQuestion, no files. "
    "Step 4: if KPIs exist, list EVERY indicator of this position from all pages, "
    "name+weight, one per line. Do not stop after the first two. "
    "The last line must be exactly СПИСОК_ГОТОВ. Do not call askQuestion in this message. "
    "Step 5 is later: the next turn asks where plan and fact come from, then writes modules."
)

def _kpi_position_missing(answer: str) -> bool:
    blob = (answer or "").casefold().replace("ё", "е")
    return any(
        token in blob
        for token in (
            "должности нет",
            "должности не найден",
            "нет показателей",
            "показателей нет",
            "kpi этой должности нет",
            "в положении нет",
            "не нашла kpi",
            "не нашел kpi",
            "не относится к должности",
        )
    )


KPI_EXTRACT_PROMPT = (
    "Положение уже прочитано. "
    "ЗАПРЕЩЕНО: office.read_file, excel.list_files, users.current, Read, Grep, Glob, askQuestion. "
    "Выпиши ВСЕ KPI этой должности со всех страниц, не только первые два. "
    "Каждый с новой строки, без вступления: 1. Название — вес N%. "
    "Последняя строка ровно: СПИСОК_ГОТОВ. "
    "Нет должности — одно предложение и стоп, без СПИСОК_ГОТОВ. "
    "План и факт в этом сообщении не спрашивай: вопросы будут следующим шагом."
)

KPI_CONTINUE_PROMPT = KPI_EXTRACT_PROMPT

KPI_ATTACHED_PROMPT = (
    "Страницы положения уже в этом сообщении (со 2-й, без обложки). "
    "Запрещены любые инструменты, в том числе askQuestion. "
    "Первым сообщением — все показатели должности из задания, со всех страниц, "
    "не только первые два. Без вступления, каждый с новой строки: "
    "1. Название — вес N% "
    "Последняя строка ровно: СПИСОК_ГОТОВ. "
    "Если должности нет — одно предложение и стоп, без СПИСОК_ГОТОВ. "
    "После списка ничего не спрашивай: откуда брать план и факт спросит следующий шаг."
)

KPI_REPAIR_LIMIT = 3
KPI_CODE_TOOL_BUDGET = 12
KPI_SDK_RETRIES = 3
KPI_NETWORK_FALLBACK = (
    "Страницы положения не дошли по сети. "
    "Читай PDF кусками: office.read_file start_page=2, max_pages=1. "
    "Если next_start есть — сразу следующий кусок. Не прикладывай все страницы сразу. "
    "Выпиши ВСЕ KPI должности, каждый с новой строки «1. Название — вес N%», "
    "последняя строка СПИСОК_ГОТОВ. Модули не пиши и источники не спрашивай."
)


def _kpi_retry_without_images(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Повтор без картинок: 10 страниц PDF часто рвут Cursor SDK по сети."""
    call = dict(kwargs)
    call["images"] = []
    prompt = str(call.get("prompt") or "")
    if KPI_NETWORK_FALLBACK not in prompt:
        call["prompt"] = f"{KPI_NETWORK_FALLBACK}\n\n{prompt}".strip()
    call["tools"] = sdk_kpi_tool_specs(read_file=True, write=False, run=False)
    return call


def _kpi_asked_blob(active: Any) -> str:
    parts: list[str] = []
    history = getattr(getattr(active, "gate", None), "qa_history", None) or []
    for item in history:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get("question") or ""))
        parts.append(str(item.get("answer") or ""))
    return "\n".join(parts)


def _session_text_blob(session: dict[str, Any] | None) -> str:
    parts: list[str] = []
    for item in (session or {}).get("messages") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("content") or ""))
    draft = (session or {}).get("catalog_draft")
    if isinstance(draft, dict):
        parts.append(str(draft.get("summary") or ""))
        for metric in draft.get("metrics") or []:
            if isinstance(metric, dict):
                parts.append(str(metric.get("name") or ""))
                parts.append(str(metric.get("code") or ""))
    return "\n".join(parts)


def _catalog_draft_from_kpi(
    *,
    session: dict[str, Any] | None,
    rows: list[dict[str, str]],
    source_notes: str,
    position: str,
    run_cwd: Path,
) -> dict[str, Any]:
    blob = "\n".join(part for part in (source_notes, _session_text_blob(session)) if part)
    found = [item for item in (rows or []) if isinstance(item, dict)]
    if not found:
        found = parse_kpi_rows(blob)
    if not found:
        draft = (session or {}).get("catalog_draft") if isinstance((session or {}).get("catalog_draft"), dict) else {}
        for metric in (draft or {}).get("metrics") or []:
            if not isinstance(metric, dict):
                continue
            name = str(metric.get("name") or "").strip()
            if len(name) < 3:
                continue
            found.append(
                {
                    "name": name,
                    "weight": str(metric.get("weight") or ""),
                    "slug": str(metric.get("code") or "").strip(),
                    "source": str((metric.get("sources") or [{}])[-1].get("detail") or "")
                    if isinstance(metric.get("sources"), list) and metric.get("sources")
                    else "",
                }
            )
    if not found:
        for slug in _existing_kpi_slugs(run_cwd):
            found.append({"name": slug, "weight": "", "slug": slug})
    jobs = kpi_write_jobs(found, source_notes=blob, existing_slugs=[], position=position)
    return catalog_from_jobs(jobs, position=position)


def _kpi_source_notes(active: Any) -> str:
    lines: list[str] = []
    history = getattr(getattr(active, "gate", None), "qa_history", None) or []
    for item in history:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        reply = str(item.get("answer") or "").strip()
        if question and reply:
            lines.append(f"{question} — {reply}")
    return "\n".join(lines)


def _ask_missing_kpi_sources(active: Any, rows: list[dict[str, str]]) -> str:
    pending = unasked_kpi_rows(rows, _kpi_asked_blob(active))
    notes: list[str] = []
    for row in pending:
        if active.stop.is_set():
            break
        name = str(row.get("name") or "").strip()
        weight = str(row.get("weight") or "").strip()
        label = f"{name} ({weight}%)" if weight else name
        reply = active.gate.ask_question(
            {
                "question": f"Откуда брать план и факт по показателю «{label}»?",
                "options": list(KPI_SOURCE_OPTIONS),
            },
            should_stop=active.stop.is_set,
        )
        picked = str(reply.get("answer") or reply.get("text") or "").strip()
        if picked and needs_source_detail(picked) and not active.stop.is_set():
            extra = active.gate.ask_question(
                {
                    "question": f"Какая система, отчёт или файл для показателя «{label}»?",
                    "options": [],
                },
                should_stop=active.stop.is_set,
            )
            detail = str(extra.get("answer") or extra.get("text") or "").strip()
            if detail:
                picked = detail
        if picked:
            notes.append(f"{name}: {picked}")
    if not notes:
        return ""
    return "Откуда брать план и факт:\n" + "\n".join(notes)


def _kpi_already_read(prompt: str) -> bool:
    blob = prompt or ""
    return any(
        token in blob
        for token in (
            "Положение уже прочитано",
            "Положение уже в этом сообщении",
            "уже в этом сообщении",
            "Страницы уже сняты",
            "ЗАПРЕЩЕНО: office.read_file",
            "KPI уже выписаны",
            "Не читай PDF",
            "Тесты не прошли",
        )
    )


def _emit_kpi_attached(
    active: Any, images: list[dict[str, Any]], events: list[dict[str, Any]] | None = None
) -> None:
    pages = [item for item in images if isinstance(item, dict)]
    count = len(pages)
    if count <= 0:
        return
    start = next((int(item.get("page") or 0) for item in pages if item.get("page")), 2)
    filename = str(pages[0].get("filename") or "")
    request_id = f"kpi-attach-{uuid.uuid4().hex[:8]}"
    summary = (
        f"Положение приложено в чат: {count} стр."
        + (" (без обложки)" if start > 1 else "")
    )
    payload_call = {
        "type": "tool_call",
        "tool": "office.read_file",
        "status": "running",
        "requestId": request_id,
        "arguments": {"filename": filename} if filename else {},
    }
    payload_done = {
        "type": "tool_result",
        "tool": "office.read_file",
        "status": "ok",
        "requestId": request_id,
        "ok": True,
        "result": {
            "vision": True,
            "delivered_pages": count,
            "start_page": start,
            "filename": filename,
            "summary": summary,
        },
    }
    for payload in (payload_call, payload_done):
        if events is not None:
            events.append(payload)
        emit(
            {
                "type": "event",
                "runId": getattr(active, "run_id", ""),
                "payload": payload,
            }
        )


def _kpi_vision_ready(run_cwd: Path) -> bool:
    vision = Path(run_cwd) / "materials" / "vision"
    if not vision.is_dir():
        return False
    pages = [
        path
        for path in vision.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    return len(pages) >= 2


def _with_sidecar_prompt(prompt: str, *, mode: str = "run") -> str:
    folded = (mode or "").strip().casefold()
    text = (prompt or "").strip()
    # KPI explain / other one-shot evals must not inherit playbook tool hints.
    if folded == "eval":
        return text
    if folded == "kpi":
        if _kpi_already_read(text):
            return text
        return "\n\n".join(part for part in (KPI_MODULE_HINT, text) if part)
    parts = [KEEP_FILE_HINT]
    if _is_calendar_control_text(prompt):
        parts.append(CALENDAR_CONTROL_HINT)
    elif _is_artifact_close_text(prompt):
        parts.append(ARTIFACT_CLOSE_HINT)
    elif _is_daily_assignment_prompt(prompt):
        parts.append(DAILY_ASSIGNMENT_HINT)
    elif _is_sd_meeting_text(prompt):
        parts.append(SD_MEETING_HINT)
    elif _is_rk_text(prompt):
        parts.append(RK_RUN_HINT)
    elif _is_outlook_series_prompt(prompt):
        parts.append(OUTLOOK_MEETING_HINT)
    if folded == "design":
        parts.append(WHEN_TO_RUN_HINT)
        parts.append(RUN_INPUTS_HINT)
    else:
        parts.append(RUN_INPUTS_RUN_HINT)
    if text:
        parts.append(text)
    return "\n\n".join(parts)


def _with_keep_file_prompt(prompt: str) -> str:
    return _with_sidecar_prompt(prompt)


def _meeting_blob(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts).casefold()


def _is_meeting_text(*parts: Any) -> bool:
    if (
        _is_calendar_control_text(*parts)
        or _is_sd_meeting_text(*parts)
        or _is_rk_text(*parts)
        or _is_assignment_journal_text(*parts)
    ):
        return False
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
        name = str(raw.get("name") or "")
        if (
            _is_calendar_control_text(current, name)
            or _is_sd_meeting_text(current, name)
            or _is_rk_text(current, name)
            or _is_assignment_journal_text(current, name)
        ):
            continue
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
        include_app_tools: bool = True,
        images: list[dict[str, Any]] | None = None,
        stop_on_kpi_list: bool = True,
        kpi_allow_read: bool = False,
    ) -> dict[str, Any]:
        kpi = (mode or "").strip().casefold() == "kpi"
        if kpi:
            specs = list(tools) if tools is not None else list(sdk_kpi_tool_specs())
        elif include_app_tools:
            specs = list(tools) if tools is not None else list(sdk_tool_specs())
            if not any(_is_keep_knowledge_file(str(item.get("name") or "")) for item in specs):
                specs.append(dict(KEEP_KNOWLEDGE_FILE_SPEC))
        else:
            specs = list(tools) if tools is not None else []
        if workflow_id:
            self._knowledge_workflow_id = workflow_id
        if cwd:
            self._knowledge_cwd = cwd
        kind = str(getattr(self._hitl_gate, "_kind", "") or "")
        must_confirm = bool(confirm_writes) or kind == "run"
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
            confirm_writes=must_confirm,
            restrict_builtins=kpi or tools is not None,
            images=images,
            stop_on_kpi_list=stop_on_kpi_list,
            kpi_allow_read=kpi_allow_read,
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
        self._events: list[dict[str, Any]] | None = None
        self.on_events_changed: Any = None
        self.work_result_done = False

    def bind(self, *, workflow_id: str = "", kind: str = "") -> None:
        if workflow_id:
            self._workflow_id = workflow_id
        if kind:
            self._kind = kind

    def bind_events(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    def _notify_events_changed(self) -> None:
        callback = self.on_events_changed
        if callback is None:
            return
        try:
            callback()
        except Exception:  # noqa: BLE001
            pass

    def _append_wait_event(self, event: dict[str, Any]) -> None:
        payload = _with_at(dict(event))
        if self._events is not None:
            self._events.append(payload)
        self._notify_events_changed()

    def _mark_wait_event(self, request_id: str, *, approved: bool) -> None:
        rid = (request_id or "").strip()
        if not rid or self._events is None:
            return
        for ev in reversed(self._events):
            if str(ev.get("type") or "") not in {"hitl", "question"}:
                continue
            ev_id = str(ev.get("requestId") or ev.get("request_id") or "").strip()
            if ev_id != rid:
                continue
            ev["status"] = "approved" if approved else "rejected"
            ev["ok"] = bool(approved)
            ev["skipped"] = not approved
            break
        self._notify_events_changed()

    def _record_timing(self, typ: str, wait: str, request_id: str) -> None:
        if self._events is None:
            return
        self._events.append(
            {
                "type": typ,
                "wait": wait,
                "requestId": request_id,
                "at": _now_iso(),
            }
        )

    def mark_work_result_done(self) -> None:
        self.work_result_done = True
        with self._lock:
            pending = list(self._hitl.items())
        for _request_id, box in pending:
            try:
                box.put_nowait(False)
            except Exception:
                continue

    def request(self, tool: str, args: dict[str, Any]) -> bool:
        if self.work_result_done:
            return False
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
                    "title": _tool_wait_title(tool),
                    "text": f"Нужно подтверждение: {tool}",
                },
                workflow_id=self._workflow_id,
                kind=self._kind,
            )
        )
        self._append_wait_event(
            {
                "type": "hitl",
                "tool": tool,
                "title": _tool_wait_title(tool),
                "text": f"Нужно подтверждение: {tool}",
                "requestId": request_id,
                "arguments": _safe_args(args),
                "confirm_only": True,
                "status": "pending",
            }
        )
        self._record_timing("human_wait", "hitl", request_id)
        try:
            return box.get()
        finally:
            with self._lock:
                self._hitl.pop(request_id, None)

    def resolve_hitl(self, request_id: str, approved: bool) -> None:
        self._record_timing("human_reply", "hitl", request_id)
        self._mark_wait_event(request_id, approved=approved)
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
        wait_s, skip_answer = _auto_continue_from_payload(payload)
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
                    "autoContinueSeconds": wait_s or None,
                    "autoContinueAnswer": skip_answer or None,
                },
                workflow_id=self._workflow_id,
                kind=self._kind,
            )
        )
        self._append_wait_event(
            {
                "type": "question",
                "tool": "askQuestion",
                "title": question or "Вопрос агента",
                "text": question,
                "requestId": request_id,
                "confirm_only": True,
                "status": "pending",
            }
        )
        self._record_timing("human_wait", "question", request_id)
        reply: dict[str, Any] = {}
        deadline = time.monotonic() + wait_s if wait_s > 0 else None
        try:
            while True:
                if should_stop and should_stop():
                    return {"ok": False, "answer": "", "text": ""}
                try:
                    reply = box.get(timeout=0.4)
                    break
                except queue.Empty:
                    if deadline is not None and time.monotonic() >= deadline:
                        reply = {"ok": True, "answer": skip_answer, "text": skip_answer}
                        break
                    continue
        finally:
            with self._lock:
                self._answers.pop(request_id, None)
        answer = str(reply.get("answer") or reply.get("text") or "").strip()
        ok = bool(reply.get("ok", True)) and bool(answer)
        if question or answer:
            self.qa_history.append({"question": question, "answer": answer})
        return {"ok": ok, "answer": answer, "text": answer}

    def release_pending_questions(self) -> None:
        with self._lock:
            pending = list(self._answers.items())
        for _request_id, box in pending:
            try:
                box.put_nowait({"ok": False, "answer": "", "text": ""})
            except Exception:
                continue

    def consume_needs_file(self, request_id: str) -> bool:
        with self._lock:
            return bool(self._needs_file.pop(request_id, False))

    def resolve_answer(self, request_id: str, reply: dict[str, Any]) -> None:
        self._record_timing("human_reply", "question", request_id)
        approved = bool(reply.get("ok", True)) and bool(
            str(reply.get("answer") or reply.get("text") or "").strip()
        )
        self._mark_wait_event(request_id, approved=approved)
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


def _auto_continue_from_payload(payload: dict[str, Any]) -> tuple[float, str]:
    args = _as_record(payload.get("arguments"))
    nested = _as_record(args.get("arguments") or args.get("input") or args.get("properties"))
    source = {**nested, **args, **payload}
    raw = source.get("autoContinueSeconds")
    if raw is None:
        raw = source.get("auto_continue_seconds")
    try:
        wait_s = float(raw or 0)
    except (TypeError, ValueError):
        wait_s = 0.0
    if wait_s < 0:
        wait_s = 0.0
    skip = str(
        source.get("autoContinueAnswer")
        or source.get("auto_continue_answer")
        or ""
    ).strip()
    needs_file, _ = _file_request_from_payload(payload)
    if needs_file and wait_s <= 0:
        wait_s = float(RUN_INPUT_WAIT_SECONDS)
    if needs_file and not skip:
        skip = FILE_QUESTION_SKIP_ANSWER
    elif wait_s > 0 and not skip:
        skip = RUN_INPUT_SKIP_ANSWER
    return wait_s, skip


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


_OUTPUT_SWEEP_MAX_AGE_SEC = 12 * 3600


def _recent_output_paths(paths: list[Path]) -> list[Path]:
    """Keep documents written during this run, not leftover clone files."""
    cutoff = time.time() - _OUTPUT_SWEEP_MAX_AGE_SEC
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.resolve()
            key = str(resolved)
            if key in seen or not resolved.is_file():
                continue
            if resolved.stat().st_mtime < cutoff:
                continue
            seen.add(key)
            out.append(resolved)
        except OSError:
            continue
    return out


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
        swept: list[Path] = []
        swept.extend(collect_workspace_output_files(workflow_id))
        cwd = Path(run_cwd) if run_cwd else None
        swept.extend(collect_output_files_from_dir(cwd))
        found.extend(_recent_output_paths(swept))
    paths = [str(path) for path in found if path.is_file()]
    if not paths:
        return []
    _upload_run_outputs(api, workflow_id, paths, run_id=run_id)
    return paths


_NAMED_RESULT_FILE_RE = re.compile(
    r"(?im)^\s*([^\s:/\\]+\.(?:docx|xlsx|xls|pdf|md|txt))\s*:?\s*$"
)


def _files_named_in_answer(answer: str) -> list[str]:
    raw = answer or ""
    section = re.search(
        r"(?is)\bFILES\b\s*:?\s*(.*?)(?:\n\s*(?:ACTIONS|NOTIFICATIONS|SCHEDULE|CLARIFY|TESTS)\b|\Z)",
        raw,
    )
    blob = section.group(1) if section else raw
    names: list[str] = []
    for match in _NAMED_RESULT_FILE_RE.finditer(blob):
        name = Path(match.group(1)).name
        if name and name not in names:
            names.append(name)
    if names:
        return names
    for match in re.finditer(
        r"([A-Za-zА-Яа-я0-9_.\-]+\.(?:docx|xlsx|xls|pdf|md|txt))",
        blob,
        flags=re.I,
    ):
        name = Path(match.group(1)).name
        if name and name not in names:
            names.append(name)
    return names


def _write_answer_document(cwd: str, filename: str, answer: str) -> Path | None:
    folder = Path(cwd or "").expanduser()
    if not folder.is_dir():
        return None
    name = Path(filename).name or "report.docx"
    path = folder / name
    body = (answer or "").strip() or name
    try:
        from app.tools.ac.office_style import pretty_title, write_docx

        if path.suffix.lower() != ".docx":
            path = path.with_suffix(".docx")
        write_docx(
            path,
            title=pretty_title(Path(name).stem),
            sections=[{"heading": "", "body": body}],
        )
        return path
    except Exception:
        fallback = path.with_suffix(".md")
        fallback.write_text(body, encoding="utf-8")
        return fallback


def _ensure_result_files_from_answer(
    api: ApiClient | None,
    workflow_id: str,
    run_cwd: str,
    answer: str,
    run_id: str = "",
) -> list[str]:
    if api is None or not (workflow_id or "").strip():
        return []
    names = _files_named_in_answer(answer)
    if not names:
        return []
    created: list[str] = []
    folder = Path(run_cwd) if run_cwd else None
    for name in names:
        existing = folder / name if folder else None
        if existing is not None and existing.is_file():
            created.append(str(existing))
            continue
        written = _write_answer_document(run_cwd, name, answer)
        if written is not None and written.is_file():
            created.append(str(written))
    if not created:
        return []
    _upload_run_outputs(api, workflow_id, created, run_id=run_id)
    return created


def _work_result_body(answer: str) -> str:
    raw = (answer or "").strip()
    match = re.search(r"#{0,6}[ \t]*WORK[ _]?RESULT\b", raw, re.I)
    return raw[match.start() :].strip() if match else raw


def _persist_work_result_if_needed(
    api: ApiClient | None,
    workflow_id: str,
    run_cwd: str,
    answer: str,
    run_id: str = "",
    existing: list[str] | None = None,
) -> list[str]:
    """If the run produced WORK_RESULT but no result file, store the oral result."""
    if api is None or not (workflow_id or "").strip():
        return []
    if any(Path(item).name.lower().startswith(("результат", "result_")) for item in existing or []):
        return []
    if not _text_has_finished_work_result(answer):
        return []
    body = _work_result_body(answer)
    if not body:
        return []
    folder = Path(run_cwd) if run_cwd else None
    if folder is None:
        return []
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    path = folder / f"Результат_{stamp}.md"
    path.write_text(body, encoding="utf-8")
    _upload_run_outputs(api, workflow_id, [str(path)], run_id=run_id)
    return [str(path)]


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
RUN_JOURNAL_DIR = "materials/run_journal"


def _journal_slug(workflow_id: str) -> str:
    raw = (workflow_id or "").strip()
    if not raw:
        return "shared"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
    return safe or "shared"


def _run_journal_path(cwd: str, workflow_id: str) -> Path:
    root = Path(cwd).resolve()
    rel = f"{RUN_JOURNAL_DIR}/{_journal_slug(workflow_id)}.md"
    target = (root / rel).resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"refusing to write outside workspace: {rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _legacy_run_journal_path(cwd: str) -> Path:
    root = Path(cwd).resolve()
    target = (root / RUN_JOURNAL_RELATIVE).resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"refusing to write outside workspace: {RUN_JOURNAL_RELATIVE}")
    return target


def _with_run_journal_prompt(prompt: str, cwd: str, workflow_id: str) -> str:
    scoped = _run_journal_path(cwd, workflow_id)
    if scoped.is_file():
        rel = scoped.relative_to(Path(cwd).resolve()).as_posix()
        hint = (
            f"Skim {rel} once (first ~50 lines, one Read). "
            "Do not re-read it; then call Constructor tools."
        )
        return f"{hint}\n\n{prompt}"
    legacy = _legacy_run_journal_path(cwd)
    if not legacy.is_file():
        return prompt
    hint = (
        "Skim materials/run_journal.md once (first ~50 lines, one Read). "
        "Do not re-read it; then call Constructor tools."
    )
    return f"{hint}\n\n{prompt}"


def _append_run_journal(
    cwd: str,
    *,
    workflow_id: str,
    message: str,
    answer: str,
    events: list[dict[str, Any]],
    qa_history: list[dict[str, str]],
    status: str,
    run_ref: str,
) -> None:
    path = _run_journal_path(cwd, workflow_id)
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


def _command_flag(value: Any) -> bool:
    if value is True:
        return True
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _is_eval_command(command: dict[str, Any]) -> bool:
    source = str(command.get("source") or "").strip().lower()
    if source in {"eval", "explain"}:
        return True
    return _command_flag(command.get("fresh"))


EVAL_UI_PREFIX = "__bg_explain__"


def _eval_ui_workflow_id(workflow_id: str) -> str:
    wid = (workflow_id or "").strip()
    if not wid or wid.startswith(EVAL_UI_PREFIX):
        return wid
    return f"{EVAL_UI_PREFIX}{wid}"


def _payload_explain_verdict(payload: dict[str, Any]) -> bool:
    """True when assistant text already contains a complete explain JSON object."""
    text = " ".join(
        str(payload.get(key) or "")
        for key in ("text", "message", "answer", "content")
    )
    if '"verdict"' not in text:
        return False
    start = text.find("{")
    while start >= 0:
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth != 0:
                    continue
                chunk = text[start : index + 1]
                try:
                    data = json.loads(chunk)
                except json.JSONDecodeError:
                    break
                if isinstance(data, dict) and str(data.get("verdict") or "").strip():
                    return True
                break
        start = text.find("{", start + 1)
    return False


PERSONAL_AGENT_PREFIX = "personal-agent:"


def _is_personal_agent(workflow_id: str) -> bool:
    return (workflow_id or "").startswith(PERSONAL_AGENT_PREFIX)


def _build_personal_agent_prompt(message: str, app_context: str = "") -> str:
    task = (message or "").strip() or "Помоги сотруднику по организационному вопросу."
    context = (app_context or "").strip()
    context_block = (
        "\n\nКонтекст рабочего места (Сегодня / процессы / решения / KPI). "
        "Опирайся на него и на инструменты приложения (users.*, board, 1С, почта, файлы):\n"
        f"{context}\n"
        if context
        else "\n\nКонтекст рабочего места не передан — при необходимости получи факты инструментами приложения.\n"
    )
    return (
        "Ты — Оркестратор, базовый агент рабочего места сотрудника в приложении «Оркестратор». "
        "Ты видишь и можешь использовать данные всего приложения: вкладки Сегодня, Процессы, Решения, "
        "Показатели, История, Настройки, а также серверные инструменты (пользователь, board, 1С, почта, "
        "Turbo Project, файлы). Сначала получай факты инструментами, потом давай итог. "
        "Весь ответ и вопросы пиши на русском."
        f"{context_block}\n"
        f"Вопрос сотрудника:\n{task}"
    )


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
        self._personal_agent_ids: dict[str, str] = {}
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
        # COM 1C workers read ERP_LOGIN / ERP_PASSWORD / ONEC_COM_USR from process env.
        # Session creds from Orchestrator login override desktop/.env when sent here.
        _apply_onec_session_credentials(command)

    def check_ready(self) -> None:
        try:
            ElectronBridge(HitlGate("probe")).check_ready()
            emit({"type": "ready_state", "ok": True, "message": ""})
        except CursorSdkUnavailable as exc:
            emit({"type": "ready_state", "ok": False, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            emit({"type": "ready_state", "ok": False, "message": str(exc)})

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
            or command.get("buildId")
            or command.get("triggerId")
            or ""
        ).strip()
        if kind in {"form_orchestrator", "calc_orchestrator"}:
            return kind
        if kind == "run" and _is_eval_command(command):
            return f"eval:{target}" if target else "eval"
        return f"{kind}:{target}" if target else ""

    def start(self, kind: str, command: dict[str, Any]) -> None:
        run_id = str(command.get("id") or uuid.uuid4().hex)
        dedup_key = self._dedup_key(kind, command)
        replace_personal = dedup_key.startswith(f"run:{PERSONAL_AGENT_PREFIX}")
        replace_eval = dedup_key.startswith("eval:")
        is_manual_run = (
            kind == "run"
            and bool(dedup_key)
            and not _is_trigger_command(command)
            and not _is_eval_command(command)
        )
        force_restart = _command_flag(
            command.get("forceRestart") or command.get("force_restart")
        )
        overlap_run_id = ""
        skip_run_id = ""
        skip_trigger = False
        with self._lock:
            kpi_busy = any(
                existing.kind == "kpi_module" and _sdk_run_alive(existing)
                for existing in self._active.values()
            )
            if kind == "check_trigger" and kpi_busy:
                skip_trigger = True
            elif dedup_key:
                for existing in list(self._active.values()):
                    if existing.dedup_key != dedup_key:
                        continue
                    replace = (
                        force_restart
                        or is_manual_run
                        or replace_personal
                        or replace_eval
                        or not _sdk_run_alive(existing)
                    )
                    if replace:
                        log(
                            "replace active run: "
                            + _ascii(f"{dedup_key} (active run {existing.run_id})")
                        )
                        existing.stop.set()
                        try:
                            existing.bridge.skip_tool("")
                        except Exception:
                            pass
                        self._active.pop(existing.run_id, None)
                        break
                    if is_manual_run or force_restart:
                        # Manual UI start must never adopt a stale sidecar slot.
                        log(
                            "force replace manual run: "
                            + _ascii(f"{dedup_key} (active run {existing.run_id})")
                        )
                        existing.stop.set()
                        try:
                            existing.bridge.skip_tool("")
                        except Exception:
                            pass
                        self._active.pop(existing.run_id, None)
                        break
                    if _is_trigger_command(command):
                        log(
                            "skip duplicate run: "
                            + _ascii(f"{dedup_key} (active run {existing.run_id})")
                        )
                        overlap_run_id = existing.run_id
                        break
                    log(
                        "skip duplicate run: "
                        + _ascii(f"{dedup_key} (active run {existing.run_id})")
                    )
                    skip_run_id = existing.run_id
                    break
            if not skip_trigger and not overlap_run_id and not skip_run_id:
                gate = HitlGate(run_id)
                stop = threading.Event()
                bridge = ElectronBridge(gate)
                active = ActiveRun(run_id=run_id, gate=gate, stop=stop, bridge=bridge)
                active.dedup_key = dedup_key
                active.kind = kind
                active.workflow_id = str(command.get("workflowId") or "").strip()
                if active.workflow_id:
                    gate.bind(workflow_id=active.workflow_id, kind=kind)
                active.gate.on_events_changed = lambda current=active: self._flush_run_events(current)
                self._active[run_id] = active
        if skip_trigger:
            log("skip trigger while kpi_module is running")
            return
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
                    "type": "run_adopted",
                    "runId": run_id,
                    "linkedRunId": skip_run_id,
                    "message": "Продолжаю текущий запуск агента.",
                }
            )
            return
        stamp_wf = str(command.get("workflowId") or "").strip()
        if _is_eval_command(command):
            stamp_wf = _eval_ui_workflow_id(stamp_wf)
        emit(
            _stamp_run_event(
                {
                    "type": "event",
                    "runId": run_id,
                    "payload": {"type": "status", "text": f"Запускаю агента ({kind})."},
                },
                workflow_id=stamp_wf,
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
            elif kind in {"form_orchestrator", "calc_orchestrator"}:
                self._run_orchestrator(command, active, kind)
            elif kind == "kpi_module":
                self._run_kpi_module(command, active)
            else:
                emit({"type": "error", "runId": active.run_id, "message": f"unknown run kind: {kind}"})
        except CursorSdkUnavailable as exc:
            self._finish_active_history(active, "Cursor SDK не отвечает")
            emit(
                {
                    "type": "error",
                    "runId": active.run_id,
                    "code": "sdk_unavailable",
                    "message": str(exc),
                }
            )
        except ApiError as exc:
            self._finish_active_history(active, "Cursor SDK не отвечает")
            emit(
                {
                    "type": "error",
                    "runId": active.run_id,
                    "message": _exc_text(exc, "Ошибка backend во время запуска агента"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            self._finish_active_history(active, "Cursor SDK не отвечает")
            log("run failed: " + repr(exc))
            log(traceback.format_exc())
            emit(
                {
                    "type": "error",
                    "runId": active.run_id,
                    "message": _exc_text(exc, "Внутренняя ошибка запуска агента"),
                }
            )
        finally:
            with self._lock:
                self._active.pop(active.run_id, None)

    def _flush_run_events(self, active: ActiveRun) -> None:
        run_ref = (active.history_run_id or "").strip()
        if not run_ref or not active.workflow_id:
            return
        try:
            self._api.update_local_agent_run_events(
                active.workflow_id,
                run_ref,
                list(active.events),
            )
        except ApiError:
            pass
        self._notify_fresh_waits(active)

    def _notify_fresh_waits(self, active: ActiveRun) -> None:
        seen = getattr(active, "notified_waits", None)
        if seen is None:
            seen = set()
            active.notified_waits = seen
        for raw in list(active.events):
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("type") or "").strip().lower()
            if kind not in {"hitl", "question"}:
                continue
            request_id = str(raw.get("requestId") or raw.get("request_id") or "").strip()
            status = str(raw.get("status") or "").strip().lower()
            if not request_id or request_id in seen:
                continue
            seen.add(request_id)
            if status in {"approved", "rejected"} or raw.get("skipped"):
                continue
            tool = str(raw.get("tool") or raw.get("title") or raw.get("text") or "").strip()
            hint = f": {tool}" if tool else ""
            self._api.notify_run_inbox(
                title="Агент ожидает подтверждения",
                body=f"Агент ожидает подтверждения{hint}. Откройте вкладку «Решения».",
                workflow_id=active.workflow_id,
                run_id=active.history_run_id,
            )

    def _forward_events(self, active: ActiveRun, events: list[dict[str, Any]]):
        """Build an on_event callback that streams raw runner events."""

        last_flush = 0

        def on_event(payload: dict[str, Any]) -> None:
            nonlocal last_flush
            if not isinstance(payload, dict):
                return
            event_type = str(payload.get("type") or "")
            if event_type in {"assistant", "thinking", "final", "status"}:
                blob = " ".join(
                    str(payload.get(key) or "")
                    for key in ("text", "answer", "message")
                )
                if blob.strip() and event_type != "thinking":
                    active.answer_buf = f"{active.answer_buf}{blob}"
                if event_type in {"assistant", "final"} and (
                    _text_has_finished_work_result(blob)
                    or _text_has_finished_work_result(active.answer_buf)
                ):
                    active.gate.mark_work_result_done()
                    active.stop.set()
            if event_type not in {"ready", "done"}:
                events.append(_with_at(payload))
            event_wf = (active.event_workflow_id or active.workflow_id or "").strip()
            # Interactive question/tool_request are handled via HITL gate.
            if event_type in {"question", "tool_request"}:
                self._flush_run_events(active)
                if active.kind == "eval":
                    active.stop.set()
                return
            emit(
                _stamp_run_event(
                    {"type": "event", "runId": active.run_id, "payload": payload},
                    workflow_id=event_wf,
                    kind=active.kind,
                )
            )
            if active.kind == "eval":
                if event_type in {"tool_call", "tool_result"}:
                    active.stop.set()
                elif _payload_explain_verdict(payload):
                    active.stop.set()
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

    def _stop_when_kpi_checked(
        self,
        active: ActiveRun,
        events: list[dict[str, Any]],
        run_cwd: Path,
        slug: str = "",
    ):
        """Остановить ход, когда pytest этого slug прошёл, или когда бюджет кончился."""
        inner = self._forward_events(active, events)
        calls = 0
        want = (slug or "").strip()

        def on_event(payload: dict[str, Any]) -> None:
            nonlocal calls
            inner(payload)
            if not isinstance(payload, dict):
                return
            tool = str(payload.get("tool") or payload.get("name") or "").casefold()
            kind = str(payload.get("type") or "").casefold()
            if kind != "tool_result":
                return
            if "write_python" not in tool and "run_python" not in tool:
                return
            calls += 1
            _promote_kpi_artifacts(Path(run_cwd))
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            script = str(result.get("script") or "")
            exit_code = result.get("exit_code")
            this_slug = (not want) or f"test_{want}.py" in script or _kpi_slug_ready(Path(run_cwd), want)
            passed = (
                "run_python" in tool
                and bool(payload.get("ok"))
                and exit_code in {0, "0"}
                and this_slug
                and (_kpi_slug_ready(Path(run_cwd), want) if want else _kpi_artifacts_ready(Path(run_cwd)))
            )
            if passed or calls >= KPI_CODE_TOOL_BUDGET:
                text = (
                    f"Тесты {want or 'модуля'} прошли."
                    if passed
                    else "Лимит правок модуля. Проверяю тестами конструктора…"
                )
                emit(
                    {
                        "type": "event",
                        "runId": active.run_id,
                        "payload": {"type": "status", "text": text},
                    }
                )
                active.stop.set()

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
        events = active.events
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
        events = active.events
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

    def _kpi_bridge_run(self, active: ActiveRun, bridge: Any, **kwargs: Any) -> dict[str, Any]:
        last_exc: CursorSdkError | None = None
        call = dict(kwargs)
        for attempt in range(1, KPI_SDK_RETRIES + 1):
            if active.stop.is_set():
                break
            try:
                return bridge.run(**call)
            except CursorSdkUnavailable:
                raise
            except CursorSdkError as exc:
                last_exc = exc
                if not is_transient_cursor_error(exc) or attempt >= KPI_SDK_RETRIES:
                    raise
                if call.get("images"):
                    call = _kpi_retry_without_images(call)
                    text = (
                        f"Страницы не дошли по сети, читаю PDF повтор {attempt} из "
                        f"{KPI_SDK_RETRIES - 1}…"
                    )
                else:
                    text = (
                        f"Cursor SDK не ответил, повтор {attempt} из "
                        f"{KPI_SDK_RETRIES - 1}…"
                    )
                emit(
                    {
                        "type": "event",
                        "runId": active.run_id,
                        "payload": {"type": "status", "text": text},
                    }
                )
                time.sleep(2 * attempt)
        if last_exc is not None:
            raise last_exc
        return {"answer": "", "agent_id": str(kwargs.get("resume_agent_id") or "")}

    def _run_kpi_code_turn(
        self,
        *,
        active: ActiveRun,
        bridge: Any,
        run_cwd: Path,
        workspace_id: str,
        events: list[dict[str, Any]],
        prompt: str,
        slug: str,
        resume_agent_id: str = "",
    ) -> tuple[str, str]:
        active.stop.clear()
        result = self._kpi_bridge_run(
            active,
            bridge,
            prompt=prompt,
            workflow_id=workspace_id,
            cwd=str(run_cwd),
            mode="kpi",
            tools=sdk_kpi_write_tool_specs(),
            resume_agent_id=resume_agent_id,
            on_event=self._stop_when_kpi_checked(active, events, run_cwd, slug=slug),
            on_question=active.gate.ask_question,
            should_stop=active.stop.is_set,
            confirm_writes=True,
            stop_on_kpi_list=False,
            kpi_allow_read=True,
        )
        active.stop.clear()
        _promote_kpi_artifacts(run_cwd)
        return str(result.get("answer") or "").strip(), str(result.get("agent_id") or resume_agent_id).strip()

    def _write_kpi_modules(
        self,
        *,
        active: ActiveRun,
        bridge: Any,
        run_cwd: Path,
        workspace_id: str,
        events: list[dict[str, Any]],
        answer: str,
        position: str,
        rows: list[dict[str, str]],
        source_notes: str,
    ) -> tuple[str, str]:
        jobs = kpi_write_jobs(
            rows,
            source_notes=source_notes,
            existing_slugs=_existing_kpi_slugs(run_cwd),
            position=position,
        )
        writer_id = ""
        for job in jobs:
            if active.stop.is_set():
                break
            slug = str(job.get("slug") or "").strip()
            if not slug:
                continue
            emit(
                {
                    "type": "event",
                    "runId": active.run_id,
                    "payload": {"type": "status", "text": f"Пишу модуль {slug}…"},
                }
            )
            try:
                more, writer_id = self._run_kpi_code_turn(
                    active=active,
                    bridge=bridge,
                    run_cwd=run_cwd,
                    workspace_id=workspace_id,
                    events=events,
                    prompt=str(job.get("prompt") or ""),
                    slug=slug,
                    resume_agent_id="",
                )
            except CursorSdkError as exc:
                emit(
                    {
                        "type": "event",
                        "runId": active.run_id,
                        "payload": {
                            "type": "status",
                            "text": f"Модуль {slug}: Cursor SDK не ответил, перехожу к следующему.",
                        },
                    }
                )
                answer = f"{answer}\n\n{slug}: {exc}".strip()
                continue
            if more:
                answer = f"{answer}\n\n{more}".strip()
            ok, pytest_out = _run_kpi_slug_tests(run_cwd, slug)
            attempt = 0
            while not ok and attempt < KPI_REPAIR_LIMIT and not active.stop.is_set():
                attempt += 1
                emit(
                    {
                        "type": "event",
                        "runId": active.run_id,
                        "payload": {
                            "type": "status",
                            "text": f"Тесты {slug} не прошли, правка {attempt} из {KPI_REPAIR_LIMIT}…",
                        },
                    }
                )
                try:
                    more, writer_id = self._run_kpi_code_turn(
                        active=active,
                        bridge=bridge,
                        run_cwd=run_cwd,
                        workspace_id=workspace_id,
                        events=events,
                        prompt=kpi_repair_prompt(slug, pytest_out),
                        slug=slug,
                        resume_agent_id=writer_id,
                    )
                except CursorSdkError as exc:
                    answer = f"{answer}\n\n{slug}: правка не дошла, {exc}".strip()
                    break
                if more:
                    answer = f"{answer}\n\n{more}".strip()
                ok, pytest_out = _run_kpi_slug_tests(run_cwd, slug)
            if not ok and pytest_out.strip():
                answer = f"{answer}\n\n{slug}: тесты не прошли\n{pytest_out.strip()[:1500]}".strip()
        return answer, writer_id

    def _rewrite_kpi_until_tests_pass(
        self,
        active: ActiveRun,
        bridge: Any,
        run_cwd: Path,
        workspace_id: str,
        agent_id: str,
        events: list[dict[str, Any]],
        answer: str,
    ) -> tuple[list[dict[str, Any]], bool, str, str, str]:
        modules = _collect_kpi_modules(run_cwd)
        if not modules:
            return [], True, "", answer, agent_id
        emit(
            {
                "type": "event",
                "runId": active.run_id,
                "payload": {"type": "status", "text": "Проверяю тесты модуля…"},
            }
        )
        pytest_ok, pytest_out = _run_kpi_workspace_tests(run_cwd)
        attempt = 0
        while modules and not pytest_ok and attempt < KPI_REPAIR_LIMIT:
            attempt += 1
            for item in modules:
                slug = str(item.get("metric_code") or "").strip()
                if not slug:
                    continue
                slug_ok, slug_out = _run_kpi_slug_tests(run_cwd, slug)
                if slug_ok:
                    continue
                emit(
                    {
                        "type": "event",
                        "runId": active.run_id,
                        "payload": {
                            "type": "status",
                            "text": f"Тесты {slug} не прошли, правка {attempt} из {KPI_REPAIR_LIMIT}…",
                        },
                    }
                )
                more, agent_id = self._run_kpi_code_turn(
                    active=active,
                    bridge=bridge,
                    run_cwd=run_cwd,
                    workspace_id=workspace_id,
                    events=events,
                    prompt=kpi_repair_prompt(slug, slug_out),
                    slug=slug,
                    resume_agent_id="",
                )
                if more:
                    answer = f"{answer}\n\n{more}".strip()
            modules = _collect_kpi_modules(run_cwd)
            pytest_ok, pytest_out = _run_kpi_workspace_tests(run_cwd)
        return modules, pytest_ok, pytest_out, answer, agent_id

    def _run_kpi_module(self, command: dict[str, Any], active: ActiveRun) -> None:
        build_id = str(command.get("buildId") or command.get("build_id") or "").strip()
        if not build_id:
            raise ValueError("kpi_module requires buildId")
        bridge = active.bridge
        bridge.check_ready()
        session = self._api.get_position_kpi_build(build_id)
        workspace_id = str(command.get("workflowId") or f"kpi-build-{build_id}").strip()
        run_cwd = Path(bridge.workspace_cwd(workspace_id))
        active.run_cwd = str(run_cwd)
        active.workflow_id = workspace_id
        active.gate.bind(workflow_id=workspace_id, kind="kpi_module")
        _prepare_kpi_workspace(run_cwd, session)
        events: list[dict[str, Any]] = []
        answer = ""
        agent_id = str(session.get("cursor_agent_id") or "").strip()
        _promote_kpi_artifacts(run_cwd)
        modules = _collect_kpi_modules(run_cwd)
        session_modules = session.get("modules") if isinstance(session.get("modules"), list) else []
        if session_modules and _kpi_artifacts_ready(run_cwd):
            emit(
                {
                    "type": "event",
                    "runId": active.run_id,
                    "payload": {"type": "status", "text": "Модуль уже записан. Проверяю тесты…"},
                }
            )
            modules, pytest_ok, pytest_out, answer, agent_id = self._rewrite_kpi_until_tests_pass(
                active,
                bridge,
                run_cwd,
                workspace_id,
                agent_id,
                events,
                answer,
            )
            if pytest_out.strip():
                answer = f"Тесты конструктора:\n{pytest_out.strip()[:2000]}"
            if modules and pytest_ok:
                emit(
                    {
                        "type": "event",
                        "runId": active.run_id,
                        "payload": {"type": "status", "text": "Тесты прошли. Подключаю KPI…"},
                    }
                )
            finished = self._api.finish_position_kpi_build(
                build_id,
                answer=answer,
                events=events,
                modules=modules,
                catalog_draft=_catalog_draft_from_kpi(
                    session=session,
                    rows=[],
                    source_notes=_kpi_source_notes(active),
                    position=str(session.get("position") or "").strip(),
                    run_cwd=run_cwd,
                ),
                cursor_agent_id=agent_id,
                connect=bool(modules) and pytest_ok,
            )
            if modules and pytest_ok and str(finished.get("status") or "") != "connected":
                finished = self._api.connect_position_kpi_build(build_id)
            emit(
                {
                    "type": "result",
                    "runId": active.run_id,
                    "kind": "kpi_module",
                    "buildId": build_id,
                    "status": str(finished.get("status") or ""),
                    "agentId": agent_id,
                    "answer": answer,
                    "pytestOk": pytest_ok,
                }
            )
            return
        file_paths = [str(p) for p in (command.get("filePaths") or []) if str(p).strip()]
        copied = _copy_attachments(str(run_cwd), file_paths) or _existing_methodology_files(run_cwd)
        position = str(session.get("position") or "").strip()
        emit(
            {
                "type": "event",
                "runId": active.run_id,
                "payload": {"type": "status", "text": "Прикладываю положение в чат…"},
            }
        )
        events: list[dict[str, Any]] = []
        prompt = str(command.get("prompt") or session.get("sdk_prompt") or "").strip()
        if not prompt:
            prompt = "Прочитай методику и собери KPI должности пользователя."
        note = _attachments_note(copied, position=position)
        if note:
            prompt = (
                f"{prompt}\n\n{note}\n"
                "Читай PDF кусками: office.read_file filename — точный путь к файлу выше, "
                "не папка. Первый вызов start_page=2, max_pages=1. "
                "Если next_start есть — сразу следующий кусок с этим start_page. "
                "Не прикладывай все страницы сразу. "
                f"Ищи только KPI должности «{position or 'из задания'}». "
                "Нет в документе — напиши пользователю и остановись. "
                "Когда куски кончились — выпиши ВСЕ показатели, каждый с новой строки "
                "«1. Название — вес N%», последняя строка СПИСОК_ГОТОВ. "
                "Модули пока не пиши и источники не спрашивай."
            )
        elif not str(session.get("sdk_prompt") or "").strip():
            prompt += (
                "\n\nФайла методики ещё нет — спроси через askQuestion с needsFile=true."
            )
        resume_id = str(
            command.get("resumeAgentId")
            or command.get("resume_agent_id")
            or session.get("cursor_agent_id")
            or ""
        ).strip()
        kpi_tools = sdk_kpi_tool_specs(read_file=True, write=False, run=False)
        try:
            result = self._kpi_bridge_run(
                active,
                bridge,
                prompt=prompt,
                workflow_id=workspace_id,
                cwd=str(run_cwd),
                mode="kpi",
                tools=kpi_tools,
                resume_agent_id=resume_id,
                images=[],
                on_event=self._forward_events(active, events),
                on_question=active.gate.ask_question,
                should_stop=active.stop.is_set,
                confirm_writes=False,
            )
        except CursorSdkError as exc:
            if not is_transient_cursor_error(exc) or active.stop.is_set():
                raise
            emit(
                {
                    "type": "event",
                    "runId": active.run_id,
                    "payload": {
                        "type": "status",
                        "text": "Сеть оборвалась, читаю положение ещё раз…",
                    },
                }
            )
            result = self._kpi_bridge_run(
                active,
                bridge,
                prompt=prompt,
                workflow_id=workspace_id,
                cwd=str(run_cwd),
                mode="kpi",
                tools=kpi_tools,
                resume_agent_id="",
                images=[],
                on_event=self._forward_events(active, events),
                on_question=active.gate.ask_question,
                should_stop=active.stop.is_set,
                confirm_writes=False,
            )
        answer = str(result.get("answer") or "").strip()
        agent_id = str(result.get("agent_id") or resume_id).strip()
        modules = _collect_kpi_modules(run_cwd)

        def _asked_kpi_clarify(items: list[dict[str, Any]]) -> bool:
            for ev in items:
                if not isinstance(ev, dict):
                    continue
                kind = str(ev.get("type") or "").casefold()
                tool = str(ev.get("tool") or ev.get("name") or "").casefold()
                if kind == "question" or tool in {"askquestion", "ask_question"}:
                    return True
            return False

        rows = parse_kpi_rows(answer)
        if (
            not rows
            and not modules
            and not _asked_kpi_clarify(events)
            and not _kpi_position_missing(answer)
            and not active.stop.is_set()
        ):
            emit(
                {
                    "type": "event",
                    "runId": active.run_id,
                    "payload": {"type": "status", "text": "Выделяю KPI должности…"},
                }
            )
            result = self._kpi_bridge_run(
                active,
                bridge,
                prompt=KPI_CONTINUE_PROMPT,
                workflow_id=workspace_id,
                cwd=str(run_cwd),
                mode="kpi",
                tools=kpi_tools,
                resume_agent_id=agent_id,
                on_event=self._forward_events(active, events),
                on_question=active.gate.ask_question,
                should_stop=active.stop.is_set,
                confirm_writes=False,
            )
            more = str(result.get("answer") or "").strip()
            if more:
                answer = more
            agent_id = str(result.get("agent_id") or agent_id).strip()
            modules = _collect_kpi_modules(run_cwd)
            rows = parse_kpi_rows(answer)
        source_notes = ""
        if rows and not _kpi_position_missing(answer) and not active.stop.is_set():
            emit(
                {
                    "type": "event",
                    "runId": active.run_id,
                    "payload": {"type": "status", "text": "Уточняю, откуда брать план и факт…"},
                }
            )
            asked = _ask_missing_kpi_sources(active, rows)
            if asked:
                answer = f"{answer}\n\n{asked}".strip()
            source_notes = _kpi_source_notes(active)
            answer, writer_id = self._write_kpi_modules(
                active=active,
                bridge=bridge,
                run_cwd=run_cwd,
                workspace_id=workspace_id,
                events=events,
                answer=answer,
                position=position,
                rows=rows,
                source_notes=source_notes,
            )
            if writer_id:
                agent_id = writer_id
        _promote_kpi_artifacts(run_cwd)
        modules = _collect_kpi_modules(run_cwd)
        if modules:
            emit(
                {
                    "type": "event",
                    "runId": active.run_id,
                    "payload": {"type": "status", "text": "Проверяю тесты модуля…"},
                }
            )
            pytest_ok, pytest_out = _run_kpi_workspace_tests(run_cwd)
        else:
            pytest_ok, pytest_out = True, ""
        if pytest_out.strip():
            answer = f"{answer}\n\nТесты конструктора:\n{pytest_out.strip()[:2000]}".strip()
        catalog = _catalog_draft_from_kpi(
            session=session,
            rows=rows,
            source_notes=source_notes,
            position=position,
            run_cwd=run_cwd,
        )
        parsed = extract_json_object(answer) if answer else None
        if isinstance(parsed, dict) and not catalog.get("metrics"):
            parsed_catalog = parsed.get("catalog") if isinstance(parsed.get("catalog"), dict) else parsed
            if isinstance(parsed_catalog, dict) and parsed_catalog.get("metrics"):
                catalog = parsed_catalog
        if modules and pytest_ok:
            emit(
                {
                    "type": "event",
                    "runId": active.run_id,
                    "payload": {"type": "status", "text": "Тесты прошли. Подключаю KPI…"},
                }
            )
        finished = self._api.finish_position_kpi_build(
            build_id,
            answer=answer,
            events=events,
            modules=modules,
            catalog_draft=catalog if isinstance(catalog, dict) else {},
            cursor_agent_id=agent_id,
            connect=bool(modules) and pytest_ok,
        )
        if modules and pytest_ok and str(finished.get("status") or "") != "connected":
            finished = self._api.connect_position_kpi_build(build_id)
        emit(
            {
                "type": "result",
                "runId": active.run_id,
                "kind": "kpi_module",
                "buildId": build_id,
                "status": str(finished.get("status") or ""),
                "agentId": agent_id,
                "answer": answer,
                "pytestOk": pytest_ok,
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
        # Wipe leftover temp files from previous trial runs. Keep attachments on
        # resume so a sample attached earlier in this formation survives.
        reset_run_scratch(run_cwd, clear_attachments=not resume_agent_id)
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
        events = active.events
        prompt = build_demo_sdk_prompt(record, resume=bool(resume_agent_id))
        for extra_note in run_input_notes:
            if extra_note:
                prompt = prompt + "\n\n" + extra_note
        result = bridge.run(
            prompt=prompt,
            workflow_id=workflow_id,
            cwd=run_cwd,
            resume_agent_id=resume_agent_id,
            tools=_tool_specs_for_workflow(record),
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
        if _is_eval_command(command):
            self._run_eval(command, active, workflow_id)
            return
        if _is_personal_agent(workflow_id):
            self._run_personal_agent(command, active, workflow_id)
            return
        active.workflow_id = workflow_id
        active.kind = "run"
        active.gate.bind(workflow_id=workflow_id, kind="run")
        message = str(command.get("message") or "").strip()
        source = str(command.get("source") or "chat").strip() or "chat"
        # Scheduled runs have no file picker, but write confirmations still wait
        # on the Orchestrator «Решения» tab until the user answers.
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
        # Each run is independent: clear leftover temp files (tool_results and
        # stale attachments) so they don't pile up or leak into this run. A chat
        # follow-up (resume, no new files) keeps the previous turn's attachments.
        _has_new_files = any(str(p).strip() for p in (command.get("filePaths") or []))
        reset_run_scratch(
            run_cwd,
            clear_attachments=autonomous or not resume_agent_id or _has_new_files,
        )
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
        # already attach. Trigger runs have no file picker, so we skip attach,
        # but write confirmations still wait on «Решения».
        run_input_notes: list[str] = []
        if not autonomous:
            run_input_notes = self._ensure_run_inputs_provided(
                active, workflow, provided_count=len(file_paths)
            )
        events = active.events
        # Always include current workflow materials in the prompt. If a saved
        # SDK agent id belongs to another machine/account and resume falls back
        # to a fresh agent, the run still has the full playbook context.
        prompt = build_sdk_prompt(workflow, message)
        note = _attachments_note(attachment_paths)
        if note:
            prompt = prompt + "\n\n" + note
        for extra_note in run_input_notes:
            if extra_note:
                prompt = prompt + "\n\n" + extra_note
        prompt = _with_run_journal_prompt(prompt, run_cwd, workflow_id)
        status = "ok"
        answer = ""
        agent_id = resume_agent_id
        try:
            try:
                result = bridge.run(
                    prompt=prompt,
                    # Regular workflow runs must keep workflow context so tools,
                    # workspace isolation and run history stay scoped correctly.
                    workflow_id=workflow_id,
                    cwd=run_cwd,
                    resume_agent_id=resume_agent_id,
                    tools=_tool_specs_for_workflow(workflow),
                    on_event=self._forward_events(active, events),
                    on_question=active.gate.ask_question,
                    should_stop=active.stop.is_set,
                    confirm_writes=True,
                )
            except Exception as exc:  # noqa: BLE001
                if resume_agent_id and self._is_missing_resume_agent_error(exc) and not active.stop.is_set():
                    log(f"resume agent missing for {workflow_id}, retry fresh run")
                    self._clear_stored_agent_id(workflow_id)
                    result = bridge.run(
                        prompt=prompt,
                        workflow_id=workflow_id,
                        cwd=run_cwd,
                        resume_agent_id="",
                        tools=_tool_specs_for_workflow(workflow),
                        on_event=self._forward_events(active, events),
                        on_question=active.gate.ask_question,
                        should_stop=active.stop.is_set,
                        confirm_writes=True,
                    )
                else:
                    raise
            answer = str(result.get("answer") or "").strip()
            agent_id = str(result.get("agent_id") or resume_agent_id).strip()
            self._store_agent_id(workflow_id, agent_id)
            continues = 0
            while (
                status == "ok"
                and agent_id
                and not active.stop.is_set()
                and not _text_has_finished_work_result(answer)
                and continues < _MAX_WORK_CONTINUES
            ):
                continues += 1
                log(f"work result missing for {workflow_id}, continue {continues}")
                on_event = self._forward_events(active, events)
                on_event(
                    {
                        "type": "status",
                        "text": "Продолжаю запуск до WORK_RESULT — уже прочитанные файлы не открываю снова.",
                    }
                )
                result = bridge.run(
                    prompt=build_continue_run_prompt(),
                    workflow_id=workflow_id,
                    cwd=run_cwd,
                    resume_agent_id=agent_id,
                    tools=_tool_specs_for_workflow(workflow),
                    on_event=on_event,
                    on_question=active.gate.ask_question,
                    should_stop=active.stop.is_set,
                    confirm_writes=True,
                )
                nxt = str(result.get("answer") or "").strip()
                if nxt:
                    answer = nxt
                agent_id = str(result.get("agent_id") or agent_id).strip()
                self._store_agent_id(workflow_id, agent_id)
            if status == "ok" and not _text_has_finished_work_result(answer):
                status = "error"
                tail = answer.strip()
                answer = (
                    "Запуск завершился без ## WORK_RESULT и TESTS: PASS — "
                    "агент остановился после подготовительных шагов."
                )
                if tail:
                    answer = f"{answer}\n\n{tail}"
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
                    workflow_id=workflow_id,
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
            output_paths = _persist_run_outputs(
                self._api,
                workflow_id,
                run_cwd,
                run_id=str(run_ref or active.run_id).strip(),
            )
            if not output_paths:
                output_paths = _ensure_result_files_from_answer(
                    self._api,
                    workflow_id,
                    run_cwd,
                    answer,
                    run_id=str(run_ref or active.run_id).strip(),
                )
            _persist_work_result_if_needed(
                self._api,
                workflow_id,
                run_cwd,
                answer,
                run_id=str(run_ref or active.run_id).strip(),
                existing=output_paths,
            )
        except Exception as exc:  # noqa: BLE001
            log("run output sweep failed: " + repr(exc))
        try:
            _append_run_journal(
                run_cwd,
                workflow_id=workflow_id,
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

    def _run_eval(
        self,
        command: dict[str, Any],
        active: ActiveRun,
        workflow_id: str,
    ) -> None:
        """One-shot JSON eval (KPI explain). Isolated from the live agent thread."""
        message = str(command.get("message") or "").strip()
        if not message:
            raise ValueError("eval requires message")
        active.workflow_id = workflow_id
        active.kind = "eval"
        active.event_workflow_id = _eval_ui_workflow_id(workflow_id)
        active.gate.bind(workflow_id=workflow_id, kind="eval")
        bridge = active.bridge
        bridge.check_ready()
        eval_cwd_id = f"eval-{workflow_id}"
        run_cwd = bridge.workspace_cwd(eval_cwd_id)
        active.run_cwd = run_cwd
        bridge.bind_knowledge(None, "", run_cwd, active.run_id)

        def _reject_question(payload: dict[str, Any], should_stop: Any = None) -> dict[str, Any]:
            del payload, should_stop
            active.stop.set()
            return {"ok": False, "answer": "", "text": ""}

        events = active.events
        status = "ok"
        answer = ""
        try:
            result = bridge.run(
                prompt=message,
                workflow_id=eval_cwd_id,
                cwd=run_cwd,
                mode="eval",
                tools=[],
                resume_agent_id="",
                on_event=self._forward_events(active, events),
                on_question=_reject_question,
                should_stop=active.stop.is_set,
                confirm_writes=False,
                include_app_tools=False,
            )
            answer = str(result.get("answer") or "").strip()
        except Exception as exc:  # noqa: BLE001
            if active.stop.is_set() and events:
                status = "ok"
                for event in reversed(events):
                    text = str(event.get("text") or event.get("message") or event.get("answer") or "").strip()
                    if text:
                        answer = text
                        break
            else:
                status = "error"
                answer = str(exc)
                emit(
                    {
                        "type": "error",
                        "runId": active.run_id,
                        "kind": "eval",
                        "workflowId": active.event_workflow_id,
                        "message": _exc_text(exc, "Фоновая оценка не завершилась"),
                    }
                )
                return
        emit(
            {
                "type": "result",
                "runId": active.run_id,
                "kind": "run",
                "workflowId": active.event_workflow_id,
                "status": status,
                "answer": answer,
            }
        )

    def _run_personal_agent(
        self,
        command: dict[str, Any],
        active: ActiveRun,
        workflow_id: str,
    ) -> None:
        active.workflow_id = workflow_id
        active.kind = "run"
        active.gate.bind(workflow_id=workflow_id, kind="run")
        message = str(command.get("message") or "").strip()
        app_context = str(command.get("appContext") or command.get("app_context") or "").strip()
        source = str(command.get("source") or "chat").strip() or "chat"
        autonomous = source == "trigger"
        resume_agent_id = str(command.get("resumeAgentId") or "").strip()
        if not resume_agent_id:
            resume_agent_id = self._personal_agent_ids.get(workflow_id, "").strip()
        bridge = active.bridge
        bridge.check_ready()
        run_cwd = bridge.workspace_cwd(workflow_id)
        active.run_cwd = run_cwd
        # Personal agent is not bound to a single workflow playbook.
        bridge.bind_knowledge(None, "", run_cwd, active.run_id)
        if app_context:
            try:
                materials = Path(run_cwd) / "materials"
                materials.mkdir(parents=True, exist_ok=True)
                (materials / "orchestrator_context.md").write_text(
                    "# Контекст рабочего места\n\n" + app_context + "\n",
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                log("orchestrator context write failed: " + repr(exc))
        file_paths = [str(p) for p in (command.get("filePaths") or []) if str(p).strip()]
        attachment_paths = _copy_attachments(run_cwd, file_paths)
        events = active.events
        prompt = _build_personal_agent_prompt(message, app_context)
        note = _attachments_note(attachment_paths)
        if note:
            prompt = prompt + "\n\n" + note
        prompt = _with_run_journal_prompt(prompt, run_cwd, workflow_id)
        status = "ok"
        answer = ""
        agent_id = resume_agent_id
        try:
            try:
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
            except Exception as exc:  # noqa: BLE001
                if resume_agent_id and self._is_missing_resume_agent_error(exc) and not active.stop.is_set():
                    log(f"personal resume agent missing for {workflow_id}, retry fresh run")
                    self._personal_agent_ids.pop(workflow_id, None)
                    result = bridge.run(
                        prompt=prompt,
                        workflow_id=workflow_id,
                        cwd=run_cwd,
                        resume_agent_id="",
                        on_event=self._forward_events(active, events),
                        on_question=active.gate.ask_question,
                        should_stop=active.stop.is_set,
                        confirm_writes=True,
                    )
                else:
                    raise
            answer = str(result.get("answer") or "").strip()
            agent_id = str(result.get("agent_id") or resume_agent_id).strip()
            if agent_id:
                self._personal_agent_ids[workflow_id] = agent_id
        except Exception as exc:  # noqa: BLE001
            status = "error"
            answer = str(exc)
            try:
                _append_run_journal(
                    run_cwd,
                    workflow_id=workflow_id,
                    message=message,
                    answer=answer,
                    events=events,
                    qa_history=active.gate.qa_history,
                    status=status,
                    run_ref=active.run_id,
                )
            except Exception as journal_exc:  # noqa: BLE001
                log("run journal write failed: " + repr(journal_exc))
            raise
        try:
            _append_run_journal(
                run_cwd,
                workflow_id=workflow_id,
                message=message,
                answer=answer,
                events=events,
                qa_history=active.gate.qa_history,
                status=status,
                run_ref=active.run_id,
            )
        except Exception as exc:  # noqa: BLE001
            log("run journal write failed: " + repr(exc))
        emit(
            {
                "type": "result",
                "runId": active.run_id,
                "kind": "run",
                "workflowId": workflow_id,
                "runRef": active.run_id,
                "agentId": agent_id,
                "status": status,
                "answer": answer,
            }
        )

    def _run_orchestrator(self, command: dict[str, Any], active: ActiveRun, kind: str) -> None:
        mode = "form" if kind == "form_orchestrator" else "calc"
        active.kind = kind
        workspace_id = "orchestrator"
        active.workflow_id = workspace_id
        active.gate.bind(workflow_id=workspace_id, kind=kind)
        bridge = active.bridge
        bridge.check_ready()
        snap = self._api.ensure_orchestrator(mode)
        needs_form = bool(snap.get("needs_form"))
        needs_calc = bool(snap.get("needs_calc"))
        if mode == "form" and not needs_form and not (snap.get("form_prompt") or "").strip():
            emit({"type": "result", "runId": active.run_id, "kind": kind, "status": "ok", "orchestrator": snap})
            return
        if mode == "calc" and not (snap.get("tiles") or []):
            emit({"type": "result", "runId": active.run_id, "kind": kind, "status": "ok", "orchestrator": snap})
            return
        prompt = str(snap.get("form_prompt") if mode == "form" else snap.get("calc_prompt") or "").strip()
        if not prompt:
            if mode == "form" and not needs_form:
                emit({"type": "result", "runId": active.run_id, "kind": kind, "status": "ok", "orchestrator": snap})
                return
            if mode == "calc" and not needs_calc:
                emit({"type": "result", "runId": active.run_id, "kind": kind, "status": "ok", "orchestrator": snap})
                return
            raise ValueError("orchestrator prompt is empty")
        resume_agent_id = str(command.get("resumeAgentId") or snap.get("sdk_agent_id") or "").strip()
        run_cwd = bridge.workspace_cwd(workspace_id)
        active.run_cwd = run_cwd
        events = active.events
        result = bridge.run(
            prompt=prompt,
            workflow_id=workspace_id,
            cwd=run_cwd,
            resume_agent_id=resume_agent_id,
            on_event=self._forward_events(active, events),
            on_question=active.gate.ask_question,
            should_stop=active.stop.is_set,
            confirm_writes=False,
        )
        answer = str(result.get("answer") or "").strip()
        agent_id = str(result.get("agent_id") or resume_agent_id).strip()
        parsed = extract_json_object(answer) or {}
        if mode == "form":
            tiles = parsed.get("tiles") if isinstance(parsed.get("tiles"), list) else []
            if not tiles:
                raise ValueError("orchestrator form did not return tiles")
            snap = self._api.save_orchestrator(
                {
                    "summary": str(parsed.get("summary") or ""),
                    "tiles": tiles,
                    "sdk_agent_id": agent_id,
                }
            )
        else:
            tiles = parsed.get("tiles") if isinstance(parsed.get("tiles"), list) else []
            snap = self._api.patch_orchestrator_tiles(
                {
                    "tiles": tiles,
                    "sdk_agent_id": agent_id,
                }
            )
        emit(
            {
                "type": "result",
                "runId": active.run_id,
                "kind": kind,
                "status": "ok",
                "agentId": agent_id,
                "orchestrator": snap,
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

    @staticmethod
    def _is_missing_resume_agent_error(exc: Exception) -> bool:
        text = str(exc or "").strip().lower()
        return "agent " in text and " not found" in text

    def _clear_stored_agent_id(self, workflow_id: str) -> None:
        wid = (workflow_id or "").strip()
        if not wid or _is_personal_agent(wid):
            return
        try:
            record = self._api.get_workflow(wid)
            local = dict(record.local_run or {})
            if "sdk_agent_id" not in local:
                return
            local.pop("sdk_agent_id", None)
            self._api.update_workflow_local_run(wid, local)
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
        skip_answer = (
            RK_FOLDER_SKIP_ANSWER
            if _is_rk_meeting_workflow(workflow)
            else FILE_QUESTION_SKIP_ANSWER
        )
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
                    "autoContinueSeconds": RUN_INPUT_WAIT_SECONDS,
                    "autoContinueAnswer": skip_answer,
                    "why": (
                        "Это временный файл только для текущего запуска, "
                        "он не сохраняется в базу знаний. "
                        "Через 30 секунд агент продолжит сам по playbook."
                    ),
                },
                should_stop=active.stop.is_set,
            )
            answer = str(reply.get("answer") or "").strip() or skip_answer
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
            self._flush_run_events(active)

    def hitl(self, command: dict[str, Any]) -> None:
        request_id = str(command.get("requestId") or "")
        approved = bool(command.get("approved"))
        for active in list(self._active.values()):
            active.gate.resolve_hitl(request_id, approved)
            self._flush_run_events(active)

    def skip(self, command: dict[str, Any]) -> None:
        request_id = str(command.get("requestId") or "")
        for active in list(self._active.values()):
            try:
                active.bridge.skip_tool(request_id)
            except Exception:  # noqa: BLE001
                pass

    def read_calendar(self, command: dict[str, Any]) -> None:
        """Read the current user's Outlook meetings and emit a calendar_result.

        Runs in a background thread so the sidecar command loop keeps serving
        agent runs while Outlook COM (which can be slow) is queried. Reuses the
        exact tool the agent uses (outlook.read_calendar via SubprocessComWorker),
        so COM stays isolated and the safe read path is shared.
        """
        request_id = str(command.get("requestId") or command.get("id") or "")
        input_data: dict[str, Any] = {}
        date_from = str(command.get("dateFrom") or "").strip()
        date_to = str(command.get("dateTo") or "").strip()
        if date_from:
            input_data["date_from"] = date_from
        if date_to:
            input_data["date_to"] = date_to
        people = command.get("people")
        if isinstance(people, list):
            names = [str(p).strip() for p in people if str(p).strip()]
            if names:
                input_data["people"] = names
        for_user = str(command.get("forUser") or "").strip()
        if for_user:
            input_data["for_user"] = for_user
        if command.get("allVisible"):
            input_data["all_visible"] = True
        days_forward = command.get("daysForward")
        if isinstance(days_forward, int) and days_forward > 0:
            input_data["days_forward"] = days_forward
        if command.get("allVisible"):
            input_data["max_scan_items"] = 2000
        elif for_user:
            input_data["max_scan_items"] = 500

        def _work() -> None:
            try:
                from app.tools.ac.dispatch import invoke_ac_tool

                output = invoke_ac_tool("outlook.read_calendar", input_data)
                events = output.get("events") or []
                log(
                    "read_calendar ok count="
                    + str(len(events) if isinstance(events, list) else 0)
                    + " from="
                    + date_from
                    + " to="
                    + date_to
                    + " for_user="
                    + for_user
                    + " all_visible="
                    + str(bool(command.get("allVisible")))
                )
                emit(
                    {
                        "type": "calendar_result",
                        "requestId": request_id,
                        "ok": True,
                        "events": events if isinstance(events, list) else [],
                        "calendars": output.get("calendars") or [],
                        "rangeStart": output.get("range_start") or "",
                        "rangeEnd": output.get("range_end") or "",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                log("read_calendar failed: " + repr(exc))
                emit(
                    {
                        "type": "calendar_result",
                        "requestId": request_id,
                        "ok": False,
                        "error": _exc_text(exc, "Не удалось прочитать календарь Outlook"),
                    }
                )

        threading.Thread(
            target=_work,
            name=f"read_calendar-{request_id[:8]}",
            daemon=True,
        ).start()

    def search_mail(self, command: dict[str, Any]) -> None:
        """Read Outlook inbox/sent for a day via outlook.search_mail (local COM)."""
        request_id = str(command.get("requestId") or command.get("id") or "")
        input_data: dict[str, Any] = {
            "folder": str(command.get("folder") or "Inbox"),
            "max_results": int(command.get("maxResults") or 50),
        }
        date_value = str(command.get("date") or "").strip()
        date_from = str(command.get("dateFrom") or "").strip()
        date_to = str(command.get("dateTo") or "").strip()
        if date_value:
            input_data["date"] = date_value
        if date_from:
            input_data["date_from"] = date_from
        if date_to:
            input_data["date_to"] = date_to
        query = command.get("query")
        if query is not None and str(query).strip():
            input_data["query"] = str(query).strip()

        def _work() -> None:
            try:
                from app.tools.ac.dispatch import invoke_ac_tool

                output = invoke_ac_tool("outlook.search_mail", input_data)
                messages = output.get("messages") or []
                log(
                    "search_mail ok count="
                    + str(len(messages) if isinstance(messages, list) else 0)
                    + " date="
                    + date_value
                )
                emit(
                    {
                        "type": "mail_result",
                        "requestId": request_id,
                        "ok": True,
                        "messages": messages if isinstance(messages, list) else [],
                        "source": output.get("source") or "outlook_com",
                        "rangeStart": output.get("range_start") or "",
                        "rangeEnd": output.get("range_end") or "",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                log("search_mail failed: " + repr(exc))
                emit(
                    {
                        "type": "mail_result",
                        "requestId": request_id,
                        "ok": False,
                        "error": _exc_text(exc, "Не удалось прочитать почту Outlook"),
                    }
                )

        threading.Thread(
            target=_work,
            name=f"search_mail-{request_id[:8]}",
            daemon=True,
        ).start()

    def invoke_ac_tool_cmd(self, command: dict[str, Any]) -> None:
        """Run any COM-backed AC tool locally (e.g. onec.search_tasks)."""
        request_id = str(command.get("requestId") or command.get("id") or "")
        tool_name = str(command.get("tool") or "").strip()
        raw_input = command.get("input")
        input_data = raw_input if isinstance(raw_input, dict) else {}

        def _work() -> None:
            try:
                from app.tools.ac.dispatch import invoke_ac_tool

                _log_ac_registry_once()
                if not tool_name:
                    raise ValueError("tool name required")
                if tool_name.startswith("onec."):
                    _apply_onec_session_credentials(input_data)
                    if not com_session_auth_ready():
                        raise RuntimeError(missing_com_auth_message())
                output = invoke_ac_tool(tool_name, input_data)
                log("invoke_ac_tool ok tool=" + tool_name)
                emit(
                    {
                        "type": "ac_tool_result",
                        "requestId": request_id,
                        "ok": True,
                        "tool": tool_name,
                        "result": output if isinstance(output, dict) else {"value": output},
                    }
                )
            except Exception as exc:  # noqa: BLE001
                log("invoke_ac_tool failed tool=" + tool_name + ": " + repr(exc))
                emit(
                    {
                        "type": "ac_tool_result",
                        "requestId": request_id,
                        "ok": False,
                        "tool": tool_name,
                        "error": _exc_text(exc, "Не удалось выполнить локальный инструмент"),
                    }
                )

        threading.Thread(
            target=_work,
            name=f"invoke_ac-{request_id[:8]}",
            daemon=True,
        ).start()

    def cancel(self, command: dict[str, Any]) -> None:
        run_id = str(command.get("id") or "")
        workflow_id = str(command.get("workflowId") or "").strip()
        dedup_key = f"run:{workflow_id}" if workflow_id else ""
        remove_ids: list[str] = []
        for active in list(self._active.values()):
            ui_id = (active.event_workflow_id or "").strip()
            by_run = bool(run_id) and active.run_id == run_id
            by_workflow = bool(workflow_id) and (
                active.workflow_id == workflow_id or ui_id == workflow_id
            )
            by_dedup = bool(dedup_key) and active.dedup_key == dedup_key
            if run_id or workflow_id:
                if not by_run and not by_workflow and not by_dedup:
                    continue
            active.stop.set()
            try:
                active.bridge.skip_tool("")
            except Exception:
                pass
            remove_ids.append(active.run_id)
        if remove_ids:
            with self._lock:
                for rid in remove_ids:
                    self._active.pop(rid, None)

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
        self.answer_buf: str = ""
        self.event_workflow_id: str = ""
        self.events: list[dict[str, Any]] = []
        gate.bind_events(self.events)


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


def _existing_methodology_files(run_cwd: Path) -> list[str]:
    folder = Path(run_cwd) / "materials" / "attachments"
    if not folder.is_dir():
        return []
    allowed = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
    found: list[str] = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in allowed:
            found.append(path.relative_to(run_cwd).as_posix())
    return found


def _attachments_note(relative_paths: list[str], *, position: str = "") -> str:
    if not relative_paths:
        return ""
    listing = ", ".join(relative_paths)
    who = f" Должность: {position}." if position.strip() else ""
    return (
        "PDF методики, не папка: office.read_file filename= "
        + listing
        + "."
        + who
    )


def _backend_kpi_root() -> Path:
    here = Path(__file__).resolve()
    repo = here.parents[3]
    return repo / "backend" / "kpi"


def _prepare_kpi_workspace(run_cwd: Path, session: dict[str, Any]) -> None:
    materials = run_cwd / "materials"
    examples = run_cwd / "examples"
    generated = run_cwd / "generated"
    tests = run_cwd / "tests"
    for folder in (materials, examples, generated, tests):
        folder.mkdir(parents=True, exist_ok=True)
    attached = materials / "vision" / ".attached"
    if attached.is_file():
        attached.unlink()
    write_kpi_example_files(examples)
    extracted = session.get("extracted") if isinstance(session.get("extracted"), dict) else {}
    position = str(session.get("position") or "").strip()
    source_text = ""
    prompt = str(session.get("sdk_prompt") or "")
    marker = "Текст методики (сокращённо):"
    if marker in prompt:
        source_text = prompt.split(marker, 1)[-1].strip()
    if source_text:
        methodology = source_text
    elif extracted.get("needs_vision"):
        methodology = (
            "ТЕКСТА НЕТ. Это скан, не методика.\n"
            "Не ищи KPI в этом файле и в extracted.json.\n"
            f"Должность: {position or 'из задания'}.\n"
            "Первое действие: office.read_file на файл .pdf внутри materials/attachments "
            "(точный путь с именем файла, start_page=2, max_pages=1).\n"
            "Если next_start есть — сразу следующий кусок. Не читай больше одной страницы за вызов.\n"
            "Если должности нет в положении — напиши пользователю и остановись.\n"
        )
    else:
        methodology = (
            str(session.get("sdk_prompt") or "").strip()
            or "Методика ещё не приложена. Спроси файл через askQuestion."
        )
    (materials / "methodology.txt").write_text(methodology, encoding="utf-8")
    (materials / "extracted.json").write_text(
        json.dumps(extracted or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_cwd / "AGENTS.md").write_text(
        "\n".join(
            [
                "# KPI module contract",
                "",
                "List KPIs in the first turn. Write code in a later new-agent turn, one slug at a time.",
                "A write turn has no PDF and no methodology images.",
                "While listing KPIs, do not call office.read_file and do not Read extracted.json.",
                "While writing code, Read examples/orders_on_time.py, then write one slug.",
                "The write turn has every Constructor tool. Find the source with them.",
                "1C: onec.odata_catalog then onec.odata_get. Do not invent EntitySet names.",
                "extracted.json is metadata only. Do not read the PDF again.",
                "code.write_python filename must be generated/<slug>.py and tests/test_<slug>.py.",
                "Those paths are the workspace root, not the code/ folder.",
                "Then code.run_python filename=tests/test_<slug>.py (pytest) and fix until it passes.",
                "Finished modules are stored in backend/kpi/generated.",
                "Export `SOURCE`, `load_<slug>_rows(ctx)`, `score_<slug>_kpi(rows, ...)`",
                "and `compute_<slug>_kpi(ctx)` = load then score.",
                "Daily run calls compute only. Extractor hands rows to the calculator.",
                "Tests: FakeCtx for compute/load, dict fixtures for score. No live 1C/Outlook.",
                "Never ask schedule, Outlook cadence, or when to run the agent.",
                "Do not create live 1C documents.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _collect_kpi_modules(run_cwd: Path) -> list[dict[str, Any]]:
    generated = run_cwd / "generated"
    tests = run_cwd / "tests"
    modules: list[dict[str, Any]] = []
    if not generated.is_dir():
        return modules
    for path in sorted(generated.glob("*.py")):
        if path.name in {"__init__.py"} or path.name.startswith("test_"):
            continue
        stem = path.stem
        test_path = tests / f"test_{stem}.py"
        if not test_path.exists():
            test_path = generated / f"test_{stem}.py"
        modules.append(
            {
                "metric_code": stem,
                "module": f"kpi.generated.{stem}",
                "code_text": path.read_text(encoding="utf-8"),
                "tests": test_path.read_text(encoding="utf-8") if test_path.exists() else "",
            }
        )
    return modules


def _kpi_artifacts_ready(run_cwd: Path) -> bool:
    modules = _collect_kpi_modules(run_cwd)
    return bool(modules) and all(str(item.get("tests") or "").strip() for item in modules)


def _kpi_slug_ready(run_cwd: Path, slug: str) -> bool:
    name = (slug or "").strip()
    if not name:
        return False
    root = Path(run_cwd)
    module = root / "generated" / f"{name}.py"
    test = root / "tests" / f"test_{name}.py"
    return module.is_file() and bool(module.read_text(encoding="utf-8").strip()) and test.is_file() and bool(
        test.read_text(encoding="utf-8").strip()
    )


def _existing_kpi_slugs(run_cwd: Path) -> list[str]:
    return [
        str(item.get("metric_code") or "").strip()
        for item in _collect_kpi_modules(run_cwd)
        if str(item.get("metric_code") or "").strip() and str(item.get("tests") or "").strip()
    ]


def _run_kpi_slug_tests(run_cwd: Path, slug: str) -> tuple[bool, str]:
    root = Path(run_cwd)
    _promote_kpi_artifacts(root)
    name = (slug or "").strip()
    if not name:
        return False, "slug пустой"
    test = root / "tests" / f"test_{name}.py"
    if not test.is_file() or not test.read_text(encoding="utf-8").strip():
        return False, f"Нет tests/test_{name}.py"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root), str(_backend_kpi_root().parent), env.get("PYTHONPATH") or ""]
    )
    from app.tools.ac.code_execution_tools import pytest_command_prefix

    try:
        completed = subprocess.run(
            [*pytest_command_prefix(), "-m", "pytest", str(test.relative_to(root)), "-q"],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        log("kpi slug pytest failed to start: " + repr(exc))
        return False, repr(exc)
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode != 0:
        log("kpi slug pytest failed: " + _ascii(output[:800]))
        return False, output
    return True, output or "passed"


def _promote_kpi_artifacts(run_cwd: Path) -> None:
    from app.tools.ac.code_execution_tools import promote_kpi_artifacts

    promote_kpi_artifacts(Path(run_cwd))


def _pytest_argv() -> list[str]:
    from app.tools.ac.code_execution_tools import pytest_command_prefix

    return [*pytest_command_prefix(), "-m", "pytest", "tests", "-q"]


def _run_kpi_workspace_tests(run_cwd: Path) -> tuple[bool, str]:
    root = Path(run_cwd)
    _promote_kpi_artifacts(root)
    modules = _collect_kpi_modules(root)
    if modules and any(not str(item.get("tests") or "").strip() for item in modules):
        missing = ", ".join(
            str(item.get("metric_code") or "")
            for item in modules
            if not str(item.get("tests") or "").strip()
        )
        return False, f"Нет tests/test_<slug>.py для: {missing}"
    tests = root / "tests"
    if not tests.is_dir() or not any(tests.glob("test_*.py")):
        return True, ""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(run_cwd), str(_backend_kpi_root().parent), env.get("PYTHONPATH") or ""]
    )
    try:
        completed = subprocess.run(
            _pytest_argv(),
            cwd=str(run_cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        log("kpi pytest failed to start: " + repr(exc))
        return False, repr(exc)
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode != 0:
        log("kpi pytest failed: " + _ascii(output[:800]))
        return False, output
    return True, output or "passed"


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
            elif ctype in {
                "design",
                "readiness",
                "demo",
                "run",
                "check_trigger",
                "form_orchestrator",
                "calc_orchestrator",
                "kpi_module",
            }:
                sidecar.start(ctype, command)
            elif ctype == "answer":
                sidecar.answer(command)
            elif ctype == "hitl":
                sidecar.hitl(command)
            elif ctype == "skip":
                sidecar.skip(command)
            elif ctype == "read_calendar":
                sidecar.read_calendar(command)
            elif ctype == "search_mail":
                sidecar.search_mail(command)
            elif ctype == "invoke_ac_tool":
                sidecar.invoke_ac_tool_cmd(command)
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
            emit(
                {
                    "type": "error",
                    "runId": str(command.get("id") or ""),
                    "message": _exc_text(exc, "Ошибка обработки команды локального агента"),
                }
            )


if __name__ == "__main__":
    main()
