from __future__ import annotations

from app.services.ocr_extract import compose_ocr_text
from app.services.regulation.types import ExtractedBlock, ExtractedTable
from app.services.workflows.document import load_attachment_bytes


def test_load_attachment_keeps_unknown_format() -> None:
    loaded = load_attachment_bytes("photo.heic", b"not-really")
    assert loaded["kind"] == "binary"
    assert "текст не извлечён" in loaded["text"]
    assert loaded["name"] == "photo.heic"


def test_load_attachment_image_uses_ocr(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.workflows.document._ocr_visual",
        lambda name, raw: "Повестка СД",
    )
    loaded = load_attachment_bytes("scan.png", b"\x89PNG\r\n" + b"x" * 20)
    assert loaded["kind"] == "image"
    assert loaded["text"] == "Повестка СД"
    assert loaded["data_b64"]


def test_load_empty_pdf_ocr_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.workflows.document._read_pdf_bytes",
        lambda raw: "",
    )
    monkeypatch.setattr(
        "app.services.workflows.document._ocr_visual",
        lambda name, raw: "Смета этапа 1",
    )
    loaded = load_attachment_bytes("scan.pdf", b"%PDF-1.3 extra")
    assert loaded["text"] == "Смета этапа 1"
    assert loaded["kind"] == "text"


def test_compose_ocr_text_joins_blocks_and_tables() -> None:
    text = compose_ocr_text(
        [
            ExtractedBlock(page=1, text="Повестка"),
            ExtractedBlock(
                page=1,
                table=ExtractedTable(headers=["Документ"], rows=[["Смета"]]),
            ),
        ]
    )
    assert "Повестка" in text
    assert "Документ" in text
    assert "Смета" in text
