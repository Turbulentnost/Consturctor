"""Пути к файлам, которые агент может читать: workspace и кэш 1С."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.tools.ac.agent_workspace import AgentWorkspace, WorkspaceError

ARTIFACT_DIR_NAME = "constructor-onec-artifacts"

WORD_SUFFIXES = {".docx"}
PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
READABLE_SUFFIXES = WORD_SUFFIXES | PDF_SUFFIXES | IMAGE_SUFFIXES | {".doc"}


def artifact_cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / ARTIFACT_DIR_NAME


def kind_for_suffix(suffix: str) -> str:
    folded = (suffix or "").strip().lower()
    if folded in WORD_SUFFIXES or folded == ".doc":
        return "word"
    if folded in PDF_SUFFIXES:
        return "pdf"
    if folded in IMAGE_SUFFIXES:
        return "image"
    if folded in EXCEL_SUFFIXES:
        return "excel"
    return ""


def read_tool_for_suffix(suffix: str) -> str:
    kind = kind_for_suffix(suffix)
    if kind == "excel":
        return "excel.read_workbook"
    if kind in {"word", "pdf", "image"}:
        return "office.read_file"
    return ""


def is_allowed_external(path: Path) -> bool:
    resolved = path.resolve()
    cache = artifact_cache_dir().resolve()
    return cache == resolved or cache in resolved.parents


def first_document_in(folder: Path) -> Path | None:
    """Если передали папку — взять первый PDF/Word/картинку внутри."""
    if not folder.is_dir():
        return None
    docs = [
        path
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in READABLE_SUFFIXES
    ]
    return docs[0] if docs else None


def resolve_readable_path(workspace: AgentWorkspace, filename: object) -> Path:
    raw = str(filename or "").strip()
    if not raw:
        raise WorkspaceError("Укажи filename или saved_path файла.")
    candidate = Path(raw)
    if candidate.is_absolute():
        if candidate.is_file() and is_allowed_external(candidate):
            return candidate.resolve()
        raise WorkspaceError(
            "Вне рабочей папки можно читать только файлы из "
            f"{artifact_cache_dir()} (saved_path после onec.download_artifact)."
        )
    folder = workspace.directory / raw.replace("\\", "/")
    picked = first_document_in(folder)
    if picked is not None:
        return picked.resolve()
    try:
        path = workspace.resolve(raw, must_exist=True)
    except WorkspaceError:
        cached = artifact_cache_dir() / Path(raw).name
        if cached.is_file():
            return cached.resolve()
        raise
    if path.is_dir():
        nested = first_document_in(path)
        if nested is not None:
            return nested.resolve()
    return path
