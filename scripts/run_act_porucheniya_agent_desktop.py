#!/usr/bin/env python3
"""Запуск агента реестра ACT: OData Document_ТД_Поручения → Excel на рабочий стол."""

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
    "Выгрузи реестр поручений ACT (Document_ТД_Поручения) из 1С через OData "
    "и сохрани Excel на рабочий стол с форматированием по каждому ACT00-***"
)


def _ensure_workflow(client: ApiClient) -> str:
    items = client.list_workflows()
    hints = ("act", "аст", "реестр поручений", "act registry")
    for item in items:
        title = str(item.title or "").casefold()
        if any(h in title for h in hints):
            return str(item.id or "")

    notes = (
        "ACT registry: реестр поручений Document_ТД_Поручения через OData 1С ERP. "
        "Журнал ACT00-*** → Excel на рабочий стол с цветовой критичностью по сроку устранения."
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix="_act_porucheniya.txt",
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
                "seed": "act_porucheniya",
                "tests_status": "pass",
                "can_publish": False,
                "runtime": {"kind": "act_porucheniya"},
            },
        )
        print("created ACT workflow:", wf.id, wf.title)
        return str(wf.id)
    finally:
        seed_path.unlink(missing_ok=True)


def main() -> int:
    client = ApiClient()
    health = client.health()
    print("health:", health.status, "erp:", getattr(health, "erp_reachable", "?"), "llm:", health.llm_provider)

    try:
        client.login(FIO, PASSWORD)
    except ApiError as exc:
        print("login failed:", exc)
        return 1
    print("logged in as", getattr(client, "user_fio", FIO))

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
            if tool in {"excel.create_workbook", "onec.act_porucheniya_registry"}:
                print(tool + ":", json.dumps(result, ensure_ascii=False)[:600])
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
        print("answer:", answer[:1500])
    return 0 if result else 2


if __name__ == "__main__":
    raise SystemExit(main())
