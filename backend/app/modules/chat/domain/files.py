from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.modules.chat.crypto import decrypt_bytes, encrypt_bytes, is_encrypted_file


def staging_dir(user_id: str) -> Path:
    path = settings.chat_storage_dir / "staging" / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_staging(user_id: str, filename: str, data: bytes, mime: str = "") -> dict:
    file_id = uuid4().hex
    dest = staging_dir(user_id) / file_id
    dest.write_bytes(encrypt_bytes(data))
    meta = dest.with_suffix(".name")
    meta.write_text(f"{filename}\n{mime}\n{len(data)}", encoding="utf-8")
    return {"file_id": file_id, "filename": filename, "mime": mime, "size": len(data)}


def take_staging(user_id: str, file_id: str, message_id: str) -> dict | None:
    src = staging_dir(user_id) / file_id
    meta = src.with_suffix(".name")
    if not src.is_file():
        return None
    filename, mime, size_s = "file", "", "0"
    if meta.is_file():
        parts = meta.read_text(encoding="utf-8").splitlines()
        filename = parts[0] if parts else "file"
        mime = parts[1] if len(parts) > 1 else ""
        size_s = parts[2] if len(parts) > 2 else str(src.stat().st_size)
    dest_dir = settings.chat_storage_dir / "files" / message_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file_id
    shutil.move(str(src), str(dest))
    if meta.is_file():
        meta.unlink(missing_ok=True)
    return {
        "id": file_id,
        "filename": filename,
        "mime": mime,
        "size": int(size_s or 0),
        "storage_path": str(dest),
    }


def resolve_stored(path: str) -> Path | None:
    raw = Path(path)
    if raw.is_file():
        return raw
    return None
