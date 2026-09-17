"""LM Studio OCR for attached scans and photos."""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://192.168.1.157:1234"
_DEFAULT_MODEL = "ministral-3-14b-instruct-2512"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_LAST_ERROR = ""


def last_ocr_error() -> str:
    return _LAST_ERROR


def ocr_file(path: str | Path) -> str:
    global _LAST_ERROR
    _LAST_ERROR = ""
    source = Path(path)
    suffix = source.suffix.lower()
    if not source.is_file():
        _LAST_ERROR = f"файл не найден: {source.name}"
        return ""
    if suffix == ".pdf":
        return _ocr_pdf(source)
    if suffix in IMAGE_SUFFIXES:
        return _ocr_image(source)
    _LAST_ERROR = f"OCR не умеет {suffix or 'этот тип файла'}"
    return ""


def _env_value(key: str) -> str:
    found = (os.environ.get(key) or "").strip()
    if found:
        return found
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / ".env",
        here.parents[2] / "backend" / ".env",
    ]
    for env_path in candidates:
        if not env_path.is_file():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                if name.strip() == key:
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _ocr_url() -> str:
    base = (_env_value("LM_STUDIO_BASE_URL") or _DEFAULT_URL).strip().rstrip("/")
    return f"{base}/v1/chat/completions"


def _ocr_model() -> str:
    return (
        _env_value("LM_STUDIO_OCR_MODEL")
        or _env_value("LM_STUDIO_MODEL")
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
        _set_error("нет pymupdf, страницы PDF для OCR не снять")
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
        _set_error(f"LM Studio недоступен ({url}): {_short_exc(exc)}")
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
    text = str(text or "").strip()
    if not text:
        _set_error(f"LM Studio ответил пусто ({url}, модель {model})")
    return text


def _set_error(message: str) -> None:
    global _LAST_ERROR
    _LAST_ERROR = (message or "").strip()


def _short_exc(exc: BaseException) -> str:
    text = str(exc or "").strip() or exc.__class__.__name__
    if "All connection attempts failed" in text or "ConnectError" in exc.__class__.__name__:
        return "нет соединения"
    if "timed out" in text.lower() or "Timeout" in exc.__class__.__name__:
        return "таймаут"
    return text[:180]


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

