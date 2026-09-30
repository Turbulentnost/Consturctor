"""One-shot run of the local Cursor SDK agent (desktop/sdk-agent runner)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from app.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SDK_ROOT = PROJECT_ROOT / "desktop" / "sdk-agent"


class CursorSdkLocalError(RuntimeError):
    pass


def run_cursor_sdk(
    prompt: str,
    *,
    images: list[dict[str, Any]] | None = None,
    model: str = "",
    timeout: int = 300,
) -> str:
    """Send one prompt (optionally with page images) and return the final answer."""
    runner = SDK_ROOT / "src" / "runner.ts"
    tsx = SDK_ROOT / "node_modules" / ".bin" / ("tsx.cmd" if sys.platform == "win32" else "tsx")
    if not runner.is_file() or not tsx.is_file():
        raise CursorSdkLocalError(
            "Cursor SDK не установлен: выполните npm install в desktop/sdk-agent"
        )
    if not settings.cursor_api_key.strip():
        raise CursorSdkLocalError("CURSOR_API_KEY не настроен в backend/.env")

    command = {
        "type": "run",
        "id": str(uuid.uuid4()),
        "prompt": prompt,
        "model": model or settings.cursor_workflow_model,
        "cwd": str(PROJECT_ROOT),
        "mode": "run",
        "tools": [],
        "useTools": False,
        "restrictBuiltins": True,
        "images": list(images or []),
    }
    env = dict(os.environ)
    env["CURSOR_API_KEY"] = settings.cursor_api_key
    env.setdefault("NODE_NO_WARNINGS", "1")
    try:
        completed = subprocess.run(
            [str(tsx), str(runner)],
            cwd=str(SDK_ROOT),
            input=json.dumps(command, ensure_ascii=False) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CursorSdkLocalError(f"Cursor SDK не ответил: {exc}") from exc

    answer = ""
    error = ""
    streamed: list[str] = []
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "assistant":
            streamed.append(str(event.get("text") or ""))
        if event.get("type") in {"final", "done"} and str(event.get("answer") or "").strip():
            answer = str(event["answer"]).strip()
        if event.get("type") == "error":
            error = str(event.get("message") or event.get("error") or "").strip()
    if not answer and completed.returncode == 0:
        answer = "".join(streamed).strip()
    if completed.returncode != 0 or not answer:
        detail = error or completed.stderr.strip()[-2000:] or "пустой ответ"
        raise CursorSdkLocalError(f"Cursor SDK: {detail}")
    return answer
