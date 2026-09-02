"""One-shot trial run for a designed workflow. Not imported by the app."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api_client import ApiClient
from app.config import backend_url
from app.sdk_agent.bridge import CursorSdkBridge
from app.sdk_agent.files import prepare_sdk_workspace
from app.sdk_agent.prompt import build_demo_sdk_prompt
from app.tools.runtime_api import configure as configure_runtime_api


WF = "5c03a6e6-55ff-4f07-a553-bb33c221ef04"


def on_question(payload: dict) -> dict:
    args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    question = str(payload.get("question") or args.get("question") or "")
    print("QUESTION:", question[:240], flush=True)
    if args.get("needsFile") or "файл" in question.casefold() or "прикрепи" in question.casefold():
        return {
            "ok": True,
            "answer": (
                "Файл уже в materials/attachments: "
                "Отчет по количеству совещаний 2026 new.xlsx"
            ),
        }
    return {"ok": True, "answer": "Как в playbook и ответах проектирования."}


def on_event(payload: dict) -> None:
    kind = str(payload.get("type") or "")
    if kind in {"thinking", "assistant"}:
        text = str(payload.get("text") or "")[:180].replace("\n", " ")
        if text:
            print(f"{kind}: {text}", flush=True)
        return
    if kind in {"tool_call", "tool_result", "status", "error", "done", "final"}:
        tool = payload.get("tool") or ""
        extra = payload.get("error") or payload.get("text") or payload.get("status") or ""
        print(f"{kind} {tool} {extra}".strip(), flush=True)


def main() -> int:
    token = (os.environ.get("CONSTRUCTOR_TOKEN") or "").strip()
    if not token:
        print("CONSTRUCTOR_TOKEN is empty", file=sys.stderr)
        return 2
    api = ApiClient(base_url=backend_url())
    api.set_token(token)
    configure_runtime_api(token=token, base_url=api.base_url)
    record = api.get_workflow(WF)
    print(f"workflow phase={record.phase} title={record.title}", flush=True)
    bridge = CursorSdkBridge()
    bridge.check_ready()
    cwd = bridge.workspace_cwd(WF)
    prepare_sdk_workspace(api, WF, cwd, workflow=record)
    print(f"cwd={cwd}", flush=True)
    prompt = build_demo_sdk_prompt(record, resume=False)
    prompt += (
        "\n\nОбразец входного файла уже лежит в materials/attachments "
        "(Отчет по количеству совещаний 2026 new.xlsx). "
        "Читай его через excel.list_files и excel.read_workbook. "
        "Не спрашивай файл повторно. Не resume предыдущего зависшего прогона."
    )
    result = bridge.run(
        prompt=prompt,
        workflow_id=WF,
        cwd=cwd,
        resume_agent_id="",
        on_event=on_event,
        on_question=on_question,
        confirm_writes=False,
    )
    answer = str(result.get("answer") or "").strip()
    agent_id = str(result.get("agent_id") or "").strip()
    print("RUN_STATUS", result.get("status"), "agent", agent_id, flush=True)
    print("ANSWER_HEAD", answer[:800], flush=True)
    api.finish_local_demo_workflow(WF, answer=answer, events=[])
    again = api.get_workflow(WF)
    local = again.local_run if isinstance(again.local_run, dict) else {}
    print(
        json.dumps(
            {
                "phase": again.phase,
                "demo_ok": local.get("demo_ok"),
                "can_run_demo": local.get("can_run_demo"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
