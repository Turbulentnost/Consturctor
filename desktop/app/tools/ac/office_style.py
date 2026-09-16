"""Корпоративное оформление Excel и Word — как у document tools в ChatGPT.

Создание и переоформление идут через одни и те же темы: шапка, зебра,
фильтр, KPI-плашки, статусы, колонтитулы. Данные не выдумываются.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

HEADER_NAME = "CONSTRUCTOR_HEADER"

_STATUS_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"просроч|overdue|провал|критич", re.I), "C0392B", "FFFFFF"),
    (re.compile(r"выполн|закрыт|done|complete|исполнен|снят", re.I), "1E8449", "FFFFFF"),
    (re.compile(r"работ|progress|открыт|назнач|соглас", re.I), "B9770E", "FFFFFF"),
    (re.compile(r"новый|new|чернов|план", re.I), "1A5276", "FFFFFF"),
)

_STATUS_HEADERS = re.compile(r"статус|status|состояние|итог", re.I)
_MONEY_HEADERS = re.compile(r"сумм|руб|стоим|бюджет|amount|price|money", re.I)
_PERCENT_HEADERS = re.compile(r"%|доля|процент|percent", re.I)
_DATE_HEADERS = re.compile(r"дат|срок|period|deadline|когда", re.I)


@dataclass(frozen=True)
class OfficeTheme:
    name: str
    primary: str
    header: str
    header_font: str
    alt_row: str
    title_font: str
    muted: str
    border: str
    page: str
    kpi_bg: str
    kpi_value: str


THEMES: dict[str, OfficeTheme] = {
    "navy": OfficeTheme(
        name="navy",
        primary="0F2940",
        header="1B4F72",
        header_font="FFFFFF",
        alt_row="EAF2F8",
        title_font="FFFFFF",
        muted="5D6D7E",
        border="BFCFDA",
        page="F7F9FB",
        kpi_bg="D4E6F1",
        kpi_value="0F2940",
    ),
    "forest": OfficeTheme(
        name="forest",
        primary="1B3A2F",
        header="1E8449",
        header_font="FFFFFF",
        alt_row="E8F6EF",
        title_font="FFFFFF",
        muted="52796F",
        border="B7D4C4",
        page="F6FBF8",
        kpi_bg="D5F5E3",
        kpi_value="145A32",
    ),
    "graphite": OfficeTheme(
        name="graphite",
        primary="1C2833",
        header="2C3E50",
        header_font="FFFFFF",
        alt_row="EBEDEF",
        title_font="FFFFFF",
        muted="5D6D7E",
        border="BFC9CA",
        page="F8F9F9",
        kpi_bg="D5D8DC",
        kpi_value="1C2833",
    ),
    "wine": OfficeTheme(
        name="wine",
        primary="4A1C2F",
        header="7B2D4B",
        header_font="FFFFFF",
        alt_row="F5E6ED",
        title_font="FFFFFF",
        muted="7D5260",
        border="D5B4C2",
        page="FDF8FA",
        kpi_bg="F2D7E3",
        kpi_value="4A1C2F",
    ),
    "sand": OfficeTheme(
        name="sand",
        primary="3E3428",
        header="8B7355",
        header_font="FFFFFF",
        alt_row="F5F0E8",
        title_font="FFFFFF",
        muted="7D7468",
        border="D4CBBE",
        page="FBF8F3",
        kpi_bg="EDE4D4",
        kpi_value="3E3428",
    ),
}

DEFAULT_THEME = "navy"


def resolve_theme(name: object) -> OfficeTheme:
    key = str(name or "").strip().casefold() or DEFAULT_THEME
    return THEMES.get(key, THEMES[DEFAULT_THEME])


def theme_names() -> list[str]:
    return list(THEMES)


def as_sections(value: Any) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                heading = str(item.get("heading") or item.get("title") or "").strip()
                body = str(item.get("body") or item.get("text") or "").strip()
                if heading or body:
                    sections.append({"heading": heading, "body": body})
            elif isinstance(item, str) and item.strip():
                sections.append({"heading": "", "body": item.strip()})
    elif isinstance(value, str) and value.strip():
        sections.append({"heading": "", "body": value.strip()})
    return sections


def as_kpis(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not isinstance(value, list):
        return items
    for raw in value:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("title") or raw.get("name") or "").strip()
        amount = raw.get("value")
        if amount is None:
            amount = raw.get("text") or ""
        hint = str(raw.get("hint") or raw.get("note") or "").strip()
        if not label and amount == "":
            continue
        items.append({"label": label, "value": _cell_text(amount), "hint": hint})
    return items


def normalize_table(headers: object, rows: object) -> tuple[list[str], list[list[Any]]]:
    header_list = [str(item).strip() for item in (headers or []) if str(item).strip()]
    raw_rows = list(rows) if isinstance(rows, (list, tuple)) else []
    if not header_list and raw_rows and isinstance(raw_rows[0], dict):
        seen: list[str] = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            for key in row:
                name = str(key).strip()
                if name and name not in seen:
                    seen.append(name)
        header_list = seen
    out: list[list[Any]] = []
    for row in raw_rows:
        if isinstance(row, dict):
            if header_list:
                out.append([_excel_value(row.get(key, "")) for key in header_list])
            else:
                out.append([_excel_value(value) for value in row.values()])
        elif isinstance(row, (list, tuple)):
            out.append([_excel_value(cell) for cell in row])
        else:
            out.append([_excel_value(row)])
    return header_list, out


def as_word_table(value: Any) -> tuple[list[str], list[list[str]]]:
    if not isinstance(value, dict):
        return [], []
    headers, rows = normalize_table(value.get("headers"), value.get("rows"))
    return headers, [[_cell_text(cell) for cell in row] for row in rows]


def pretty_title(*parts: object) -> str:
    """Человеческий заголовок из имени файла или листа — голый stem не оставляем."""
    for part in parts:
        text = str(part or "").strip()
        if not text:
            continue
        stem = Path(text).stem if any(ch in text for ch in "\\/.") else text
        cleaned = stem.replace("_", " ").replace("-", " ").strip()
        if cleaned:
            return cleaned
    return "Отчёт"


def write_excel_sheet(
    workbook: Any,
    *,
    sheet: str,
    headers: object,
    rows: object,
    title: str = "",
    subtitle: str = "",
    theme: object = DEFAULT_THEME,
    kpis: object | None = None,
) -> Any:
    """Записать лист с данными и сразу оформить. Голую таблицу не оставляем."""
    header_list, row_list = normalize_table(headers, rows)
    name = (sheet or "Лист1")[:31]
    if workbook.active and workbook.active.max_row == 1 and workbook.active.max_column == 1:
        worksheet = workbook.active
        worksheet.title = name
    elif name in workbook.sheetnames:
        worksheet = workbook[name]
        worksheet.delete_rows(1, worksheet.max_row)
    else:
        worksheet = workbook.create_sheet(title=name)

    palette = resolve_theme(theme)
    banner_title = pretty_title(title, name)
    start = _write_banner(worksheet, header_list, banner_title, subtitle, as_kpis(kpis), palette)

    if header_list:
        for col, head in enumerate(header_list, start=1):
            worksheet.cell(start, col, head)
    for offset, row in enumerate(row_list):
        for col, value in enumerate(row, start=1):
            worksheet.cell(start + (1 if header_list else 0) + offset, col, value)

    apply_excel_sheet_style(
        workbook,
        worksheet,
        header_row=start if header_list else 0,
        title=banner_title,
        theme=palette,
    )
    return worksheet


def apply_excel_sheet_style(
    workbook: Any,
    worksheet: Any,
    *,
    header_row: int | None = None,
    title: str = "",
    theme: OfficeTheme | str = DEFAULT_THEME,
) -> int:
    """Оформить уже заполненный лист: шапка, зебра, фильтр, ширины, печать."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    palette = resolve_theme(theme) if not isinstance(theme, OfficeTheme) else theme
    detected = header_row if header_row and header_row > 0 else detect_header_row(workbook, worksheet)
    last_col = max(worksheet.max_column or 1, 1)
    last_row = max(worksheet.max_row or 1, detected or 1)
    if last_col < 1:
        return detected

    thin = Border(
        left=Side(style="thin", color=palette.border),
        right=Side(style="thin", color=palette.border),
        top=Side(style="thin", color=palette.border),
        bottom=Side(style="thin", color=palette.border),
    )
    header_fill = PatternFill("solid", fgColor=palette.header)
    alt_fill = PatternFill("solid", fgColor=palette.alt_row)
    white_fill = PatternFill("solid", fgColor="FFFFFF")
    header_font = Font(name="Calibri", bold=True, color=palette.header_font, size=11)
    data_font = Font(name="Calibri", size=11, color="1C2833")
    wrap = Alignment(vertical="center", wrap_text=True)
    header_align = Alignment(vertical="center", wrap_text=True, horizontal="center")

    headers = [
        _cell_text(worksheet.cell(detected, col).value)
        for col in range(1, last_col + 1)
    ] if detected else []

    if detected > 1:
        _recolor_banner(worksheet, detected, last_col, palette, title)

    if detected:
        worksheet.row_dimensions[detected].height = 22
        for col in range(1, last_col + 1):
            cell = worksheet.cell(detected, col)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_align
            cell.border = thin
        for row in range(detected + 1, last_row + 1):
            worksheet.row_dimensions[row].height = 18
            stripe = alt_fill if (row - detected) % 2 == 0 else white_fill
            for col in range(1, last_col + 1):
                cell = worksheet.cell(row, col)
                cell.font = data_font
                cell.alignment = wrap
                cell.border = thin
                if not _is_status_cell(headers, col, cell.value):
                    cell.fill = stripe
                _apply_number_format(cell, headers[col - 1] if col <= len(headers) else "")
                _color_status(cell, headers, col)

        data_ref = f"A{detected}:{get_column_letter(last_col)}{last_row}"
        worksheet.auto_filter.ref = data_ref
        worksheet.freeze_panes = f"A{detected + 1}"
        worksheet.print_title_rows = f"{detected}:{detected}"
        _set_header_row(workbook, worksheet, detected)

    _autosize_columns(worksheet, last_col, last_row)
    worksheet.sheet_properties.tabColor = palette.primary
    worksheet.sheet_view.showGridLines = False
    worksheet.page_setup.orientation = "landscape"
    worksheet.page_setup.fitToWidth = 1
    worksheet.page_setup.fitToHeight = 0
    worksheet.page_setup.paperSize = worksheet.PAPERSIZE_A4
    try:
        worksheet.sheet_properties.pageSetUpPr.fitToPage = True
    except Exception:
        pass
    worksheet.page_margins.left = 0.4
    worksheet.page_margins.right = 0.4
    worksheet.page_margins.top = 0.6
    worksheet.page_margins.bottom = 0.6
    worksheet.oddHeader.left.text = title or worksheet.title
    worksheet.oddFooter.right.text = "Стр. &P из &N"
    worksheet.oddFooter.left.text = "Constructor"
    if getattr(workbook, "properties", None) is not None:
        workbook.properties.creator = "Constructor"
        if title:
            workbook.properties.title = title
    return detected


