"""Вложения к сообщению агенту: фотографии и файлы, сохраняемые в папку сессии."""

from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

FOLDER = "attachments"
MAX_FILES = 10
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 60 * 1024 * 1024
# Форматы, которые Cursor SDK принимает картинкой сообщения (SDKUserMessage.images).
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_NAME_CHARS = 120
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class AttachmentUpload(BaseModel):
    name: str
    mime: str = ""
    data: str


class Attachment(BaseModel):
    name: str
    # Относительно папки сессии, всегда внутри attachments/.
    path: str
    mime: str
    size: int
    image: bool


class AttachmentError(ValueError):
    pass


@dataclass
class DecodedFile:
    name: str
    mime: str
    content: bytes


def _safe_name(raw: str) -> str:
    name = _UNSAFE.sub("_", Path(raw.replace("\\", "/")).name).strip(" .")
    if len(name) > _NAME_CHARS:
        suffix = Path(name).suffix[:16]
        name = name[: _NAME_CHARS - len(suffix)] + suffix
    return name or "file"


def _mime(name: str, declared: str) -> str:
    value = declared.strip().lower()
    if value and "/" in value:
        return "image/jpeg" if value == "image/jpg" else value
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def decode(uploads: list[AttachmentUpload]) -> list[DecodedFile]:
    """Проверить все вложения до того, как что-то запускать или писать на диск."""
    if len(uploads) > MAX_FILES:
        raise AttachmentError(f"Не больше {MAX_FILES} вложений за сообщение")
    decoded: list[DecodedFile] = []
    total = 0
    for upload in uploads:
        name = _safe_name(upload.name)
        try:
            content = base64.b64decode(upload.data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AttachmentError(f"«{name}»: повреждённые данные файла") from exc
        if not content:
            raise AttachmentError(f"«{name}»: пустой файл")
        if len(content) > MAX_FILE_BYTES:
            raise AttachmentError(f"«{name}» больше {MAX_FILE_BYTES // 1_048_576} МБ")
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise AttachmentError(f"Вложения вместе больше {MAX_TOTAL_BYTES // 1_048_576} МБ")
        decoded.append(DecodedFile(name=name, mime=_mime(name, upload.mime), content=content))
    return decoded


def _free_path(folder: Path, name: str) -> Path:
    target = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    index = 2
    while target.exists():
        target = folder / f"{stem} ({index}){suffix}"
        index += 1
    return target


def save(workspace: Path, files: list[DecodedFile]) -> list[Attachment]:
    folder = workspace / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    saved: list[Attachment] = []
    for item in files:
        target = _free_path(folder, item.name)
        target.write_bytes(item.content)
        saved.append(
            Attachment(
                name=target.name,
                path=f"{FOLDER}/{target.name}",
                mime=item.mime,
                size=len(item.content),
                image=item.mime in IMAGE_TYPES,
            )
        )
    return saved


def resolve(workspace: Path, relative: str) -> Path | None:
    """Файл вложения по пути из события; None, если путь ведёт за пределы attachments/."""
    root = (workspace / FOLDER).resolve()
    target = (workspace / relative).resolve()
    if target.parent != root or not target.is_file():
        return None
    return target
