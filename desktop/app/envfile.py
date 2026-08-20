"""Чтение .env без падения на Windows-1251 / UTF-8."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False


def decode_env_bytes(data: bytes) -> str:
    """Декодировать .env: UTF-8 (с BOM), иначе Windows-1251."""
    if not data:
        return ""
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    for encoding in ("utf-8", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1251", errors="replace")


def read_env_text(path: Path) -> str:
    """Прочитать текст .env в любой типичной Windows-кодировке."""
    return decode_env_bytes(path.read_bytes())


def write_env_text(path: Path, text: str) -> None:
    """Записать .env в UTF-8 с BOM, чтобы Inno Setup и Notepad узнали кодировку."""
    path.write_text(text, encoding="utf-8-sig", newline="\n")


def load_env_file(path: Path, *, override: bool = False) -> bool:
    """Загрузить переменные из .env, не падая на cp1251."""
    if not path.is_file():
        return False
    return bool(load_dotenv(stream=StringIO(read_env_text(path)), override=override))
