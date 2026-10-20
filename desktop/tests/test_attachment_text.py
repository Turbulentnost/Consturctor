from __future__ import annotations

from pathlib import Path

from app.attachment_text import extract_attachment_text, write_extracted_sidecar


class _FakeOle:
    def __init__(self, streams: dict[str, bytes]) -> None:
        self._streams = streams

    def __enter__(self) -> "_FakeOle":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def openstream(self, name: str):
        import io

        return io.BytesIO(self._streams[name])


def _word97(text: str, *, compressed: bool) -> dict[str, bytes]:
    import struct

    body_at = 0x400
    payload = text.encode("cp1252" if compressed else "utf-16-le")
    word = bytearray(body_at) + payload
    struct.pack_into("<H", word, 0x0A, 0x0200)
    fc = (body_at * 2) | 0x40000000 if compressed else body_at
    plc = struct.pack("<II", 0, len(text)) + struct.pack("<HIH", 0, fc, 0)
    clx = b"\x01" + struct.pack("<H", 2) + b"\x00\x00" + b"\x02" + struct.pack("<I", len(plc)) + plc
    struct.pack_into("<II", word, 0x01A2, 0, len(clx))
    return {"WordDocument": bytes(word), "1Table": clx}


def test_old_doc_unicode_text_with_table(tmp_path: Path, monkeypatch) -> None:
    import olefile

    import app.attachment_text as attachment_text

    streams = _word97("Извещение\rУтвердил\x07И.Б. Амураль\x07\r\x13 PAGE \x141\x15\r", compressed=False)
    monkeypatch.setattr(olefile, "OleFileIO", lambda path: _FakeOle(streams))
    monkeypatch.setattr(attachment_text, "_read_doc_via_word", lambda path: "")
    source = tmp_path / "notice.doc"
    source.write_bytes(b"\xd0\xcf\x11\xe0")

    assert extract_attachment_text(str(source)) == "Извещение\nУтвердил\tИ.Б. Амураль\n1"


def test_old_doc_compressed_text(tmp_path: Path, monkeypatch) -> None:
    import olefile

    from app.attachment_text import _read_doc_pieces

    streams = _word97("Signed by director\r", compressed=True)
    monkeypatch.setattr(olefile, "OleFileIO", lambda path: _FakeOle(streams))

    assert _read_doc_pieces(tmp_path / "x.doc") == "Signed by director"


def test_extract_pptx_slide_text(tmp_path: Path) -> None:
    import zipfile

    source = tmp_path / "deck.pptx"
    slide = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<a:t>концепция автоматизации</a:t></sld>"
    )
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)
    assert "концепция автоматизации" in extract_attachment_text(str(source))


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


def test_extract_image_skips_ocr_when_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.attachment_text._ocr",
        lambda path: (_ for _ in ()).throw(AssertionError("OCR выключен")),
    )
    source = tmp_path / "scan.png"
    source.write_bytes(b"\x89PNG\r\n")
    text = extract_attachment_text(str(source), ocr=False)
    assert "текст не извлечён" in text


def test_unreadable_image_without_ocr(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.attachment_text._ocr", lambda path: "")
    source = tmp_path / "scan.png"
    source.write_bytes(b"\x89PNG\r\n")
    text = extract_attachment_text(str(source))
    assert "текст не извлечён" in text
    assert write_extracted_sidecar(source) == ""
