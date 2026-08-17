#!/usr/bin/env python3
"""Smoke: onec.com microservice + orchestrator routing."""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid

sys.stdout.reconfigure(encoding="utf-8")

HOST = "http://127.0.0.1:7831"
ORCH = "http://127.0.0.1:7825"


def post(url: str, payload: dict, timeout: float = 60) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main() -> int:
    failed = 0
    run = str(uuid.uuid4())

    print("=== Direct :7831 ===")
    for tool in ("onec.com.status", "onec.com.connect", "onec.com.query_tasks"):
        payload = {"mine_only": True, "limit": 10} if tool == "onec.com.query_tasks" else {}
        try:
            body = post(f"{HOST}/api/v1/tools/{tool}/invoke", {"run_id": run, "payload": payload}, timeout=180)
            ok = body.get("ok")
            data = body.get("data") or {}
            extra = f" count={data.get('count')}" if tool == "onec.com.query_tasks" else ""
            print(f"  {'OK' if ok else 'FAIL'} {tool}: {data.get('summary')} source={data.get('source')}{extra}")
            if not ok:
                failed += 1
                print(f"    err={body.get('error')}")
        except Exception as exc:
            print(f"  FAIL {tool}: {exc}")
            failed += 1

    print("\n=== Orchestrator :7825 ===")
    for tool, payload in (
        ("onec.com.status", {}),
        ("onec.com.query_tasks", {"mine_only": True, "limit": 10}),
    ):
        try:
            body = post(
                f"{ORCH}/api/v1/tools/{tool}/invoke",
                {"run_id": run, "payload": payload},
                timeout=120,
            )
            ok = body.get("ok")
            data = body.get("data") or {}
            print(f"  {'OK' if ok else 'FAIL'} {tool}: {data.get('summary')} count={data.get('count')}")
            if not ok:
                failed += 1
                print(f"    err={(body.get('error') or '')[:200]}")
        except Exception as exc:
            print(f"  FAIL {tool}: {exc}")
            failed += 1

    print(f"\nDone failed={failed}")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