def restyle_excel_workbook(workbook: Any, *, theme: object = DEFAULT_THEME, title: str = "") -> None:
    palette = resolve_theme(theme)
    for name in workbook.sheetnames:
        apply_excel_sheet_style(workbook, workbook[name], title=title or name, theme=palette)


def detect_header_row(workbook: Any, worksheet: Any) -> int:
    stored = _read_header_row(workbook, worksheet)
    if stored:
        return stored
    max_row = min(worksheet.max_row or 1, 12)
    max_col = worksheet.max_column or 1
    for row in range(1, max_row + 1):
        filled = [
            worksheet.cell(row, col).value
            for col in range(1, max_col + 1)
            if worksheet.cell(row, col).value not in (None, "")
        ]
        if len(filled) >= 2:
            return row
    return 1


def data_start_row(workbook: Any, worksheet: Any) -> int:
    """Первая строка таблицы (шапка), без баннера."""
    return detect_header_row(workbook, worksheet)


def write_docx(
    path: Any,
    *,
    title: str,
    summary: str = "",
    sections: list[dict[str, str]] | None = None,
    headers: list[str] | None = None,
    rows: list[list[str]] | None = None,
    theme: object = DEFAULT_THEME,
    kpis: object | None = None,
) -> None:
    from docx import Document

    document = Document()
    apply_word_chrome(document, title=title, theme=theme)
    _write_word_body(
        document,
        title=title,
        summary=summary,
        sections=sections or [],
        headers=headers or [],
        rows=rows or [],
        kpis=as_kpis(kpis),
        theme=resolve_theme(theme),
    )
    document.save(str(path))


