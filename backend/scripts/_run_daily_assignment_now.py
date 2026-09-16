#!/usr/bin/env python3
"""Start the published daily AST00 agent once via Constructor sidecar."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from sqlalchemy.orm.attributes import flag_modified

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO = BACKEND_ROOT.parent
DESKTOP = REPO / "desktop"
SIDECAR = REPO / "desktop-electron" / "pybridge" / "agent_sidecar.py"
WORKFLOW_ID = "af314914-bb0a-4cb7-95e0-6ef87698d3f5"
TIMEOUT_SEC = 900
RUN_MESSAGE = (
    "Проверь журнал АСТ00 заказчика Амураль Игорь Борисович и доложи устно: "
    "просрочки и список на сегодня. Повтори проверенную цепочку. "
    "Запись в 1С не делай."
)
EXCEL_WRITE = {"excel.create_workbook", "excel.edit_workbook"}
ONEC_WRITE = {
    "onec.erp_assignments_write",
    "onec.odata_post",
    "onec.odata_patch",
    "onec.attach_file",
}


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _mint_owner_token() -> tuple[str, str]:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.core.jwt import create_access_token
    from app.db.session import SessionLocal, init_db
    from app.models.agent_run import AgentRun
    from app.models.user import AppUser
    from app.models.workflow import Workflow
    from app.services.agent_runs import USER_CANCEL_ANSWER, finish_agent_run
    from app.services.sessions import DEFAULT_CLIENT, current_session_id

    init_db()
    db = SessionLocal()
    try:
        row = db.get(Workflow, WORKFLOW_ID)
        if row is None:
            raise SystemExit(f"workflow not found: {WORKFLOW_ID}")
        user = db.get(AppUser, row.user_id)
        if user is None:
            raise SystemExit(f"owner not found: {row.user_id}")
        local = dict(row.local_run or {})
        if local.get("sdk_agent_id"):
            local["sdk_agent_id"] = ""
            row.local_run = local
            flag_modified(row, "local_run")
            db.add(row)
            db.commit()
            print("cleared sdk_agent_id for a fresh agent", flush=True)
        started = (
            db.query(AgentRun)
            .filter(AgentRun.workflow_id == WORKFLOW_ID, AgentRun.status == "started")
            .all()
        )
        for run in started:
            finish_agent_run(
                db,
                run_id=run.id,
                status="canceled",
                answer=USER_CANCEL_ANSWER,
                events=run.events_json if isinstance(run.events_json, list) else [],
                message=run.message or "",
            )
            print(f"canceled leftover started run {run.id}", flush=True)
        sid = current_session_id(user.id, DEFAULT_CLIENT)
        token = create_access_token(
            user_id=user.id,
            fio=user.fio,
            department=user.department or "",
            position=user.position or "",
            session_id=sid,
            client=DEFAULT_CLIENT,
        )
        print(f"owner={user.fio} title={row.title} session={'reuse' if sid else 'new'}", flush=True)
        return token, user.fio
    finally:
        db.close()


def _decide_hitl(tool: str) -> bool:
    name = (tool or "").strip()
    if name in EXCEL_WRITE:
        return True
    if name in ONEC_WRITE or name.startswith("outlook.") or name.startswith("email."):
        return False
    return False


def _decide_answer(question: str) -> str:
    text = (question or "").casefold()
    if any(word in text for word in ("запис", "закры", "исполн", "1с", "поручен")):
        return (
            "Нет. Запись в 1С не нужна. Сделай устный доклад по журналу АСТ00 "
            "заказчика Амураль Игорь Борисович."
        )
    if "excel" in text or "трекер" in text or "файл" in text:
        return "Да, если файла нет — создай Action Tracker из списка журнала."
    return (
        "Продолжай проверенную цепочку. Заказчик Амураль Игорь Борисович. "
        "Без задач, OCR и записи в 1С."
    )


def main() -> int:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    _load_dotenv(BACKEND_ROOT / ".env")
    _load_dotenv(DESKTOP / ".env")
    if not SIDECAR.is_file():
        print(f"sidecar not found: {SIDECAR}", file=sys.stderr)
        return 1
    token, fio = _mint_owner_token()
    backend_url = (
        os.environ.get("ASSIGNMENT_RUN_BACKEND") or "http://127.0.0.1:7812"
    ).strip()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["CONSTRUCTOR_DESKTOP_ROOT"] = str(DESKTOP)
    env["PYTHONPATH"] = str(DESKTOP)
    proc = subprocess.Popen(
        [sys.executable, "-u", str(SIDECAR)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(DESKTOP),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    tool_calls: list[str] = []
    errors: list[str] = []
    answers: list[str] = []
    done = threading.Event()
    send_lock = threading.Lock()

    def send(obj: dict) -> None:
        with send_lock:
            proc.stdin.write(json.dumps(obj, ensure_ascii=True) + "\n")
            proc.stdin.flush()

    def read_stderr() -> None:
        for line in proc.stderr:
            text = line.rstrip()
            if text:
                print(f"[stderr] {text}", flush=True)

    def read_stdout() -> None:
        for line in proc.stdout:
            text = line.strip()
            if not text:
                continue
            print(text, flush=True)
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            mtype = str(msg.get("type") or "")
            if mtype == "error":
                errors.append(str(msg.get("message") or msg))
            if mtype == "hitl":
                tool = str(msg.get("tool") or "")
                request_id = str(msg.get("requestId") or "")
                approved = _decide_hitl(tool)
                print(f"[hitl] {tool} -> {'approve' if approved else 'reject'}", flush=True)
                send({"type": "hitl", "requestId": request_id, "approved": approved})
            if mtype == "question":
                request_id = str(msg.get("requestId") or "")
                question = str(msg.get("question") or "")
                answer = _decide_answer(question)
                print(f"[question] {question[:180]}", flush=True)
                send({"type": "answer", "requestId": request_id, "ok": True, "answer": answer})
            payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
            if str(payload.get("type") or "") == "tool_call":
                name = str(payload.get("name") or payload.get("tool") or "")
                if name:
                    tool_calls.append(name)
                    print(f"[tool] {name}", flush=True)
            if mtype == "result":
                answers.append(str(msg.get("answer") or ""))
                done.set()
            if mtype == "error" and msg.get("runId"):
                done.set()

    threading.Thread(target=read_stderr, daemon=True).start()
    threading.Thread(target=read_stdout, daemon=True).start()
    send(
        {
            "type": "configure",
            "backendUrl": backend_url,
            "token": token,
            "login": fio,
        }
    )
    time.sleep(1)
    send({"type": "cancel", "workflowId": WORKFLOW_ID})
    time.sleep(0.4)
    send(
        {
            "type": "run",
            "id": f"run-daily-{int(time.time())}",
            "workflowId": WORKFLOW_ID,
            "message": RUN_MESSAGE,
            "source": "chat",
            "forceRestart": True,
        }
    )
    deadline = time.time() + TIMEOUT_SEC
    while time.time() < deadline and not done.is_set():
        time.sleep(1)
    if not done.is_set():
        print("timeout, canceling", flush=True)
        send({"type": "cancel", "workflowId": WORKFLOW_ID})
        time.sleep(1)
        try:
            send({"type": "shutdown"})
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    else:
        try:
            send({"type": "shutdown"})
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("\n=== SUMMARY ===", flush=True)
    print(f"errors: {len(errors)}", flush=True)
    for err in errors[:8]:
        print(f"  - {err}", flush=True)
    print(f"tool_calls ({len(tool_calls)}):", flush=True)
    for name in tool_calls:
        print(f"  - {name}", flush=True)
    if answers:
        print("answer:", flush=True)
        print(answers[-1][:4000], flush=True)
    return 0 if tool_calls and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
