"""Minimal OOXML bytes for agent test files (written via fs.write, not COM)."""

from __future__ import annotations

import base64
import io
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from platform_tool_filesystem.desktop_paths import agent_build_dir

DEFAULT_DOCX_NAME = "agent_test.docx"
DEFAULT_XLSX_NAME = "agent_test.xlsx"


def _timestamp_label() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def desktop_agent_build_dir(*, subdir: str = "") -> Path:
    return agent_build_dir(subdir=subdir)


def resolve_output_dir(*, prefer_desktop: bool = True) -> Path:
    env = (os.environ.get("AGENT_BUILD_OUTPUT_DIR") or os.environ.get("FS_AGENT_BUILD_DIR") or "").strip()
    if env:
        path = Path(env).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    if prefer_desktop:
        return desktop_agent_build_dir()
    root = Path(os.environ.get("CONSTRUCTOR_ROOT", Path.cwd())).resolve()
    path = (root / "data" / "filesystem").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_docx_bytes(*, title: str, body: str) -> bytes:
    title_xml = escape(title)
    body_xml = escape(body)
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{title_xml}</w:t></w:r></w:p>
    <w:p><w:r><w:t>{body_xml}</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/_rels/document.xml.rels", doc_rels)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def build_xlsx_bytes(*, title: str, rows: list[list[str]]) -> bytes:
    sheet_rows = []
    for row_idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row, start=1):
            col = ""
            n = col_idx
            while n:
                n, rem = divmod(n - 1, 26)
                col = chr(65 + rem) + col
            ref = f"{col}{row_idx}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>{"".join(sheet_rows)}</sheetData>
</worksheet>"""
    workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Test" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


def default_test_payloads(
    *,
    title: str = "Constructor agent test",
    body: str = "",
    output_dir: Path | None = None,
    docx_path: str | Path | None = None,
    xlsx_path: str | Path | None = None,
    docx_name: str = DEFAULT_DOCX_NAME,
    xlsx_name: str = DEFAULT_XLSX_NAME,
) -> tuple[dict[str, str], dict[str, str], Path]:
    folder = output_dir or agent_build_dir()
    stamp = _timestamp_label()
    if not body.strip():
        body = (
            f"Тестовый документ для агента Constructor.\n"
            f"Создан через fs.write (OOXML, без COM).\n"
            f"Время: {stamp}\n"
            f"Папка: {folder}"
        )
    rows = [
        ["Поле", "Значение"],
        ["Создано", stamp],
        ["Источник", "fs.write + OOXML"],
        ["Папка", str(folder)],
    ]
    docx_target = Path(docx_path) if docx_path else folder / docx_name
    xlsx_target = Path(xlsx_path) if xlsx_path else folder / xlsx_name
    docx_payload = build_office_write_payload(
        path=docx_target, format="docx", title=title, body=body
    )
    xlsx_payload = build_office_write_payload(
        path=xlsx_target, format="xlsx", title=title, rows=rows
    )
    return docx_payload, xlsx_payload, folder


def build_office_write_payload(
    *,
    path: str | Path,
    format: str = "",
    title: str = "Constructor agent file",
    body: str = "",
    rows: list[list[str]] | None = None,
    mode: str = "overwrite",
) -> dict[str, str]:
    """Build fs.write payload for docx/xlsx; path is chosen by caller."""
    file_path = Path(str(path).strip()).expanduser()
    if not file_path.name:
        raise ValueError("path must include filename")
    fmt = (format or file_path.suffix).lower().lstrip(".")
    stamp = _timestamp_label()
    if fmt == "docx":
        if not body.strip():
            body = (
                f"Документ Constructor.\n"
                f"Создан через fs.build_office_file.\n"
                f"Время: {stamp}\n"
                f"Путь: {file_path}"
            )
        data = build_docx_bytes(title=title, body=body)
    elif fmt == "xlsx":
        sheet_rows = rows or [
            ["Поле", "Значение"],
            ["Создано", stamp],
            ["Источник", "fs.build_office_file"],
            ["Путь", str(file_path)],
        ]
        data = build_xlsx_bytes(title=title, rows=sheet_rows)
    else:
        raise ValueError("format must be docx or xlsx (or path ending with .docx/.xlsx)")
    return {
        "path": str(file_path),
        "content_base64": base64.b64encode(data).decode("ascii"),
        "mode": mode,
    }
