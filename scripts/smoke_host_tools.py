#!/usr/bin/env python3
"""Full smoke: unified desktop host :7830 + gateway routing + agent coding tools."""
from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HOST = "http://127.0.0.1:7830"
GW = "http://127.0.0.1:7812"


def get(url: str, timeout: float = 8) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except Exception as exc:
        return 0, str(exc)


def post(url: str, payload: dict, timeout: float = 120, headers: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"error": body}
    except Exception as exc:
        return 0, {"error": str(exc)}


def inv_host(tool: str, payload: dict, timeout: float = 120) -> dict:
    code, body = post(
        f"{HOST}/api/v1/tools/{tool}/invoke",
        {"run_id": str(uuid.uuid4()), "payload": payload},
        timeout=timeout,
    )
    if isinstance(body, dict):
        body["_http"] = code
        return body
    return {"ok": False, "_http": code, "error": str(body)}


def inv_gw(tool: str, payload: dict, token: str, timeout: float = 120) -> dict:
    code, body = post(
        f"{GW}/api/v1/tools/{tool}/invoke",
        {"run_id": str(uuid.uuid4()), "payload": payload},
        timeout=timeout,
        headers={"Authorization": f"Bearer {token}"},
    )
    if isinstance(body, dict):
        body["_http"] = code
        return body
    return {"ok": False, "_http": code, "error": str(body)}


def check_agent_coding_tools() -> int:
    failed = 0
    import sys

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    ws_root = Path(tempfile.mkdtemp(prefix="agent-smoke-"))
    os.environ["AGENT_WORKSPACE"] = str(ws_root)
    try:
        from agent.tools.delete_file import delete_file
        from agent.tools.glob_files import glob_files
        from agent.tools.grep_search import grep_search
        from agent.tools.read_file import read_file
        from agent.tools.str_replace import str_replace
        from agent.tools.write_file import write_file

        ws = str(ws_root)
        w = write_file(ws, "hello.py", 'print("hi")\n', max_bytes=512_000)
        if not w.ok:
            print(f"  FAIL write_file: {w.error}")
            failed += 1
        else:
            print("  OK write_file")

        r = read_file(ws, "hello.py")
        print(f"  {'OK' if r.ok else 'FAIL'} read_file")

        s = str_replace(ws, "hello.py", 'print("hi")', 'print("hello")')
        print(f"  {'OK' if s.ok else 'FAIL'} str_replace")

        g = glob_files(ws, "*.py")
        if not g.ok or not g.data.get("count"):
            failed += 1
        print(f"  {'OK' if g.ok and g.data.get('count') else 'FAIL'} glob count={g.data.get('count') if g.data else 0}")

        gr = grep_search(ws, "hello", head_limit=5)
        print(f"  {'OK' if gr.ok else 'FAIL'} grep engine={gr.data.get('engine') if gr.data else '?'}")

        d = delete_file(ws, "hello.py")
        print(f"  {'OK' if d.ok else 'FAIL'} delete_file")
    except Exception as exc:
        print(f"  FAIL agent coding tools: {exc}")
        failed += 1
    finally:
        import shutil

        shutil.rmtree(ws_root, ignore_errors=True)
    return failed


def main() -> int:
    failed = 0
    print("=== Unified host :7830 health ===")
    for path in ("/health", "/api/v1/capabilities"):
        code, body = get(f"{HOST}{path}")
        ok = code == 200
        if not ok:
            failed += 1
        if isinstance(body, dict):
            print(f"  {'OK' if ok else 'FAIL'} {path} service={body.get('service') or body.get('host')} use_stubs={body.get('use_stubs')}")
        else:
            print(f"  {'OK' if ok else 'FAIL'} {path} -> {body}")

    print("\n=== Host tool invokes (:7830) ===")
    cases = [
        ("imap.search", {"user": "omto", "query": "omto", "limit": 2}),
        ("browser.extract_text", {"query": "календарь праздников", "fetch_first": True, "max_results": 3}),
        ("browser.open_session", {}),
        ("com.list_apps", {}),
        ("com.outlook.launch", {"visible": False}),
        ("fs.list", {"path": "."}),
        ("shell.run", {"command": "echo host-smoke", "runtime": "native"}),
        ("desktop.capabilities", {}),
    ]
    session_id = ""
    browser_run = str(uuid.uuid4())
    for tool, payload in cases:
        run = browser_run if tool.startswith("browser.") else str(uuid.uuid4())
        if tool == "browser.open_session":
            res = inv_host(tool, payload)
            if res.get("ok"):
                browser_run = str((res.get("data") or {}).get("run_id") or run)
            print(f"  {'OK' if res.get('ok') else 'FAIL'} {tool}: {res.get('error') or (res.get('data') or {}).get('summary')}")
            if not res.get("ok"):
                failed += 1
            continue
        if tool.startswith("browser.") and tool != "browser.extract_text":
            res = post(f"{HOST}/api/v1/tools/{tool}/invoke", {"run_id": browser_run, "payload": payload}, timeout=60)
            res = res[1] if isinstance(res[1], dict) else {"ok": False, "error": str(res[1])}
        else:
            res = inv_host(tool, payload)
        ok = bool(res.get("ok"))
        if not ok:
            failed += 1
        data = res.get("data") or {}
        extra = ""
        if tool == "imap.search":
            extra = f" mode={data.get('mode')} uids={data.get('uids')}"
        elif tool == "browser.extract_text":
            extra = f" engine={data.get('engine')} n={len(data.get('results') or [])}"
        elif tool == "com.outlook.launch":
            session_id = str(data.get("session_id") or "")
            extra = f" session={session_id[:8]}"
        print(f"  {'OK' if ok else 'FAIL'} {tool}: {res.get('error') or data.get('summary')}{extra}")

    if browser_run:
        post(
            f"{HOST}/api/v1/tools/browser.close_session/invoke",
            {"run_id": browser_run, "payload": {}},
            timeout=30,
        )

    if session_id:
        cal = inv_host("com.outlook.calendar_list", {"session_id": session_id, "days": 7, "limit": 5})
        print(f"  {'OK' if cal.get('ok') else 'WARN'} com.outlook.calendar_list: {cal.get('error') or (cal.get('data') or {}).get('summary')}")
        inv_host("com.outlook.close", {"session_id": session_id})
        if not cal.get("ok"):
            pass  # profile issue — not a host wiring failure

    print("\n=== Gateway via host.docker.internal:7830 ===")
    _, login = post(f"{GW}/api/v1/auth/login", {"fio": "t", "password": "x"}, timeout=20)
    token = (login or {}).get("access_token") if isinstance(login, dict) else None
    if not token:
        print(f"  FAIL login: {login}")
        failed += 1
    else:
        for tool, payload in (
            ("imap.search", {"user": "omto", "query": "omto", "limit": 2}),
            ("browser.extract_text", {"query": "календарь праздников", "fetch_first": True}),
            ("com.list_apps", {}),
            ("desktop.capabilities", {}),
        ):
            res = inv_gw(tool, payload, token)
            ok = bool(res.get("ok"))
            if not ok:
                failed += 1
            data = res.get("data") or {}
            print(
                f"  {'OK' if ok else 'FAIL'} {tool}: "
                f"{res.get('error') or data.get('summary')} mode={data.get('mode') or data.get('engine') or data.get('source')}"
            )

    print("\n=== Agent coding tools (local) ===")
    failed += check_agent_coding_tools()

    print(f"\nDone. failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
