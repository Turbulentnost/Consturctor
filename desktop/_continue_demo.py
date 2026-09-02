"""One-shot trial run for a designed workflow. Not imported by the app."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from app.api_client import ApiClient
from app.config import backend_url, erp_login, erp_password
from app.sdk_agent.bridge import CursorSdkBridge
from app.sdk_agent.files import prepare_sdk_workspace
from app.sdk_agent.prompt import build_demo_sdk_prompt
from app.tools.runtime_api import configure as configure_runtime_api


WF = "5c03a6e6-55ff-4f07-a553-bb33c221ef04"


def _p(*parts: object) -> None:
    text = " ".join(str(part) for part in parts)
    print(text.replace("\n", " ")[:400], flush=True)


def on_question(payload: dict) -> dict:
    args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    question = str(payload.get("question") or args.get("question") or "")
    _p("QUESTION:", question[:240])
    if args.get("needsFile") or "файл" in question.casefold() or "прикрепи" in question.casefold():
        return {
            "ok": True,
            "answer": (
                "Файл уже в materials/attachments: "
                "Отчет по количеству совещаний 2026 new.xlsx"
            ),
        }
    return {"ok": True, "answer": "Как в playbook и ответах проектирования."}


def main() -> int:
    api = ApiClient(base_url=backend_url())
    token = (os.environ.get("CONSTRUCTOR_TOKEN") or "").strip()
    if token:
        api.set_token(token)
    else:
        fio, pwd = erp_login(), erp_password()
        if not fio or not pwd:
            _p("NO_SESSION: set CONSTRUCTOR_TOKEN or ERP_LOGIN/ERP_PASSWORD")
            return 2
        api.login(fio, pwd)
        token = str(api.token or "").strip()
    configure_runtime_api(token=token, base_url=api.base_url)
    record = api.get_workflow(WF)
    _p(f"workflow phase={record.phase} title={record.title}")
    bridge = CursorSdkBridge()
    bridge.check_ready()
    cwd = bridge.workspace_cwd(WF)
    prepare_sdk_workspace(api, WF, cwd, workflow=record)
    _p(f"cwd={cwd}")
    prompt = build_demo_sdk_prompt(record, resume=False)
    prompt += (
        "\n\nОбразец входного файла уже лежит в materials/attachments "
        "(Отчет по количеству совещаний 2026 new.xlsx). "
        "Читай его через excel.list_files и excel.read_workbook. "
        "users.current уже доступен — не спрашивай ФИО. "
        "Не спрашивай файл повторно. Не resume предыдущего зависшего прогона."
    )
    events: list[dict] = []

    def on_event(payload: dict) -> None:
        if isinstance(payload, dict) and str(payload.get("type") or "") not in {"ready", "done"}:
            events.append(payload)
        kind = str(payload.get("type") or "")
        if kind in {"thinking", "assistant"}:
            text = str(payload.get("text") or "")[:180].replace("\n", " ")
            if text:
                _p(f"{kind}: {text}")
            return
        if kind in {"tool_call", "tool_result", "status", "error", "done", "final"}:
            tool = payload.get("tool") or ""
            extra = payload.get("error") or payload.get("status") or ""
            _p(f"{kind} {tool} {extra}".strip())

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
    status = str(result.get("status") or "")
    _p("RUN_STATUS", status, "agent", agent_id)
    _p("ANSWER_HEAD", answer[:800])
    if not answer:
        _p("SKIP_FINISH empty answer")
        return 3
    finished = api.finish_local_demo_workflow(WF, answer=answer, events=events)
    local = finished.local_run if isinstance(finished.local_run, dict) else {}
    _p(
        json.dumps(
            {
                "phase": finished.phase,
                "demo_ok": local.get("demo_ok"),
                "can_run_demo": local.get("can_run_demo"),
                "can_publish": local.get("can_publish"),
                "tests_status": local.get("tests_status"),
                "tools": local.get("live_tools_invoked"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if local.get("demo_ok") else 4


if __name__ == "__main__":
    raise SystemExit(main())
