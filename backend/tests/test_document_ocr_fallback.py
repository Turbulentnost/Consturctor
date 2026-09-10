from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.workflows.document import DocumentError, _read_pdf_bytes


def test_read_pdf_bytes_returns_text_layer_without_ocr() -> None:
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello SD package checklist")
    raw = doc.tobytes()
    doc.close()
    text = _read_pdf_bytes(raw)
    assert "Hello SD package" in text


def test_read_pdf_bytes_ocr_fallback_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")

    doc = fitz.open()
    doc.new_page()
    raw = doc.tobytes()
    doc.close()

    class _Block:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Extracted:
        blocks = [_Block("OCR line from scan")]

    with patch("app.services.regulation.detect.is_scan_pdf", return_value=(True, 1)):
        with patch("app.services.regulation.pdf_ocr.extract_pdf_scan", return_value=_Extracted()):
            text = _read_pdf_bytes(raw)
    assert "OCR line from scan" in text
