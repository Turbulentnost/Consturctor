"""1C scans come without an extension: readers must still see them as PDF/Word."""

from __future__ import annotations

from pathlib import Path

from app.tools.ac.readable_files import suffix_from_bytes, with_detected_suffix


def test_suffix_from_bytes() -> None:
    assert suffix_from_bytes(b"%PDF-1.7") == ".pdf"
    assert suffix_from_bytes(b"\xff\xd8\xff\xe0") == ".jpg"
    assert suffix_from_bytes(b"PK\x03\x04....word/document.xml") == ".docx"
    assert suffix_from_bytes(b"plain text") == ""


def test_file_without_extension_gets_a_typed_copy(tmp_path: Path) -> None:
    raw = tmp_path / "doc02715420260929090414"
    raw.write_bytes(b"%PDF-1.7\nscan")

    picked = with_detected_suffix(raw)

    assert picked.name == "doc02715420260929090414.pdf"
    assert picked.read_bytes() == raw.read_bytes()


def test_file_with_extension_is_left_as_is(tmp_path: Path) -> None:
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7")
    assert with_detected_suffix(path) == path
