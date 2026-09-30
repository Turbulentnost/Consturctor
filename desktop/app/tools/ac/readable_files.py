"""Пути к файлам, которые агент может читать: workspace и кэш 1С."""

from __future__ import annotations

import shutil
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


def suffix_from_bytes(content: bytes) -> str:
    """1C file cards often come without an extension; readers pick the parser by suffix."""
    if content.startswith(b"%PDF"):
        return ".pdf"
    if content[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if content.startswith(b"\x89PNG"):
        return ".png"
    if content[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    if content[:2] == b"PK":
        head = content[:4096]
        if b"word/" in head:
            return ".docx"
        if b"xl/" in head:
            return ".xlsx"
        if b"ppt/" in head:
            return ".pptx"
        return ".zip"
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        return ".doc"
    return ""


def with_detected_suffix(path: Path) -> Path:
    """A file without extension gets a sibling copy named by its content type."""
    if path.suffix or not path.is_file():
        return path
    try:
        with path.open("rb") as handle:
            suffix = suffix_from_bytes(handle.read(4096))
    except OSError:
        return path
    if not suffix:
        return path
    target = path.with_name(path.name + suffix)
    if not target.exists():
        try:
            shutil.copy2(path, target)
        except OSError:
            return path
    return target


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
