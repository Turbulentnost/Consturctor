"""Ask the next regulation question on the gateway when the desktop agent is gone."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def desktop_root() -> Path:
    return Path(__file__).resolve().parents[4] / "desktop"


def run_server_interview_model(
    *,
    prompt: str,
    rules: str,
    workflow_id: str,
    timeout: float = 110,
    mode: str = "question",
) -> str:
    root = desktop_root()
    script = root / "scripts" / "run_interview_prompt.py"
    if not script.is_file():
        raise RuntimeError(f"Не найден {script}")
    text = f"{rules.strip()}\n\n{prompt.strip()}".strip()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        command = [sys.executable, str(script), workflow_id]
        if mode == "document":
            command.append("document")
        completed = subprocess.run(
            command,
            input=text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(root),
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Серверный интервьюер не успел ответить") from exc
    payload = _parse_stdout(completed.stdout)
    if completed.returncode != 0 or payload.get("error"):
        detail = str(payload.get("error") or completed.stderr or "").strip()
        raise RuntimeError(detail[-500:] or "Серверный интервьюер завершился без ответа")
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        raise RuntimeError("Серверный интервьюер вернул пустой ответ")
    return answer


def _parse_stdout(stdout: str) -> dict:
    for line in reversed((stdout or "").splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and ("answer" in data or "error" in data):
            return data
    return {}
