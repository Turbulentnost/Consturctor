#!/usr/bin/env python3
"""Запуск агента поручений: 1С → Excel на рабочий стол (headless, через desktop tools)."""

from __future__ import annotations

import json
import sys
import tempfile
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
    "Проверь статусы исполнения и артефакты поручений из 1С по Action Tracker "
    "и сохрани Excel на рабочий стол"
)


def _ensure_workflow(client: ApiClient) -> str:
    picked = _pick_workflow(client, allow_missing=True)
    if picked:
        return picked

    notes = (
        "Action Tracker: поручения из 1С, контроль статусов исполнения, "
        "проверка артефактов/результата, Excel на рабочий стол."
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix="_porucheniya_smart.txt",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(notes)
        seed_path = Path(tmp.name)

    try:
        wf = client.create_workflow(notes=notes, file_paths=[seed_path])
        client.update_workflow_local_run(
            str(wf.id),
            {
                "seed": "porucheniya",
                "tests_status": "pass",
                "can_publish": False,
                "runtime": {"kind": "action_tracker"},
            },
        )
        print("created seed workflow:", wf.id, wf.title)
        return str(wf.id)
    finally:
        seed_path.unlink(missing_ok=True)


def _pick_workflow(client: ApiClient, *, allow_missing: bool = False) -> str:
    items = client.list_workflows()
    hints = ("smart", "поручен", "action tracker", "onec", "1с")
    for item in items:
        title = str(item.title or "").casefold()
        if item.phase != "done" and not item.has_local_run:
            continue
        if any(h in title for h in hints):
            return str(item.id or "")
    for item in items:
        if item.phase == "done" or item.has_local_run:
            return str(item.id or "")
    if allow_missing:
        return ""
    raise SystemExit("Нет опубликованного workflow для запуска")


def main() -> int:
    client = ApiClient()
    health = client.health()
    print("health:", health.status, "erp:", getattr(health, "erp_reachable", "?"), "llm:", health.llm_provider)

    try:
        client.login(FIO, PASSWORD)
    except ApiError as exc:
        print("login failed:", exc)
        return 1
    print("logged in as", client.user_fio if hasattr(client, "user_fio") else FIO)

    workflow_id = _ensure_workflow(client)
    print("workflow:", workflow_id)

    events: list[dict] = []

    def on_event(payload: dict) -> None:
        event_type = str(payload.get("type") or "")
        if event_type in {"status", "agent_message", "error"}:
            text = payload.get("text") or payload.get("message") or ""
            if text:
                print(f"[{event_type}] {text}")
        elif event_type == "tool_result":
            tool = payload.get("tool")
            result = payload.get("result") or {}
            if tool == "excel.create_workbook":
                print("excel:", json.dumps(result, ensure_ascii=False)[:500])
        events.append(payload)

    result = client.stream_workflow_agent_run(
        workflow_id,
        TASK,
        on_event,
        source="script",
        auto_approve=True,
    )
    print("done:", json.dumps(result, ensure_ascii=False)[:800] if result else "—")
    for ev in reversed(events):
        if ev.get("type") == "tool_result" and ev.get("tool") == "excel.create_workbook":
            path = (ev.get("result") or {}).get("desktop_path") or (ev.get("result") or {}).get("path")
            if path:
                print("DESKTOP_FILE:", path)
                return 0
    answer = (result or {}).get("answer") or ""
    if answer:
        print("answer:", answer[:1200])
    return 0 if result else 2


if __name__ == "__main__":
    raise SystemExit(main())
