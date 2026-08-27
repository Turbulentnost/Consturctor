"""Файлы-результаты инструментов: Excel и другие документы для пользователя."""

from __future__ import annotations

import re
from pathlib import Path

DOCUMENT_SUFFIXES = frozenset(
    {
        ".xlsx",
        ".xls",
        ".xlsm",
        ".csv",
        ".docx",
        ".doc",
        ".pdf",
        ".odt",
        ".pptx",
        ".ppt",
        ".rtf",
        ".txt",
        ".md",
        ".json",
        ".xml",
    }
)
_SKIP_TOOLS = frozenset(
    {
        "excel.list_files",
        "excel.read_workbook",
        "code.write_python",
        "code.run_python",
    }
)
_OUTPUT_SKIP_DIRS = frozenset({"materials", "code", "tool_results", "__pycache__"})
_OUTPUT_SKIP_NAMES = frozenset({"agents.md", "keepknowledgefile", "keep_knowledge_file"})
_PATH_KEYS = ("path", "file", "absolute_path", "filepath", "dest")
_FILE_IN_TEXT = re.compile(
    r"[A-Za-z0-9_.\-]+\.(?:xlsx|xls|xlsm|csv|docx|doc|pdf|pptx|txt|md)",
    re.IGNORECASE,
)
_remembered: dict[str, list[str]] = {}
_pending_attach: list[tuple[str, str]] = []


def is_document_path(path: Path) -> bool:
    return path.suffix.lower() in DOCUMENT_SUFFIXES


def _as_document(raw: object, *, workspace: Path | None = None) -> Path | None:
    text = str(raw or "").strip()
    if not text or text in {".", ".."} or "\n" in text:
        return None
    path = Path(text)
    if not path.is_absolute():
        if workspace is None:
            return None
        path = workspace / path.name
    try:
        path = path.resolve()
    except OSError:
        return None
    if workspace is not None:
        try:
            path.relative_to(workspace.resolve())
        except ValueError:
            return None
    if not path.is_file() or not is_document_path(path):
        return None
    return path


def workspace_for(workflow_id: str) -> Path | None:
    wid = (workflow_id or "").strip()
    if not wid:
        return None
    from app.tools.ac.dispatch import workspaces_root
    from app.tools.ac.agent_workspace import AgentWorkspace

    return AgentWorkspace(workspaces_root(), wid).directory


def collect_workspace_output_files(workflow_id: str) -> list[Path]:
    """Documents the agent wrote into the workspace, not inputs or tool dumps."""
    root = workspace_for(workflow_id)
    if root is None or not root.is_dir():
        return []
    found: list[Path] = []
    seen: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part.casefold() in _OUTPUT_SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if path.name.casefold() in _OUTPUT_SKIP_NAMES:
            continue
        if path.suffix.lower() == ".py":
            continue
        if not is_document_path(path):
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        found.append(path.resolve())
    return found


def extract_result_files(
    result: object,
    *,
    tool: str = "",
    workflow_id: str = "",
) -> list[Path]:
    """Локальные документы из ответа инструмента — только существующие файлы."""
    folded = (tool or "").strip()
    if folded == "code.run_python":
        return collect_workspace_output_files(workflow_id)
    if folded in _SKIP_TOOLS:
        return []
    if not isinstance(result, dict):
        return []
    workspace = workspace_for(workflow_id)
    found: list[Path] = []
    seen: set[str] = set()

    def _add(raw: object) -> None:
        path = _as_document(raw, workspace=workspace)
        if path is None:
            return
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        found.append(path)

    for key in _PATH_KEYS:
        _add(result.get(key))
    _add(result.get("filename"))
    files = result.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict):
                for key in _PATH_KEYS:
                    _add(item.get(key))
                _add(item.get("name"))
                _add(item.get("filename"))
            else:
                _add(item)
    return found


def remember_result_files(paths: list[Path], *, workflow_id: str = "") -> None:
    key = (workflow_id or "").strip() or "_"
    bucket = _remembered.setdefault(key, [])
    for path in paths:
        text = str(path)
        if text not in bucket:
            bucket.append(text)


def remembered_result_files(workflow_id: str = "") -> list[Path]:
    key = (workflow_id or "").strip() or "_"
    found: list[Path] = []
    for raw in _remembered.get(key, []):
        path = Path(raw)
        if path.is_file() and is_document_path(path):
            found.append(path)
    return found


def remembered_result_names(workflow_id: str = "") -> list[str]:
    return [path.name for path in remembered_result_files(workflow_id)]


def queue_unattached_result_file(path: Path, workflow_id: str = "") -> None:
    item = (str(path), str(workflow_id or ""))
    if item not in _pending_attach:
        _pending_attach.append(item)


def take_unattached_result_files() -> list[tuple[str, str]]:
    items = list(_pending_attach)
    _pending_attach.clear()
    return items


def clear_remembered_result_files(workflow_id: str = "") -> None:
    key = (workflow_id or "").strip() or "_"
    _remembered.pop(key, None)
    leftover = [item for item in _pending_attach if item[1] != (workflow_id or "")]
    _pending_attach.clear()
    _pending_attach.extend(leftover)


def publish_result_files(result: object, *, tool: str = "", workflow_id: str = "") -> None:
    files = extract_result_files(result, tool=tool, workflow_id=workflow_id)
    if not files:
        return
    remember_result_files(files, workflow_id=workflow_id)
    try:
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return
        from app.ui.widgets.result_file_card import offer_result_files
    except Exception:
        return
    offer_result_files(files, workflow_id=workflow_id)


def publish_answer_files(
    *,
    workflow_id: str,
    work: dict | None = None,
    text: str = "",
    arguments: dict | None = None,
    tool: str = "",
) -> None:
    """Прикрепить документы ответа: Excel/файлы прогона и текстовый итог."""
    wid = (workflow_id or "").strip()
    payload = dict(work or {})
    if arguments:
        for key in ("filename", "path", "file"):
            if arguments.get(key) and key not in payload:
                payload[key] = arguments.get(key)
    files = extract_result_files(payload, tool=tool, workflow_id=wid)
    files.extend(remembered_result_files(wid))
    name = str((arguments or {}).get("filename") or payload.get("filename") or "").strip()
    workspace = workspace_for(wid)
    if workspace is not None and name:
        extra = _as_document(name, workspace=workspace)
        if extra is not None:
            files.append(extra)
    if workspace is not None:
        for match in _FILE_IN_TEXT.findall(text or str(payload.get("text") or "")):
            extra = _as_document(match, workspace=workspace)
            if extra is not None:
                files.append(extra)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in files:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    answer = (text or str(payload.get("text") or "")).strip()
    if answer and workspace is not None:
        note = workspace / "Результат.md"
        try:
            note.write_text(answer, encoding="utf-8")
            unique.append(note)
        except OSError:
            pass
    if not unique:
        return
    remember_result_files(unique, workflow_id=wid)
    from app.ui.widgets.result_file_card import offer_result_files

    offer_result_files(unique, workflow_id=wid)