def restyle_docx(path: Any, *, theme: object = DEFAULT_THEME, title: str = "") -> None:
    from docx import Document

    document = Document(str(path))
    palette = resolve_theme(theme)
    apply_word_chrome(document, title=title or _first_heading(document), theme=palette)
    for table in document.tables:
        _style_word_table(table, palette)
    document.save(str(path))


def apply_word_chrome(document: Any, *, title: str, theme: OfficeTheme | str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    palette = resolve_theme(theme) if not isinstance(theme, OfficeTheme) else theme
    section = document.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(2.0)
    _set_run_font(document.styles["Normal"], "Calibri", 11, RGBColor(0x1C, 0x28, 0x33))
    for name, size in (("Heading 1", 16), ("Heading 2", 13)):
        if name in document.styles:
            _set_run_font(document.styles[name], "Calibri", size, _rgb(palette.header))
    header = section.header.paragraphs[0]
    header.text = title or ""
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in header.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = _rgb(palette.muted)
        run.font.name = "Calibri"
    footer = section.footer.paragraphs[0]
    footer.text = ""
    left = footer.add_run("Constructor")
    left.font.size = Pt(9)
    left.font.color.rgb = _rgb(palette.muted)
    left.font.name = "Calibri"
    footer.add_run("   ")
    _add_page_field(footer)
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _recolor_banner(
    worksheet: Any,
    header_row: int,
    last_col: int,
    theme: OfficeTheme,
    title: str,
) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    title_fill = PatternFill("solid", fgColor=theme.primary)
    kpi_fill = PatternFill("solid", fgColor=theme.kpi_bg)
    for col in range(1, last_col + 1):
        cell = worksheet.cell(1, col)
        cell.fill = title_fill
        if col == 1 and title and not cell.value:
            cell.value = title
        cell.font = Font(name="Calibri", bold=True, size=16, color=theme.title_font)
    if header_row > 2:
        worksheet.cell(2, 1).font = Font(name="Calibri", size=10, color=theme.muted, italic=True)
        worksheet.cell(2, 1).alignment = Alignment(vertical="center", indent=1)
    for row in range(3, header_row):
        if not any(worksheet.cell(row, col).value not in (None, "") for col in range(1, last_col + 1)):
            continue
        for col in range(1, last_col + 1):
            cell = worksheet.cell(row, col)
            if cell.value in (None, ""):
                continue
            cell.fill = kpi_fill


def _write_banner(
    worksheet: Any,
    headers: list[str],
    title: str,
    subtitle: str,
    kpis: list[dict[str, str]],
    theme: OfficeTheme,
) -> int:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    width = max(len(headers), len(kpis), 3)
    title_text = str(title or "").strip() or "Отчёт"
    worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    title_cell = worksheet.cell(1, 1, title_text)
    title_cell.fill = PatternFill("solid", fgColor=theme.primary)
    title_cell.font = Font(name="Calibri", bold=True, size=16, color=theme.title_font)
    title_cell.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    worksheet.row_dimensions[1].height = 28
    for col in range(1, width + 1):
        worksheet.cell(1, col).fill = PatternFill("solid", fgColor=theme.primary)

    meta = str(subtitle or "").strip() or datetime.now().strftime("Сформировано %d.%m.%Y %H:%M")
    worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width)
    meta_cell = worksheet.cell(2, 1, meta)
    meta_cell.font = Font(name="Calibri", size=10, color=theme.muted, italic=True)
    meta_cell.alignment = Alignment(vertical="center", indent=1)
    worksheet.row_dimensions[2].height = 18
    row = 3
    if kpis:
        row = 4
        for index, item in enumerate(kpis[: max(width, 1)]):
            col = index + 1
            label = worksheet.cell(3, col, item["label"] or item["hint"])
            label.fill = PatternFill("solid", fgColor=theme.kpi_bg)
            label.font = Font(name="Calibri", size=9, color=theme.muted, bold=True)
            label.alignment = Alignment(horizontal="center", vertical="center")
            value = worksheet.cell(4, col, item["value"])
            value.fill = PatternFill("solid", fgColor=theme.kpi_bg)
            value.font = Font(name="Calibri", size=14, color=theme.kpi_value, bold=True)
            value.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.row_dimensions[3].height = 16
        worksheet.row_dimensions[4].height = 22
        row = 6
    else:
        row = 4
    # keep a spacer column letter used so merge width is real
    _ = get_column_letter(width)
    return row


