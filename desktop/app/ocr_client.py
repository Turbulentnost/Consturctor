"""LM Studio OCR for attached scans and photos."""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://192.168.1.157:1239"
_DEFAULT_MODEL = "ministral-3-14b-instruct-2512"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


def ocr_file(path: str | Path) -> str:
    source = Path(path)
    suffix = source.suffix.lower()
    if not source.is_file():
        return ""
    if suffix == ".pdf":
        return _ocr_pdf(source)
    if suffix in IMAGE_SUFFIXES:
        return _ocr_image(source)
    return ""


def _ocr_url() -> str:
    base = (os.environ.get("LM_STUDIO_BASE_URL") or _DEFAULT_URL).strip().rstrip("/")
    return f"{base}/v1/chat/completions"


def _ocr_model() -> str:
    return (
        os.environ.get("LM_STUDIO_OCR_MODEL")
        or os.environ.get("LM_STUDIO_MODEL")
        or _DEFAULT_MODEL
    ).strip()


def _ocr_image(path: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="ocr-img-") as tmp:
        png = Path(tmp) / "page-001.png"
        _to_png(path, png)
        return _recognize([(1, png)])


def _ocr_pdf(path: Path) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    with tempfile.TemporaryDirectory(prefix="ocr-pdf-") as tmp:
        images: list[tuple[int, Path]] = []
        work = Path(tmp)
        doc = fitz.open(str(path))
        try:
            for idx, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image_path = work / f"page-{idx:03d}.png"
                pix.save(str(image_path))
                images.append((idx, image_path))
        finally:
            doc.close()
        if not images:
            return ""
        return _recognize(images)


def _recognize(images: list[tuple[int, Path]]) -> str:
    if not images:
        return ""
    prompt = (
        "Распознай весь видимый текст на страницах, включая таблицы. "
        "Верни только текст, без markdown и без комментариев."
    )
    content: list[dict] = [{"type": "text", "text": prompt}]
    for page, image_path in images:
        raw = image_path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        content.append({"type": "text", "text": f"Page {page}"})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )
    url = _ocr_url()
    model = _ocr_model()
    logger.info(
        "lm studio ocr request url=%s model=%s pages=%s",
        url,
        model,
        len(images),
    )
    try:
        with httpx.Client(timeout=180.0) as client:
            response = client.post(
                url,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0,
                },
            )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "lm studio ocr failed url=%s model=%s detail=%s",
            url,
            model,
            ascii(str(exc)),
        )
        return ""
    choices = data.get("choices") if isinstance(data, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices else {}
    text = ""
    if isinstance(message, dict):
        text = message.get("content") or message.get("reasoning") or ""
    if isinstance(text, list):
        text = "".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part)
            for part in text
        )
    return str(text or "").strip()


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

