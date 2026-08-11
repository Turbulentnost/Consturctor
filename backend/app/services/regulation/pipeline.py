from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.schemas.regulation import RegulationParseResult
from app.services.regulation.detect import is_scan_pdf
from app.services.regulation.docx_extract import extract_docx
from app.services.regulation.pdf_ocr import extract_pdf_scan
from app.services.regulation.pdf_text import extract_pdf_text
from app.services.regulation.storage import (
    get_document,
    new_regulation_id,
    save_result,
    save_upload,
)
from app.services.regulation.structure import build_result
from app.services.regulation.text_extract import extract_text_file
from app.services.regulation.types import ExtractedDocument
from app.services.regulation.xlsx_extract import extract_xlsx

_SUPPORTED = {".docx", ".pdf", ".xlsx", ".md", ".txt"}


class RegulationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def parse_upload(
    db: Session,
    *,
    user_id: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> RegulationParseResult:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".doc":
        raise RegulationError("Формат DOC не поддерживается. Сохраните файл как DOCX.")
    if suffix not in _SUPPORTED:
        raise RegulationError("Поддерживаются файлы: DOCX, PDF, XLSX, MD, TXT.")
    if not data:
        raise RegulationError("Файл пустой")

    regulation_id = new_regulation_id()
    path = save_upload(regulation_id=regulation_id, filename=filename, data=data)
    try:
        extracted = _extract(path, suffix=suffix, regulation_id=regulation_id)
        result = build_result(regulation_id=regulation_id, filename=filename, extracted=extracted)
    except RegulationError:
        raise
    except RuntimeError as exc:
        raise RegulationError(str(exc), status_code=503) from exc
    except Exception as exc:  # noqa: BLE001 - user-facing upload endpoint.
        raise RegulationError(f"Не удалось разобрать регламент: {exc}", status_code=500) from exc

    try:
        save_result(
            db,
            regulation_id=regulation_id,
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            storage_path=path,
            result=result,
        )
    except Exception as exc:  # noqa: BLE001
        raise RegulationError(
            f"Не удалось сохранить результат распознавания: {exc}",
            status_code=500,
        ) from exc
    return result


def get_result(db: Session, *, regulation_id: str, user_id: str) -> RegulationParseResult:
    doc = get_document(db, regulation_id=regulation_id, user_id=user_id)
    if doc is None:
        raise RegulationError("Регламент не найден", status_code=404)
    return RegulationParseResult.model_validate(doc.result_json)


def _extract(path: Path, *, suffix: str, regulation_id: str) -> ExtractedDocument:
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".xlsx":
        return extract_xlsx(path)
    if suffix in {".md", ".txt"}:
        return extract_text_file(path)
    if suffix == ".pdf":
        is_scan, _page_count = is_scan_pdf(path)
        if is_scan:
            return extract_pdf_scan(path, work_dir=path.parent)
        return extract_pdf_text(path)
    raise RegulationError(f"Формат {suffix} не поддерживается")