def _write_word_body(
    document: Any,
    *,
    title: str,
    summary: str,
    sections: list[dict[str, str]],
    headers: list[str],
    rows: list[list[str]],
    kpis: list[dict[str, str]],
    theme: OfficeTheme,
) -> None:
    from docx.shared import Pt

    heading = document.add_paragraph()
    run = heading.add_run(title)
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = _rgb(theme.primary)
    run.font.name = "Calibri"
    heading.paragraph_format.space_after = Pt(4)
    _bottom_border(heading, theme.header)

    meta = document.add_paragraph(datetime.now().strftime("Сформировано %d.%m.%Y %H:%M"))
    meta.runs[0].font.size = Pt(10)
    meta.runs[0].font.color.rgb = _rgb(theme.muted)
    meta.paragraph_format.space_after = Pt(12)

    if kpis:
        table = document.add_table(rows=2, cols=max(1, len(kpis)))
        for index, item in enumerate(kpis):
            table.cell(0, index).text = item["label"]
            table.cell(1, index).text = item["value"]
            _shade(table.cell(0, index), theme.kpi_bg)
            _shade(table.cell(1, index), theme.kpi_bg)
        _style_word_table(table, theme)
        document.add_paragraph("")

    if summary:
        box = document.add_table(rows=1, cols=1)
        box.cell(0, 0).text = summary
        _shade(box.cell(0, 0), theme.alt_row)
        _style_word_table(box, theme)
        document.add_paragraph("")

    for section in sections:
        if section.get("heading"):
            document.add_heading(section["heading"], level=1)
        body = section.get("body") or ""
        for block in _split_blocks(body):
            if block.startswith(("- ", "* ", "• ")):
                document.add_paragraph(block[2:].strip(), style="List Bullet")
            else:
                document.add_paragraph(block)

    if headers and rows:
        table = document.add_table(rows=1, cols=len(headers))
        for idx, head in enumerate(headers):
            table.rows[0].cells[idx].text = head
        for row in rows:
            cells = table.add_row().cells
            for idx in range(len(headers)):
                cells[idx].text = row[idx] if idx < len(row) else ""
        _style_word_table(table, theme)


def _style_word_table(table: Any, theme: OfficeTheme) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    table.autofit = True
    for row_idx, row in enumerate(table.rows):
        for cell in row.cells:
            if row_idx == 0:
                _shade(cell, theme.header)
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
                        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                        run.font.size = Pt(10)
                        run.font.name = "Calibri"
            else:
                _shade(cell, theme.alt_row if row_idx % 2 == 0 else "FFFFFF")
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(10)
                        run.font.name = "Calibri"
            _cell_margins(cell)
    _ = (OxmlElement, qn)


def _shade(cell: Any, color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    for old in tc_pr.findall(qn("w:shd")):
        tc_pr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    shd.set(qn("w:val"), "clear")
    tc_pr.append(shd)


def _cell_margins(cell: Any) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    for old in tc_pr.findall(qn("w:tcMar")):
        tc_pr.remove(old)
    mar = OxmlElement("w:tcMar")
    for edge in ("top", "left", "bottom", "right"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:w"), "80")
        node.set(qn("w:type"), "dxa")
        mar.append(node)
    tc_pr.append(mar)


def _bottom_border(paragraph: Any, color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), color)
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def _add_page_field(paragraph: Any) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    from docx.shared import Pt

    run = paragraph.add_run("стр. ")
    run.font.size = Pt(9)
    def _field(instruction: str) -> None:
        r = paragraph.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = instruction
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        r._r.append(begin)
        r._r.append(instr)
        r._r.append(end)

    _field(" PAGE ")
    paragraph.add_run(" / ")
    _field(" NUMPAGES ")


def _set_run_font(style: Any, name: str, size: int, color: Any) -> None:
    from docx.shared import Pt

    font = style.font
    font.name = name
    font.size = Pt(size)
    font.color.rgb = color


def _rgb(hex_color: str) -> Any:
    from docx.shared import RGBColor

    raw = hex_color.lstrip("#")
    return RGBColor(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def _first_heading(document: Any) -> str:
    for paragraph in document.paragraphs:
        text = (paragraph.text or "").strip()
        if text:
            return text
    return ""


def _split_blocks(body: str) -> list[str]:
    if not body.strip():
        return []
    blocks: list[str] = []
    for chunk in re.split(r"\n\s*\n", body.strip()):
        lines = chunk.splitlines()
        if all(line.startswith(("- ", "* ", "• ")) for line in lines if line.strip()):
            blocks.extend(line.strip() for line in lines if line.strip())
        else:
            blocks.append(chunk.strip())
    return blocks


def _excel_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool, date, datetime)):
        return value
    return value


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return str(value)


