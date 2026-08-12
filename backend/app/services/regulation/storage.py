from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.models.regulation import RegulationDocument
from app.schemas.regulation import RegulationParseResult


def new_regulation_id() -> str:
    return f"reg-{uuid4().hex[:12]}"


def save_upload(*, regulation_id: str, filename: str, data: bytes) -> Path:
    storage = settings.regulation_storage_dir / regulation_id
    storage.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or "regulation.bin").name
    path = storage / safe_name
    path.write_bytes(data)
    return path


def save_result(
    db: Session,
    *,
    regulation_id: str,
    user_id: str,
    filename: str,
    content_type: str,
    storage_path: Path,
    result: RegulationParseResult,
) -> RegulationDocument:
    doc = RegulationDocument(
        id=regulation_id,
        user_id=user_id,
        file_name=filename,
        content_type=content_type,
        storage_path=str(storage_path),
        is_scan=result.isScan,
        result_json=result.model_dump(mode="json"),
    )
    # merge() returns the session-managed instance; refresh the returned object.
    doc = db.merge(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_document(db: Session, *, regulation_id: str, user_id: str) -> RegulationDocument | None:
    return (
        db.query(RegulationDocument)
        .filter(RegulationDocument.id == regulation_id, RegulationDocument.user_id == user_id)
        .first()
    )
