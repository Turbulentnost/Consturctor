#!/usr/bin/env python3
"""Smoke-run SD meeting agent via agent_sidecar (stdout events, ~3 min)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

WORKFLOW_ID = "622388eb-b81e-4471-89a0-46979f5926b0"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO = BACKEND_ROOT.parent
DESKTOP = REPO / "desktop"
SIDECAR = REPO / "orchestrator" / "desktop-electron" / "pybridge" / "agent_sidecar.py"
TIMEOUT_SEC = 180


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


def main() -> int:
    _load_dotenv(DESKTOP / ".env")
    _load_dotenv(BACKEND_ROOT / ".env")
    backend_url = (os.environ.get("BACKEND_URL") or "http://192.168.1.157:7812").strip()
    if not SIDECAR.is_file():
        print(f"sidecar not found: {SIDECAR}", file=sys.stderr)
        return 1

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
        bufsize=1,
    )
    assert proc.stdin and proc.stdout and proc.stderr

    tool_calls: list[str] = []
    statuses: list[str] = []
    errors: list[str] = []
    done = threading.Event()

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
            if mtype == "run_adopted":
                statuses.append("run_adopted")
            if mtype == "error":
                errors.append(str(msg.get("message") or msg))
            payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
            if str(payload.get("type") or "") == "tool_call":
                name = str(payload.get("name") or payload.get("tool") or "")
                if name:
                    tool_calls.append(name)
            if mtype in {"result", "error"}:
                done.set()

    threading.Thread(target=read_stderr, daemon=True).start()
    threading.Thread(target=read_stdout, daemon=True).start()

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj, ensure_ascii=True) + "\n")
        proc.stdin.flush()

    send({"type": "configure", "backendUrl": backend_url, "token": None})
    time.sleep(1)
    send({"type": "cancel", "workflowId": WORKFLOW_ID})
    time.sleep(0.5)
    send(
        {
            "type": "run",
            "id": f"run-smoke-{int(time.time())}",
            "workflowId": WORKFLOW_ID,
            "message": "SD meeting prep smoke run.",
            "forceRestart": True,
        }
    )

    deadline = time.time() + TIMEOUT_SEC
    while time.time() < deadline and not done.is_set():
        time.sleep(1)
    if not done.is_set():
        send({"type": "cancel", "workflowId": WORKFLOW_ID})
        time.sleep(1)
        try:
            send({"type": "shutdown"})
        except Exception:
            pass
        proc.wait(timeout=10)

    print("\n=== SUMMARY ===", flush=True)
    print(f"run_adopted: {'yes' if 'run_adopted' in statuses else 'no'}", flush=True)
    print(f"errors: {len(errors)}", flush=True)
    for err in errors[:5]:
        print(f"  - {err}", flush=True)
    print(f"tool_calls ({len(tool_calls)}):", flush=True)
    for name in tool_calls:
        print(f"  - {name}", flush=True)
    expected = {"outlook.read_calendar", "onec.meeting_protocols", "onec.meeting_service_notes"}
    missing = sorted(expected - set(tool_calls))
    if missing:
        print(f"missing expected tools: {', '.join(missing)}", flush=True)
    return 0 if tool_calls and "run_adopted" not in statuses else 1


if __name__ == "__main__":
    raise SystemExit(main())
