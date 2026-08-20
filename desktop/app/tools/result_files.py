"""Файлы-результаты инструментов: Excel и другие документы для пользователя."""

from __future__ import annotations

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
_PATH_KEYS = ("path", "file", "absolute_path", "filepath", "dest", "workspace_path")
_remembered: dict[str, list[str]] = {}
_pending_attach: list[tuple[str, str]] = []


def is_document_path(path: Path) -> bool:
    return path.suffix.lower() in DOCUMENT_SUFFIXES


def extract_result_files(result: object, *, tool: str = "") -> list[Path]:
    """Локальные документы из ответа инструмента — только существующие файлы."""
    if (tool or "").strip() in _SKIP_TOOLS:
        return []
    if not isinstance(result, dict):
        return []
    found: list[Path] = []
    seen: set[str] = set()

    def _add(raw: object) -> None:
        path = _as_document(raw)
        if path is None:
            return
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        found.append(path)

    for key in _PATH_KEYS:
        _add(result.get(key))
    filename = result.get("filename")
    if filename and result.get("path"):
        _add(result.get("path"))
    files = result.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict):
                for key in _PATH_KEYS:
                    _add(item.get(key))
                _add(item.get("name"))
            else:
                _add(item)
    return found


def _as_document(raw: object) -> Path | None:
    text = str(raw or "").strip()
    if not text or text in {".", ".."} or "\n" in text:
        return None
    path = Path(text)
    if not path.is_absolute():
        return None
    try:
        path = path.resolve()
    except OSError:
        return None
    if not path.is_file() or not is_document_path(path):
        return None
    return path


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
    files = extract_result_files(result, tool=tool)
    if not files:
        return
    remember_result_files(files, workflow_id=workflow_id)
    from app.ui.widgets.result_file_card import offer_result_files

    offer_result_files(files, workflow_id=workflow_id)
