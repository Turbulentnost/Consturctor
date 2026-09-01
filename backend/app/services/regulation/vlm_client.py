from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.services.regulation.types import ExtractedBlock, ExtractedTable

logger = logging.getLogger(__name__)


class VlmError(RuntimeError):
    pass


def recognize_pages(images: list[tuple[int, Path]]) -> list[ExtractedBlock]:
    if not images:
        return []
    prompt = (
        "Ты OCR/VLM для русскоязычных регламентов. Распознай страницы документа. "
        "Верни только JSON без markdown: {\"blocks\":[...]}. Каждый block: "
        "page (номер страницы), section (заголовок раздела если виден), "
        "kind: text|table|list, text, table:{headers:[...], rows:[[...]]} или null, "
        "ocrConfidence от 0 до 1. Таблицы сохраняй структурно, списки не теряй."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for page, image_path in images:
        b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        content.append({"type": "text", "text": f"Страница {page}"})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    model = (settings.lm_studio_ocr_model or settings.lm_studio_model).strip()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }
    response_text = _post_with_retry(payload)
    return _parse_blocks(response_text)


def _ocr_url() -> str:
    return f"{settings.lm_studio_base_url.rstrip('/')}/v1/chat/completions"


def _post_with_retry(payload: dict[str, Any]) -> str:
    url = _ocr_url()
    model = str(payload.get("model") or "")
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            logger.info(
                "lm studio ocr request url=%s model=%s pages=%s attempt=%s",
                url,
                model,
                sum(1 for item in payload.get("messages", [{}])[0].get("content", []) if item.get("type") == "image_url"),
                attempt,
            )
            with httpx.Client(timeout=180.0) as client:
                response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") if isinstance(data, dict) else None
            message = choices[0].get("message") if isinstance(choices, list) and choices else {}
            content = ""
            if isinstance(message, dict):
                content = message.get("content") or message.get("reasoning") or ""
            if isinstance(content, list):
                content = "".join(
                    str(part.get("text") or "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            content = str(content or "")
            logger.info(
                "lm studio ocr response url=%s model=%s status=%s chars=%s",
                url,
                model,
                response.status_code,
                len(content),
            )
            if not content.strip():
                raise VlmError("LM Studio returned empty OCR content")
            return content
        except Exception as exc:  # noqa: BLE001 - converted to user-facing parse error.
            last_error = exc
            logger.warning(
                "lm studio ocr request failed url=%s model=%s attempt=%s detail=%s",
                url,
                model,
                attempt,
                ascii(str(exc)),
            )
    raise VlmError(f"LM Studio OCR недоступен: {url} model={model}: {last_error}") from last_error


def _parse_blocks(raw: str) -> list[ExtractedBlock]:
    payload = _load_json(raw)
    blocks_obj = payload.get("blocks") if isinstance(payload, dict) else None
    if not isinstance(blocks_obj, list):
        raise VlmError("LM Studio вернул ответ без blocks")

    blocks: list[ExtractedBlock] = []
    for item in blocks_obj:
        if not isinstance(item, dict):
            continue
        table_obj = item.get("table")
        table = None
        if isinstance(table_obj, dict):
            headers = [str(x) for x in table_obj.get("headers") or []]
            rows = [[str(cell) for cell in row] for row in table_obj.get("rows") or []]
            table = ExtractedTable(headers=headers, rows=rows)
        kind = str(item.get("kind") or "text").strip().lower()
        blocks.append(
            ExtractedBlock(
                page=int(item.get("page") or 1),
                section=str(item.get("section") or "").strip(),
                text=str(item.get("text") or "").strip(),
                kind=kind if kind in {"text", "table", "list"} else "text",
                block_type="table" if kind == "table" else ("list_item" if kind == "list" else "paragraph"),
                table=table,
                table_headers=table.headers if table is not None else [],
                confidence=float(item.get("ocrConfidence") or item.get("confidence") or 0.85),
            )
        )
    return blocks


def _load_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise
