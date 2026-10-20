from __future__ import annotations

import mimetypes
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.vendors.aiagentback.tools.fs.paths import (
    ensure_under_allowed_roots,
    normalize_path_str,
    parse_allowed_roots,
    to_path,
)
from app.vendors.aiagentback.tools.fs.resolve import ResolveResult, resolve_path

FsOperation = Literal["resolve", "list", "read"]

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".log",
    ".ini",
    ".cfg",
    ".yml",
    ".yaml",
    ".py",
    ".js",
    ".ts",
    ".css",
    ".sql",
    ".rtf",
}


def _iso_mtime(path: Path) -> str | None:
    try:
        ts = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def list_directory(
    path: str,
    *,
    allowed_roots: list[str] | tuple[str, ...] | str | None,
    max_entries: int = 200,
    min_score: float = 0.72,
    max_candidates: int = 8,
    max_search_entries: int = 5000,
) -> dict[str, Any]:
    resolved = resolve_path(
        path,
        allowed_roots=allowed_roots,
        min_score=min_score,
        max_candidates=max_candidates,
        max_entries=max_search_entries,
    )
    if not resolved.ok or not resolved.resolved_path:
        return {
            "operation": "list",
            "ok": False,
            "resolved_path": resolved.resolved_path,
            "match_type": resolved.match_type,
            "score": resolved.score,
            "candidates": [asdict(c) for c in resolved.candidates],
            "entries": [],
            "truncated": False,
            "hint": _resolve_hint(resolved),
        }

    target = to_path(resolved.resolved_path)
    if not target.is_dir():
        raise ValueError(f"Путь не является каталогом: {resolved.resolved_path}")

    roots = parse_allowed_roots(allowed_roots)
    ensure_under_allowed_roots(str(target), roots)

    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(target) as iterator:
            for index, entry in enumerate(iterator):
                if index >= max_entries:
                    truncated = True
                    break
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    size = entry.stat(follow_symlinks=False).st_size if not is_dir else None
                except OSError:
                    is_dir = False
                    size = None
                entries.append(
                    {
                        "name": entry.name,
                        "path": str(Path(entry.path)),
                        "is_dir": is_dir,
                        "size": size,
                        "modified_at": _iso_mtime(Path(entry.path)),
                    }
                )
    except OSError as exc:
        raise ValueError(f"Не удалось прочитать каталог: {exc}") from exc

    entries.sort(key=lambda item: (not item["is_dir"], (item["name"] or "").casefold()))
    return {
        "operation": "list",
        "ok": True,
        "resolved_path": resolved.resolved_path,
        "match_type": resolved.match_type,
        "score": resolved.score,
        "candidates": [asdict(c) for c in resolved.candidates],
        "entries": entries,
        "truncated": truncated,
        "hint": None,
    }


def _decode_text(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _extract_pdf_text(data: bytes, *, max_chars: int = 100_000) -> str | None:
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return None
    parts: list[str] = []
    total = 0
    try:
        for page in doc:
            text = page.get_text() or ""
            parts.append(text)
            total += len(text)
            if total >= max_chars:
                break
    finally:
        doc.close()
    joined = "\n".join(parts).strip()
    if not joined:
        return None
    return joined[:max_chars]


def read_file(
    path: str,
    *,
    allowed_roots: list[str] | tuple[str, ...] | str | None,
    query: str | None = None,
    max_bytes: int = 2_000_000,
    min_score: float = 0.72,
    max_candidates: int = 8,
    max_search_entries: int = 5000,
) -> dict[str, Any]:
    resolved = resolve_path(
        path,
        allowed_roots=allowed_roots,
        query=query,
        min_score=min_score,
        max_candidates=max_candidates,
        max_entries=max_search_entries,
    )
    if not resolved.ok or not resolved.resolved_path:
        return {
            "operation": "read",
            "ok": False,
            "resolved_path": resolved.resolved_path,
            "match_type": resolved.match_type,
            "score": resolved.score,
            "candidates": [asdict(c) for c in resolved.candidates],
            "name": None,
            "size": None,
            "content_type": None,
            "encoding": None,
            "text": None,
            "content_truncated": False,
            "hint": _resolve_hint(resolved),
        }

    target = to_path(resolved.resolved_path)
    roots = parse_allowed_roots(allowed_roots)
    ensure_under_allowed_roots(str(target), roots)

    if not target.is_file():
        raise ValueError(f"Путь не является файлом: {resolved.resolved_path}")

    try:
        size = target.stat().st_size
    except OSError as exc:
        raise ValueError(f"Не удалось получить размер файла: {exc}") from exc

    content_type, _ = mimetypes.guess_type(target.name)
    suffix = target.suffix.casefold()
    limit = max(1, int(max_bytes))

    try:
        with target.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise ValueError(f"Не удалось прочитать файл: {exc}") from exc

    content_truncated = len(data) > limit or size > limit
    data = data[:limit]

    text: str | None = None
    encoding: str | None = None
    hint: str | None = None

    if suffix == ".pdf":
        text = _extract_pdf_text(data)
        encoding = "pdf-text" if text else None
        if text is None:
            hint = "Бинарный PDF: текст не извлечён (нет текстового слоя или ошибка чтения)."
        elif content_truncated:
            hint = "Содержимое обрезано по лимиту байт."
    elif suffix in TEXT_EXTENSIONS or (content_type or "").startswith("text/"):
        text, encoding = _decode_text(data)
        if content_truncated:
            hint = "Содержимое обрезано по лимиту байт."
    else:
        hint = "Бинарный файл: содержимое не возвращается, только метаданные."

    return {
        "operation": "read",
        "ok": True,
        "resolved_path": normalize_path_str(str(target)),
        "match_type": resolved.match_type,
        "score": resolved.score,
        "candidates": [asdict(c) for c in resolved.candidates],
        "name": target.name,
        "size": size,
        "content_type": content_type,
        "encoding": encoding,
        "text": text,
        "content_truncated": content_truncated,
        "hint": hint,
    }


def _resolve_hint(resolved: ResolveResult) -> str | None:
    if resolved.match_type == "ambiguous":
        return "Найдено несколько кандидатов — уточните path или query."
    if resolved.match_type == "not_found":
        return "Путь не найден. Проверьте имя или укажите более полный path."
    return None


_DOCUMENT_SUFFIXES = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".xlsm",
    ".txt",
    ".csv",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".webp",
    ".msg",
    ".pptx",
}


