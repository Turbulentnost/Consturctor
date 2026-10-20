"""Извлечение текста из вложений: офисные файлы, PDF и OCR для сканов/фото."""

from __future__ import annotations

import re
import struct
import sys
import tempfile
from pathlib import Path

_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".log"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_W_TEXT = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
_A_TEXT = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
_MAX_CHARS = 12_000
UNREADABLE = "текст не извлечён"
_UNREADABLE = UNREADABLE


def extract_attachment_text(
    path: str,
    *,
    max_chars: int = _MAX_CHARS,
    max_pages: int = 0,
    start_page: int = 1,
    ocr: bool = True,
) -> str:
    file_path = Path(path)
    name = file_path.name
    suffix = file_path.suffix.lower()
    if not file_path.is_file():
        return f"файл {name} прикреплён, {_UNREADABLE} (файл не найден)"
    try:
        if suffix in _TEXT_SUFFIXES:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            text = _read_pdf(
                file_path, max_pages=max_pages, start_page=start_page, ocr=ocr
            )
        elif suffix == ".docx":
            text = _read_docx(file_path)
        elif suffix == ".pptx":
            text = _read_pptx(file_path)
        elif suffix in {".xlsx", ".xlsm"}:
            text = _read_xlsx(file_path)
        elif suffix in _IMAGE_SUFFIXES:
            text = _ocr(file_path) if ocr else ""
        elif suffix == ".doc":
            text = _read_doc(file_path)
        else:
            text = ""
    except Exception:  # noqa: BLE001
        text = ""
    text = (text or "").strip()
    if not text:
        return f"файл {name} прикреплён, {_UNREADABLE}"
    limit = max(200, int(max_chars or _MAX_CHARS))
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n…"
    return text


def write_extracted_sidecar(path: str | Path) -> str:
    """Write path + '.txt' when OCR/native extract produced real text.

    Returns the sidecar path as a posix string, or empty if nothing useful.
    """
    source = Path(path)
    if not source.is_file():
        return ""
    text = extract_attachment_text(str(source))
    if not text or _UNREADABLE in text:
        return ""
    target = source.with_name(source.name + ".txt")
    target.write_text(text, encoding="utf-8")
    return target.as_posix()


def format_attachments_block(paths: list[str]) -> str:
    if not paths:
        return ""
    parts: list[str] = ["", "Прикреплено:"]
    for path in paths:
        name = Path(path).name
        extracted = extract_attachment_text(path)
        parts.append(f"— {name}")
        parts.append(extracted)
    return "\n".join(parts).rstrip()


def _ocr(path: Path) -> str:
    try:
        from app.ocr_client import ocr_file
    except ImportError:
        return ""
    return ocr_file(path)


def _read_pdf(
    path: Path, *, max_pages: int = 0, start_page: int = 1, ocr: bool = True
) -> str:
    native = ""
    try:
        import fitz  # pymupdf
    except ImportError:
        fitz = None
    if fitz is not None:
        doc = fitz.open(path)
        try:
            pages = list(doc)
            start = max(1, int(start_page or 1))
            if start > len(pages):
                start = 1
            pages = pages[start - 1 :]
            if max_pages and max_pages > 0:
                pages = pages[:max_pages]
            native = "\n\n".join((page.get_text() or "") for page in pages)
        finally:
            doc.close()
    native = (native or "").strip()
    if native:
        return native
    return _ocr(path) if ocr else ""


def _read_docx(path: Path) -> str:
    """Paragraphs, tables and text boxes. python-docx paragraphs miss table acts."""
    try:
        import zipfile
        import xml.etree.ElementTree as ET
    except ImportError:
        return ""
    skip = ("styles", "settings", "fontTable", "numbering", "webSettings", "theme")
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.startswith("word/")
                and name.endswith(".xml")
                and not any(part in name for part in skip)
            ]
            for name in names:
                try:
                    root = ET.fromstring(archive.read(name))
                except ET.ParseError:
                    continue
                lines = [
                    (node.text or "").strip()
                    for node in root.iter(_W_TEXT)
                    if (node.text or "").strip()
                ]
                if lines:
                    chunks.append("\n".join(lines))
    except Exception:  # noqa: BLE001
        return ""
    return "\n".join(chunks)


