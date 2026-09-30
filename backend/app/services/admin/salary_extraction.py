from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.workflows.document import DocumentError, load_attachment_bytes


class SalaryExtractionError(RuntimeError):
    pass


def extract_salary_document(name: str, raw: bytes) -> dict[str, Any]:
    """Extract position salaries semantically with the local Cursor SDK agent."""
    try:
        attachment = load_attachment_bytes(name, raw, ocr=True)
    except DocumentError as exc:
        raise SalaryExtractionError(str(exc)) from exc
    text = str(attachment.get("text") or "").strip()
    if not text:
        raise SalaryExtractionError("Cursor SDK не получил текст документа")

    project_root = Path(__file__).resolve().parents[4]
    sdk_root = project_root / "desktop" / "sdk-agent"
    runner = sdk_root / "src" / "runner.ts"
    tsx = sdk_root / "node_modules" / ".bin" / (
        "tsx.cmd" if sys.platform == "win32" else "tsx"
    )
    if not runner.is_file() or not tsx.is_file():
        raise SalaryExtractionError(
            "Cursor SDK не установлен: выполните npm install в desktop/sdk-agent"
        )
    if not settings.cursor_api_key.strip():
        raise SalaryExtractionError("CURSOR_API_KEY не настроен в backend/.env")

    prompt = _salary_prompt(name, text)
    command = {
        "type": "run",
        "id": str(uuid.uuid4()),
        "prompt": prompt,
        "model": settings.cursor_workflow_model,
        "cwd": str(project_root),
        "mode": "run",
        "tools": [],
        "useTools": False,
        "restrictBuiltins": True,
    }
    env = dict(os.environ)
    env["CURSOR_API_KEY"] = settings.cursor_api_key
    env.setdefault("NODE_NO_WARNINGS", "1")
    try:
        completed = subprocess.run(
            [str(tsx), str(runner)],
            cwd=str(sdk_root),
            input=json.dumps(command, ensure_ascii=False) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SalaryExtractionError(f"Cursor SDK не обработал документ: {exc}") from exc

    answer = ""
    error = ""
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") in {"final", "done"} and str(
            event.get("answer") or ""
        ).strip():
            answer = str(event["answer"]).strip()
        if event.get("type") == "error":
            error = str(event.get("message") or event.get("error") or "").strip()
    if completed.returncode != 0 or not answer:
        detail = error or completed.stderr.strip() or "пустой ответ"
        raise SalaryExtractionError(f"Cursor SDK: {detail}")
    return _parse_answer(answer)


def _salary_prompt(name: str, text: str) -> str:
    return f"""Разбери документ с окладами «{name}».
Оклад привязан к должности, не к сотруднику. Извлеки ВСЕ строки без пропусков.
Верни только JSON без markdown:
{{
  "effective_from": "YYYY-MM-DD",
  "rows": [
    {{
      "position_name": "точное название должности",
      "amount": "число без пробелов и обозначения валюты",
      "currency": "RUB"
    }}
  ]
}}
Если указана только дата утверждения — используй её. Если указан период только годом,
используй первое января этого года. Не включай надбавки, итог с надбавкой, количество
ставок, номера строк и итоги: amount — именно базовый оклад.

Текст документа:
--- START DOCUMENT ---
{text}
--- END DOCUMENT ---"""


def _parse_answer(answer: str) -> dict[str, Any]:
    raw = answer.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise SalaryExtractionError("Cursor SDK не вернул JSON")
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SalaryExtractionError(f"Некорректный JSON Cursor SDK: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise SalaryExtractionError("В ответе Cursor SDK отсутствует массив rows")
    return payload