def _autosize_columns(worksheet: Any, last_col: int, last_row: int) -> None:
    from openpyxl.utils import get_column_letter

    for col in range(1, last_col + 1):
        longest = 8
        for row in range(1, last_row + 1):
            value = worksheet.cell(row, col).value
            longest = max(longest, min(len(_cell_text(value)), 48))
        worksheet.column_dimensions[get_column_letter(col)].width = min(42, longest + 3)


def _apply_number_format(cell: Any, header: str) -> None:
    value = cell.value
    if isinstance(value, datetime):
        cell.number_format = "DD.MM.YYYY HH:MM"
        return
    if isinstance(value, date):
        cell.number_format = "DD.MM.YYYY"
        return
    if isinstance(value, float) and _PERCENT_HEADERS.search(header):
        cell.number_format = "0.0%"
        return
    if isinstance(value, (int, float)) and _MONEY_HEADERS.search(header):
        cell.number_format = "#,##0.00"
        return
    if isinstance(value, (int, float)):
        cell.number_format = "#,##0" if isinstance(value, int) else "#,##0.00"
        return
    return


def _is_status_cell(headers: list[str], col: int, value: Any) -> bool:
    if col > len(headers) or value in (None, ""):
        return False
    return bool(_STATUS_HEADERS.search(headers[col - 1]))


def _color_status(cell: Any, headers: list[str], col: int) -> None:
    from openpyxl.styles import Font, PatternFill

    if not _is_status_cell(headers, col, cell.value):
        return
    text = _cell_text(cell.value)
    for pattern, fill, font in _STATUS_RULES:
        if pattern.search(text):
            cell.fill = PatternFill("solid", fgColor=fill)
            cell.font = Font(name="Calibri", size=11, color=font, bold=True)
            return


def _set_header_row(workbook: Any, worksheet: Any, row: int) -> None:
    from openpyxl.workbook.defined_name import DefinedName

    safe_title = worksheet.title.replace("'", "''")
    ref = f"'{safe_title}'!$A${int(row)}"
    try:
        if HEADER_NAME in workbook.defined_names:
            del workbook.defined_names[HEADER_NAME]
    except Exception:
        pass
    try:
        workbook.defined_names.add(DefinedName(name=HEADER_NAME, attr_text=ref))
    except Exception:
        pass


def _read_header_row(workbook: Any, worksheet: Any) -> int:
    try:
        defined = workbook.defined_names[HEADER_NAME]
    except Exception:
        return 0
    text = str(getattr(defined, "attr_text", "") or getattr(defined, "value", "") or "")
    if worksheet.title.replace("'", "''") not in text and worksheet.title not in text:
        destinations = getattr(defined, "destinations", None)
        if destinations:
            for sheet, coord in destinations:
                if sheet == worksheet.title:
                    match = re.search(r"(\d+)", str(coord))
                    return int(match.group(1)) if match else 0
        return 0
    match = re.search(r"\$(\d+)\s*$", text)
    return int(match.group(1)) if match else 0


def iter_theme_preview() -> Iterable[str]:
    return THEMES.keys()
