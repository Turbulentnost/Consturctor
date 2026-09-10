from __future__ import annotations

from pathlib import Path

from app.attachment_text import extract_attachment_text, write_extracted_sidecar


def test_extract_txt(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("повестка", encoding="utf-8")
    assert extract_attachment_text(str(source)) == "повестка"


def test_write_extracted_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "kit.txt"
    source.write_text("смета", encoding="utf-8")
    sidecar = Path(write_extracted_sidecar(source))
    assert sidecar.name == "kit.txt.txt"
    assert sidecar.read_text(encoding="utf-8") == "смета"


def test_unreadable_image_without_ocr(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.attachment_text._ocr", lambda path: "")
    source = tmp_path / "scan.png"
    source.write_bytes(b"\x89PNG\r\n")
    text = extract_attachment_text(str(source))
    assert "текст не извлечён" in text
    assert write_extracted_sidecar(source) == ""