def resolve_readable_file(
    path: str,
    *,
    allowed_roots: list[str] | tuple[str, ...] | str | None,
    query: str | None = None,
    min_score: float = 0.72,
    max_candidates: int = 8,
    max_search_entries: int = 5000,
) -> Path:
    """Resolve path/query to an existing file under allowed roots.

    Supports: exact file, directory + filename query, directory with a single
    document, or bare filename search under roots.
    """
    roots = parse_allowed_roots(allowed_roots)
    if not roots:
        raise ValueError("Не заданы разрешённые корни FS_ALLOWED_ROOTS")

    resolved = resolve_path(
        path or "",
        allowed_roots=roots,
        query=query,
        min_score=min_score,
        max_candidates=max_candidates,
        max_entries=max_search_entries,
    )
    if not resolved.ok or not resolved.resolved_path:
        hint = _resolve_hint(resolved) or "Путь не найден"
        raise ValueError(hint)

    target = to_path(resolved.resolved_path)
    ensure_under_allowed_roots(str(target), roots)

    if target.is_file():
        return target

    if target.is_dir():
        if query:
            nested = resolve_path(
                str(target),
                allowed_roots=roots,
                query=query,
                min_score=min_score,
                max_candidates=max_candidates,
                max_entries=max_search_entries,
            )
            if nested.ok and nested.resolved_path:
                nested_path = to_path(nested.resolved_path)
                ensure_under_allowed_roots(str(nested_path), roots)
                if nested_path.is_file():
                    return nested_path

        documents: list[Path] = []
        try:
            for entry in sorted(target.iterdir(), key=lambda item: item.name.casefold()):
                if entry.is_file() and entry.suffix.casefold() in _DOCUMENT_SUFFIXES:
                    documents.append(entry)
        except OSError as exc:
            raise ValueError(f"Не удалось прочитать каталог: {exc}") from exc

        if len(documents) == 1:
            return documents[0]
        if len(documents) > 1:
            names = ", ".join(item.name for item in documents[:5])
            raise ValueError(
                "В каталоге несколько файлов — уточните имя файла. "
                f"Найдено: {names}"
            )
        raise ValueError("В каталоге нет файлов для открытия")

    raise ValueError(f"Путь не является файлом: {resolved.resolved_path}")


def run_filesystem(
    *,
    operation: FsOperation,
    path: str,
    allowed_roots: list[str] | tuple[str, ...] | str | None,
    query: str | None = None,
    max_bytes: int | None = None,
    max_list_entries: int = 200,
    min_score: float = 0.72,
    max_candidates: int = 8,
    max_search_entries: int = 5000,
    default_max_read_bytes: int = 2_000_000,
) -> dict[str, Any]:
    op = (operation or "").strip().lower()
    if op not in {"resolve", "list", "read"}:
        raise ValueError("operation должен быть resolve, list или read")

    if op == "resolve":
        resolved = resolve_path(
            path,
            allowed_roots=allowed_roots,
            query=query,
            min_score=min_score,
            max_candidates=max_candidates,
            max_entries=max_search_entries,
        )
        return {
            "operation": "resolve",
            "ok": resolved.ok,
            "resolved_path": resolved.resolved_path,
            "match_type": resolved.match_type,
            "score": resolved.score,
            "candidates": [asdict(c) for c in resolved.candidates],
            "entries": [],
            "truncated": False,
            "name": None,
            "size": None,
            "content_type": None,
            "encoding": None,
            "text": None,
            "content_truncated": False,
            "hint": _resolve_hint(resolved),
        }

    if op == "list":
        result = list_directory(
            path,
            allowed_roots=allowed_roots,
            max_entries=max_list_entries,
            min_score=min_score,
            max_candidates=max_candidates,
            max_search_entries=max_search_entries,
        )
        result.setdefault("name", None)
        result.setdefault("size", None)
        result.setdefault("content_type", None)
        result.setdefault("encoding", None)
        result.setdefault("text", None)
        result.setdefault("content_truncated", False)
        return result

    limit = default_max_read_bytes if max_bytes is None else min(int(max_bytes), default_max_read_bytes)
    if limit < 1:
        raise ValueError("max_bytes должен быть >= 1")
    result = read_file(
        path,
        allowed_roots=allowed_roots,
        query=query,
        max_bytes=limit,
        min_score=min_score,
        max_candidates=max_candidates,
        max_search_entries=max_search_entries,
    )
    result.setdefault("entries", [])
    result.setdefault("truncated", False)
    return result
