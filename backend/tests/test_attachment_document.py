from __future__ import annotations

import pytest

from app.services import ocr_extract
from app.services.cursor_sdk_local import CursorSdkLocalError
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
        "app.services.ocr_extract.extract_pdf_text",
        lambda name, raw: "Смета этапа 1",
    )
    loaded = load_attachment_bytes("scan.pdf", b"%PDF-1.3 extra")
    assert loaded["text"] == "Смета этапа 1"
    assert loaded["kind"] == "text"
    assert loaded["ocr_error"] == ""


def test_load_pdf_reports_ocr_error(monkeypatch) -> None:
    def boom(name, raw):
        raise ocr_extract.OcrError("Cursor SDK не распознал страниц(ы) 2 из 3")

    monkeypatch.setattr("app.services.ocr_extract.extract_pdf_text", boom)
    loaded = load_attachment_bytes("scan.pdf", b"%PDF-1.3 extra")
    assert "страниц(ы) 2" in loaded["ocr_error"]
    assert loaded["text_extracted"] is False


def _scan_pdf(pages: int) -> bytes:
    import fitz

    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    raw = doc.tobytes()
    doc.close()
    return raw


def test_cursor_ocr_recognizes_every_page(monkeypatch) -> None:
    monkeypatch.setattr(ocr_extract.settings, "ocr_provider", "cursor_sdk")
    monkeypatch.setattr(ocr_extract.settings, "cursor_ocr_pages_per_batch", 2)
    calls: list[list[int]] = []

    def fake_sdk(prompt, *, images, model, timeout):
        pages = [item["page"] for item in images]
        calls.append(pages)
        return "\n".join(f"===PAGE {page}===\nТекст страницы {page}" for page in pages)

    monkeypatch.setattr(ocr_extract, "run_cursor_sdk", fake_sdk)
    text = ocr_extract.extract_pdf_text("scan.pdf", _scan_pdf(5))
    assert sorted(page for batch in calls for page in batch) == [1, 2, 3, 4, 5]
    for page in range(1, 6):
        assert f"Текст страницы {page}" in text
    assert text.index("страницы 1") < text.index("страницы 5")


def test_cursor_ocr_retries_missed_page(monkeypatch) -> None:
    monkeypatch.setattr(ocr_extract.settings, "ocr_provider", "cursor_sdk")
    monkeypatch.setattr(ocr_extract.settings, "cursor_ocr_pages_per_batch", 3)

    def fake_sdk(prompt, *, images, model, timeout):
        pages = [item["page"] for item in images]
        if len(pages) > 1:
            return "===PAGE 1===\nПервая"
        return f"Одиночная {pages[0]}"

    monkeypatch.setattr(ocr_extract, "run_cursor_sdk", fake_sdk)
    text = ocr_extract.extract_pdf_text("scan.pdf", _scan_pdf(3))
    assert "Первая" in text
    assert "Одиночная 2" in text
    assert "Одиночная 3" in text


def test_cursor_ocr_fails_when_page_is_lost(monkeypatch) -> None:
    monkeypatch.setattr(ocr_extract.settings, "ocr_provider", "cursor_sdk")
    monkeypatch.setattr(ocr_extract.settings, "cursor_ocr_pages_per_batch", 3)

    def fake_sdk(prompt, *, images, model, timeout):
        pages = [item["page"] for item in images]
        if 2 in pages and len(pages) == 1:
            raise CursorSdkLocalError("timeout")
        return "\n".join(f"===PAGE {p}===\nOK {p}" for p in pages if p != 2)

    monkeypatch.setattr(ocr_extract, "run_cursor_sdk", fake_sdk)
    with pytest.raises(ocr_extract.OcrError, match="2 из 3"):
        ocr_extract.extract_pdf_text("scan.pdf", _scan_pdf(3))


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
