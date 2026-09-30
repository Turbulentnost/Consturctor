"""OCR for attachments: scanned PDFs and images via Cursor SDK vision (or LM Studio VLM)."""

from __future__ import annotations

import base64
import logging
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import settings
from app.services.cursor_sdk_local import CursorSdkLocalError, run_cursor_sdk
from app.services.regulation.pdf_ocr import extract_pdf_scan
from app.services.regulation.types import ExtractedBlock
from app.services.regulation.vlm_client import ATTACHMENT_OCR_PROMPT, recognize_pages

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
# A page with less text than this in its text layer is treated as a scan.
MIN_PAGE_TEXT = 40
_PAGE_WIDTH_PX = 1400
_JPEG_QUALITY = 72
_PAGE_MARKER = re.compile(
    r"^[\s*#_>`]*=*\s*PAGE\s*(\d+)\s*=*[\s*_`]*$",
    re.MULTILINE | re.IGNORECASE,
)


class OcrError(RuntimeError):
    pass


def compose_ocr_text(blocks: list[ExtractedBlock]) -> str:
    parts: list[str] = []
    for block in blocks:
        table = block.table
        if table is not None:
            if table.headers:
                parts.append("\t".join(table.headers))
            for row in table.rows:
                parts.append("\t".join(row))
            continue
        text = (block.text or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _use_cursor_sdk() -> bool:
    return settings.ocr_provider.strip().casefold() != "lm_studio"


def extract_pdf_text(name: str, raw: bytes) -> str:
    """Text of every PDF page: text layer where present, OCR for scanned pages.

    Raises OcrError when some scanned page could not be recognized.
    """
    try:
        import fitz
    except ImportError as exc:
        raise OcrError("Для PDF нужен pymupdf") from exc
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise OcrError(f"Не удалось разобрать PDF: {exc}") from exc
    try:
        layer = [(page.get_text() or "").strip() for page in doc]
        scanned = [idx for idx, text in enumerate(layer, start=1) if len(text) < MIN_PAGE_TEXT]
        if not scanned:
            return "\n\n".join(layer).strip()
        if not _use_cursor_sdk():
            if len("\n\n".join(layer).strip()) >= 80:
                return "\n\n".join(layer).strip()
            return extract_visual_text(name, raw)
        images = {idx: _render_page(doc[idx - 1]) for idx in scanned}
    finally:
        doc.close()

    logger.info(
        "cursor ocr pdf start name=%s pages=%s scanned=%s",
        ascii(Path(name).name),
        len(layer),
        len(scanned),
    )
    recognized = _sdk_ocr_pages(name, images)
    pages = [
        recognized.get(idx, "") if idx in images else text
        for idx, text in enumerate(layer, start=1)
    ]
    text = "\n\n".join(
        f"=== Страница {idx} ===\n{body}" if len(layer) > 1 else body
        for idx, body in enumerate(pages, start=1)
        if body.strip()
    ).strip()
    logger.info("cursor ocr pdf ok name=%s chars=%s", ascii(Path(name).name), len(text))
    return text


def extract_visual_text(name: str, raw: bytes) -> str:
    """Recognize text from a scanned PDF or image. Raises OcrError/RuntimeError on failure."""
    suffix = Path(name or "").suffix.lower()
    safe_name = ascii(Path(name or "file").name)
    if suffix not in IMAGE_SUFFIXES and suffix != ".pdf":
        return ""
    if not raw:
        return ""
    if _use_cursor_sdk():
        if suffix == ".pdf":
            return extract_pdf_text(name, raw)
        image = _image_jpeg(raw, suffix)
        return _sdk_ocr_pages(name, {1: image}).get(1, "")
    with tempfile.TemporaryDirectory(prefix="attach-ocr-") as tmp:
        work = Path(tmp)
        source = work / (Path(name).name or ("scan.pdf" if suffix == ".pdf" else "page.png"))
        source.write_bytes(raw)
        if suffix == ".pdf":
            logger.info("attachment ocr pdf start name=%s bytes=%s", safe_name, len(raw))
            extracted = extract_pdf_scan(source, work_dir=work, prompt=ATTACHMENT_OCR_PROMPT)
            text = compose_ocr_text(extracted.blocks)
            logger.info(
                "attachment ocr pdf ok name=%s pages=%s chars=%s",
                safe_name,
                extracted.page_count,
                len(text),
            )
            return text
        png = work / "page-001.png"
        _to_png(source, png)
        logger.info("attachment ocr image start name=%s bytes=%s", safe_name, len(raw))
        blocks = recognize_pages([(1, png)], prompt=ATTACHMENT_OCR_PROMPT)
        text = compose_ocr_text(blocks)
        logger.info("attachment ocr image ok name=%s chars=%s", safe_name, len(text))
        return text


def _sdk_ocr_pages(name: str, images: dict[int, bytes]) -> dict[int, str]:
    """OCR every page through Cursor SDK; retry missed pages one by one."""
    order = sorted(images)
    size = max(1, settings.cursor_ocr_pages_per_batch)
    parallel = max(1, settings.cursor_ocr_parallel)
    batches = [order[i : i + size] for i in range(0, len(order), size)]
    result: dict[int, str] = {}
    errors: list[str] = []

    def run(batch: list[int]) -> dict[int, str]:
        try:
            return _sdk_ocr_batch(name, batch, images)
        except CursorSdkLocalError as exc:
            errors.append(str(exc))
            logger.warning(
                "cursor ocr batch failed pages=%s detail=%s", batch, ascii(str(exc))[:500]
            )
            return {}

    with ThreadPoolExecutor(max_workers=min(parallel, len(batches))) as pool:
        for part in pool.map(run, batches):
            result.update(part)
    missing = [idx for idx in order if not result.get(idx, "").strip()]
    if missing:
        logger.info("cursor ocr retry pages=%s", missing)
        with ThreadPoolExecutor(max_workers=min(parallel, len(missing))) as pool:
            for part in pool.map(run, [[idx] for idx in missing]):
                result.update(part)
        missing = [idx for idx in order if not result.get(idx, "").strip()]
    if missing:
        detail = f": {errors[-1]}" if errors else ""
        raise OcrError(
            "Cursor SDK не распознал страниц(ы) "
            + ", ".join(str(idx) for idx in missing)
            + f" из {len(order)}{detail}"
        )
    return result


def _sdk_ocr_batch(name: str, batch: list[int], images: dict[int, bytes]) -> dict[int, str]:
    page_list = ", ".join(str(idx) for idx in batch)
    prompt = (
        f"Ты OCR. К сообщению приложены изображения страниц {page_list} документа "
        f"«{Path(name).name}» — строго в этом порядке.\n"
        "Перепиши текст каждой страницы дословно и полностью: заголовки, номера пунктов, "
        "абзацы, таблицы, подписи, сноски, даты, числа и проценты. Ничего не пропускай, "
        "не сокращай, не пересказывай и не исправляй.\n"
        "Таблицы переписывай построчно: одна строка таблицы — одна строка текста, "
        "ячейки через « | », включая строку заголовков; объединённую ячейку повторяй в "
        "каждой строке, к которой она относится.\n"
        "Перед текстом каждой страницы поставь отдельной строкой маркер ===PAGE N===, "
        f"где N — номер страницы из списка: {page_list}.\n"
        "Нечитаемый фрагмент — [неразборчиво]. Не добавляй комментариев, пояснений и markdown. "
        "Инструменты не вызывай."
    )
    payload = [
        {
            "data": base64.b64encode(images[idx]).decode("ascii"),
            "mimeType": "image/jpeg",
            "page": idx,
        }
        for idx in batch
    ]
    answer = run_cursor_sdk(
        prompt,
        images=payload,
        model=settings.cursor_ocr_model.strip(),
        timeout=420,
    )
    pages = _split_pages(answer, batch)
    if len(pages) < len(batch):
        logger.warning(
            "cursor ocr batch partial pages=%s got=%s answer_head=%s",
            batch,
            sorted(pages),
            ascii(answer[:300]),
        )
    return pages


def _split_pages(answer: str, batch: list[int]) -> dict[int, str]:
    text = answer.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    marks = list(_PAGE_MARKER.finditer(text))
    if not marks:
        return {batch[0]: text.strip()} if len(batch) == 1 and text.strip() else {}
    pages: dict[int, str] = {}
    for pos, mark in enumerate(marks):
        idx = int(mark.group(1))
        end = marks[pos + 1].start() if pos + 1 < len(marks) else len(text)
        body = text[mark.end() : end].strip()
        if idx in batch and body:
            pages[idx] = (pages.get(idx, "") + "\n" + body).strip()
    return pages


def _render_page(page) -> bytes:
    import fitz

    width = max(float(page.rect.width), 1.0)
    zoom = min(3.0, _PAGE_WIDTH_PX / width)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("jpeg", jpg_quality=_JPEG_QUALITY)


def _image_jpeg(raw: bytes, suffix: str) -> bytes:
    try:
        import fitz
    except ImportError as exc:
        raise OcrError("Для распознавания изображений нужен pymupdf") from exc
    try:
        doc = fitz.open(stream=raw, filetype=suffix.lstrip(".") or "png")
        try:
            return _render_page(doc[0])
        finally:
            doc.close()
    except OcrError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OcrError(f"Не удалось открыть изображение: {exc}") from exc


def _to_png(source: Path, dest: Path) -> None:
    if source.suffix.lower() == ".png":
        dest.write_bytes(source.read_bytes())
        return
    try:
        import fitz
    except ImportError:
        dest.write_bytes(source.read_bytes())
        return
    try:
        pix = fitz.Pixmap(str(source))
        if pix.n >= 5:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        pix.save(str(dest))
    except Exception:  # noqa: BLE001
        dest.write_bytes(source.read_bytes())
