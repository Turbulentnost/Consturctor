from __future__ import annotations

from pathlib import Path


class RegulationExtractError(RuntimeError):
    pass


def extract_text(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        raise RegulationExtractError(f"Файл не найден: {file_path}")

    suffix = file_path.suffix.casefold()
    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="replace").strip()
    if suffix == ".docx":
        return _extract_docx(file_path)
    if suffix == ".pdf":
        return _extract_pdf(file_path)
    if suffix == ".doc":
        raise RegulationExtractError("Формат .doc не поддерживается — сохраните как .docx")
    raise RegulationExtractError(f"Неподдерживаемый формат: {suffix}")


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RegulationExtractError("Установите python-docx") from exc
    doc = Document(str(path))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n".join(parts).strip()


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RegulationExtractError("Установите pypdf") from exc
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts).strip()
