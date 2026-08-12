from __future__ import annotations

import re
from pathlib import Path

from app.services.regulation.types import ExtractedBlock, ExtractedDocument, ExtractedTable


def pdf_text_profile(path: Path) -> tuple[int, int]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Для PDF требуется зависимость pdfplumber") from exc

    with pdfplumber.open(str(path)) as pdf:
        page_count = len(pdf.pages)
        chars = 0
        for page in pdf.pages[: min(3, page_count)]:
            chars += len((page.extract_text() or "").strip())
    return page_count, chars


def extract_pdf_text(path: Path) -> ExtractedDocument:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Для PDF требуется зависимость pdfplumber") from exc

    blocks: list[ExtractedBlock] = []
    with pdfplumber.open(str(path)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            char_sizes = [float(ch.get("size") or 0) for ch in page.chars or []]
            baseline = _median(char_sizes) or 12.0
            text_blocks = _extract_text_blocks(page)
            if text_blocks:
                for piece, bbox in text_blocks:
                    is_list_item = _is_bullet(piece)
                    font_size = _guess_font_size(piece, baseline)
                    blocks.append(
                        ExtractedBlock(
                            page=idx,
                            text=piece,
                            kind="list" if is_list_item else "text",
                            block_type=(
                                "list_item"
                                if is_list_item
                                else "heading"
                                if font_size > baseline + 1.5
                                else "paragraph"
                            ),
                            font_size=font_size,
                            is_bold=piece.isupper() and len(piece) < 140,
                            numbering=_leading_numbering(piece),
                            bbox=bbox,
                            confidence=1.0,
                        )
                    )

            for table in page.extract_tables() or []:
                rows = [[(cell or "").strip() for cell in row] for row in table if row]
                rows = [row for row in rows if any(row)]
                if not rows:
                    continue
                headers = rows[0]
                body = rows[1:] if len(rows) > 1 else []
                table_text = "\n".join(" | ".join(cell for cell in row if cell) for row in rows)
                blocks.append(
                    ExtractedBlock(
                        page=idx,
                        text=table_text,
                        kind="table",
                        block_type="table",
                        table=ExtractedTable(headers=headers, rows=body),
                        bbox=(0.0, 0.0, float(page.width), float(page.height)),
                        confidence=1.0,
                    )
                )

        return ExtractedDocument(page_count=len(pdf.pages), blocks=blocks)


def _extract_text_blocks(page) -> list[tuple[str, tuple[float, float, float, float]]]:
    line_items = _extract_lines(page)
    if not line_items:
        text = (page.extract_text(x_tolerance=1, y_tolerance=3) or "").strip()
        return [
            (piece, (0.0, 0.0, float(page.width), float(page.height)))
            for piece in _split_text_blocks(text)
        ]
    paragraphs = _split_line_items_into_blocks(line_items)
    return [(text, bbox) for text, bbox in paragraphs if text]


def _extract_lines(page) -> list[tuple[str, tuple[float, float, float, float]]]:
    words = page.extract_words(x_tolerance=1, y_tolerance=3, use_text_flow=True) or []
    if not words:
        return []
    rows: list[list[dict]] = []
    for word in sorted(words, key=lambda item: (float(item.get("top") or 0), float(item.get("x0") or 0))):
        top = float(word.get("top") or 0)
        if not rows:
            rows.append([word])
            continue
        last_top = _row_top(rows[-1])
        if abs(top - last_top) <= 3:
            rows[-1].append(word)
        else:
            rows.append([word])
    lines: list[tuple[str, tuple[float, float, float, float]]] = []
    for row in rows:
        ordered = sorted(row, key=lambda item: float(item.get("x0") or 0))
        text = " ".join(str(item.get("text") or "").strip() for item in ordered).strip()
        if not text:
            continue
        lines.append((text, _words_bbox(ordered)))
    return lines


def _split_line_items_into_blocks(
    lines: list[tuple[str, tuple[float, float, float, float]]],
) -> list[tuple[str, tuple[float, float, float, float]]]:
    blocks: list[tuple[str, tuple[float, float, float, float]]] = []
    current_text: list[str] = []
    current_boxes: list[tuple[float, float, float, float]] = []
    for line, bbox in lines:
        starts_new = bool(current_text) and (_is_numbered_heading(line) or _is_bullet(line))
        if starts_new:
            blocks.append((" ".join(current_text).strip(), _merge_bboxes(current_boxes)))
            current_text = [line]
            current_boxes = [bbox]
            continue
        current_text.append(line)
        current_boxes.append(bbox)
    if current_text:
        blocks.append((" ".join(current_text).strip(), _merge_bboxes(current_boxes)))
    return blocks


def _row_top(row: list[dict]) -> float:
    values = [float(item.get("top") or 0) for item in row]
    return sum(values) / len(values) if values else 0.0


def _words_bbox(words: list[dict]) -> tuple[float, float, float, float]:
    return (
        min(float(item.get("x0") or 0) for item in words),
        min(float(item.get("top") or 0) for item in words),
        max(float(item.get("x1") or 0) for item in words),
        max(float(item.get("bottom") or 0) for item in words),
    )


def _merge_bboxes(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _split_text_blocks(text: str) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if len(paragraphs) > 1:
        return [piece for paragraph in paragraphs for piece in _split_lines_into_blocks(paragraph)]
    return _split_lines_into_blocks(text)


def _split_lines_into_blocks(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        starts_new = bool(current) and (_is_numbered_heading(line) or _is_bullet(line))
        if starts_new:
            blocks.append(" ".join(current).strip())
            current = [line]
            continue
        current.append(line)
    if current:
        blocks.append(" ".join(current).strip())
    return [block for block in blocks if block]


def _is_numbered_heading(line: str) -> bool:
    return bool(re.match(r"^\d+(?:\.\d+)*\s+\S", line))


def _is_bullet(line: str) -> bool:
    return line.startswith(("- ", "• ", "– "))


def _median(values: list[float]) -> float | None:
    clean = sorted(value for value in values if value > 0)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2


def _guess_font_size(text: str, baseline: float) -> float:
    first = text.splitlines()[0].strip() if text else ""
    if first.isupper() and 3 < len(first) < 140:
        return baseline + 2
    if _leading_numbering(first) and len(first) < 140:
        return baseline + 1
    return baseline


def _leading_numbering(text: str) -> str | None:
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    first = parts[0].rstrip(".)")
    if first and all(piece.isdigit() for piece in first.split(".")):
        return first
    return None
