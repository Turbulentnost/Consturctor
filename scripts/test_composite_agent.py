#!/usr/bin/env python3
"""Проверка комплексной задачи ACT-агента (OData → Excel → Word → Outlook)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
sys.path.insert(0, str(DESKTOP))

env_path = ROOT / "infra" / ".env"
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    import os

    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

from app.api_client import ApiClient, ApiError  # noqa: E402

FIO = "Жалыбин Максим Дмитриевич"
PASSWORD = "gm360249"
TASK = (
    "Вытащи из 1С через OData полный реестр поручений ACT, как в типовой задаче, "
    "и сохрани Excel на рабочий стол. "
    "Добавь в созданный Excel новую запись (без номера ACT): "
    "исполнитель — Соколова Анна Петровна, срок 15.10.2026, "
    "задача — Провести аудит закупок медоборудования (тестовая запись). "
    "Составь отчёт по имеющимся поручениям в Word (.docx) на рабочем столе. "
    "Зайди в Outlook, возьми мои совещания на сегодня и допиши их в конец того же docx-файла."
)


def _find_workflow(client: ApiClient) -> str:
    for item in client.list_workflows():
        title = str(item.title or "").casefold()
        if any(h in title for h in ("act", "аст", "реестр поручений", "поручен")):
            return str(item.id or "")
    raise RuntimeError("ACT workflow not found")


def _artifacts() -> None:
    desktop = Path.home() / "Desktop"
    xlsx = list(desktop.glob("act_porucheniya_*.xlsx")) + list(desktop.glob("Поручения.xlsx"))
    docx = list(desktop.glob("act_porucheniya_report_*.docx"))
    print("ARTIFACTS xlsx:", [p.name for p in sorted(xlsx, key=lambda p: p.stat().st_mtime)[-3:]])
    print("ARTIFACTS docx:", [p.name for p in sorted(docx, key=lambda p: p.stat().st_mtime)[-3:]])


def main() -> int:
    _artifacts()
    client = ApiClient()
    print("health:", client.health().status, "llm:", client.health().llm_provider)
    try:
        client.login(FIO, PASSWORD)
    except ApiError as exc:
        print("login failed:", exc)
        return 1

    workflow_id = _find_workflow(client)
    print("workflow:", workflow_id)
    print("TASK:", TASK[:200], "…")

    tools_seen: list[str] = []

    def on_event(payload: dict) -> None:
        event_type = str(payload.get("type") or "")
        if event_type in {"status", "agent_message", "error"}:
            text = payload.get("text") or payload.get("message") or ""
            if text:
                print(f"[{event_type}] {text[:500]}")
        elif event_type == "tool_call":
            tool = str(payload.get("tool") or "")
            tools_seen.append(tool)
            print(f"[tool_call] {tool}")
        elif event_type == "tool_result":
            tool = str(payload.get("tool") or "")
            if tool not in tools_seen:
                tools_seen.append(tool)
            result = payload.get("result") or {}
            print(f"[tool_result] {tool}: {json.dumps(result, ensure_ascii=False)[:600]}")

    try:
        result = client.stream_workflow_agent_run(
            workflow_id,
            TASK,
            on_event,
            source="script",
            auto_approve=True,
        )
    except ApiError as exc:
        print("RUN FAILED:", exc)
        return 2

    print("RESULT intent:", (result or {}).get("intent"))
    print("TOOLS:", tools_seen)
    _artifacts()

    intent = str((result or {}).get("intent") or "")
    if intent != "composite_workflow":
        print("WARN: expected composite_workflow, got", intent)
    required = {
        "onec.act_porucheniya_registry",
        "excel.create_workbook",
        "document.write_docx",
    }
    missing = [t for t in required if t not in tools_seen]
    if missing:
        print("MISSING TOOLS:", missing)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