def _read_pptx(path: Path) -> str:
    try:
        import xml.etree.ElementTree as ET
        import zipfile
    except ImportError:
        return ""
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            for name in names:
                try:
                    root = ET.fromstring(archive.read(name))
                except ET.ParseError:
                    continue
                lines = [
                    (node.text or "").strip()
                    for node in root.iter(_A_TEXT)
                    if (node.text or "").strip()
                ]
                if lines:
                    chunks.append("\n".join(lines))
    except Exception:  # noqa: BLE001
        return ""
    return "\n\n".join(chunks)


def _read_xlsx(path: Path) -> str:
    try:
        import openpyxl
    except ImportError:
        return ""
    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        parts: list[str] = []
        for sheet in workbook.worksheets:
            parts.append(f"===== SHEET: {sheet.title} =====")
            for row in sheet.iter_rows(values_only=True):
                values = [str(cell).strip() if cell is not None else "" for cell in row]
                while values and not values[-1]:
                    values.pop()
                if values:
                    parts.append("\t".join(values))
        return "\n".join(parts)
    finally:
        workbook.close()


def _read_doc(path: Path) -> str:
    try:
        text = _read_doc_pieces(path)
    except Exception:  # noqa: BLE001
        text = ""
    if text.strip():
        return text
    return _read_doc_via_word(path)


_DOC_CONTROL = str.maketrans({"\r": "\n", "\x07": "\t", "\x0b": "\n", "\x0c": "\n", "\x13": "", "\x14": "", "\x15": ""})


def _read_doc_pieces(path: Path) -> str:
    """Word 97–2003 text from the piece table (FIB → Clx → PlcPcd)."""
    import olefile

    with olefile.OleFileIO(str(path)) as ole:
        word = ole.openstream("WordDocument").read()
        table_name = "1Table" if struct.unpack_from("<H", word, 0x0A)[0] & 0x0200 else "0Table"
        table = ole.openstream(table_name).read()
    fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x01A2)
    clx = table[fc_clx : fc_clx + lcb_clx]
    pos = 0
    while pos < len(clx) and clx[pos] == 0x01:
        pos += 3 + struct.unpack_from("<H", clx, pos + 1)[0]
    if pos >= len(clx) or clx[pos] != 0x02:
        return ""
    lcb = struct.unpack_from("<I", clx, pos + 1)[0]
    plc = clx[pos + 5 : pos + 5 + lcb]
    count = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{count + 1}I", plc, 0)
    parts: list[str] = []
    for index in range(count):
        length = cps[index + 1] - cps[index]
        fc = struct.unpack_from("<I", plc, 4 * (count + 1) + 8 * index + 2)[0]
        if fc & 0x40000000:
            start = (fc & ~0x40000000) // 2
            parts.append(word[start : start + length].decode("cp1252", errors="replace"))
        else:
            parts.append(word[fc : fc + 2 * length].decode("utf-16-le", errors="replace"))
    text = "".join(parts)
    text = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", text)
    text = re.sub(r"\x13[^\x13\x14\x15]*\x15", "", text)
    text = text.translate(_DOC_CONTROL)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _read_doc_via_word(path: Path) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return ""
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        with tempfile.TemporaryDirectory(prefix="constructor-doc-") as tmp:
            target = Path(tmp) / f"{path.stem}.docx"
            doc = word.Documents.Open(
                str(path.resolve()), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False
            )
            try:
                doc.SaveAs2(str(target), FileFormat=16)
            finally:
                doc.Close(SaveChanges=0)
            return _read_docx(target)
    except Exception:  # noqa: BLE001
        return ""
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:  # noqa: BLE001
                pass
        pythoncom.CoUninitialize()
