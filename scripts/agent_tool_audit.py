#!/usr/bin/env python3
"""Agent-style audit of platform tools via gateway :7812."""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path
from urllib import error, request

BASE = "http://127.0.0.1:7812"
RESULTS: list[dict] = []


def req(method: str, path: str, body: dict | None = None, token: str | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    http_req = request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with request.urlopen(http_req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:500]}
        return exc.code, payload
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def note(tool: str, ok: bool, detail, expected: str = "works") -> None:
    RESULTS.append({"tool": tool, "ok": ok, "expected": expected, "detail": detail})


def invoke(token: str, run_id: str, name: str, payload: dict, expect_ok: bool = True) -> dict:
    code, body = req(
        "POST",
        f"/api/v1/tools/{name}/invoke",
        {"run_id": run_id, "payload": payload},
        token=token,
    )
    ok = code == 200 and isinstance(body, dict) and body.get("ok") is True
    detail = {
        "http": code,
        "ok": body.get("ok") if isinstance(body, dict) else None,
        "error": body.get("error") if isinstance(body, dict) else None,
        "summary": (body.get("data") or {}).get("summary")
        if isinstance(body, dict) and isinstance(body.get("data"), dict)
        else None,
        "data_keys": sorted((body.get("data") or {}).keys())
        if isinstance(body, dict) and isinstance(body.get("data"), dict)
        else None,
        "preview": str(body)[:500],
    }
    note(name, ok if expect_ok else code == 200, detail)
    return body if isinstance(body, dict) else {}


def main() -> int:
    code, health = req("GET", "/api/v1/health")
    if code != 200:
        code, health = req("GET", "/health")
    note(
        "gateway.health",
        code == 200,
        {"status": code, "body": health if isinstance(health, dict) else str(health)[:300]},
    )
    code_alias, _ = req("GET", "/api/v1/health")
    note("gateway.health_api_v1", code_alias == 200, {"status": code_alias})

    code, login = req("POST", "/api/v1/auth/login", {"fio": "Тест Агент", "password": "stub"})
    token = ""
    if isinstance(login, dict):
        token = login.get("access_token") or login.get("token") or ""
        if not token and isinstance(login.get("data"), dict):
            token = login["data"].get("access_token") or ""
    note(
        "auth.login",
        bool(token),
        {
            "status": code,
            "keys": list(login.keys()) if isinstance(login, dict) else type(login).__name__,
            "preview": str(login)[:400],
        },
    )
    if not token:
        _print_report()
        return 1

    code, tools = req("GET", "/api/v1/tools", token=token)
    items = tools.get("items") if isinstance(tools, dict) else None
    note(
        "tools.list",
        code == 200 and isinstance(items, list),
        {"status": code, "count": len(items) if isinstance(items, list) else None, "items": items},
    )

    run_id = str(uuid.uuid4())

    # IMAP
    invoke(token, run_id, "imap.list_unread", {"limit": 2, "user": "omto"})
    invoke(token, run_id, "imap.search", {"user": "omto", "query": "omto", "limit": 2})
    invoke(token, run_id, "imap.fetch_message", {"uid": 8801, "user": "omto"})
    invoke(token, run_id, "imap.fetch_attachments", {"uid": 8801, "user": "omto"})

    # 1C
    invoke(token, run_id, "onec.odata_get", {"top": 3, "entity": "Document_ТД_ВходящаяКорреспонденция"})
    invoke(token, run_id, "onec.sql_query", {"sql": "SELECT 1 AS x"})

    # Browser session flow
    invoke(token, run_id, "browser.open_session", {})
    invoke(token, run_id, "browser.navigate", {"url": "https://example.com"})
    snap = invoke(token, run_id, "browser.snapshot", {})
    refs = ((snap.get("data") or {}).get("elements")) or []
    ref = refs[0]["ref"] if refs else "e1"
    invoke(token, run_id, "browser.click", {"ref": ref})
    invoke(token, run_id, "browser.type", {"selector": "#q", "text": "test"})
    invoke(token, run_id, "browser.extract_text", {"query": "новости Ростова"})
    invoke(token, run_id, "browser.screenshot", {"url": "https://example.com"})
    invoke(token, run_id, "browser.tabs", {"action": "list"})
    invoke(token, run_id, "browser.close_session", {})
    closed = invoke(token, run_id, "browser.snapshot", {}, expect_ok=False)
    note(
        "browser.session_after_close",
        closed.get("ok") is False,
        {"error": closed.get("error"), "preview": str(closed)[:300]},
        expected="SESSION_NOT_FOUND",
    )

    # Shell / FS
    invoke(token, run_id, "shell.run", {"command": "echo hello-agent", "runtime": "sandbox"})
    invoke(token, run_id, "fs.list", {"path": "."})
    invoke(token, run_id, "fs.stat", {"path": "."})

    # COM
    invoke(token, run_id, "com.list_apps", {})
    com = invoke(token, run_id, "com.connect", {"app": "outlook"})
    sid = ((com.get("data") or {}).get("session_id")) if isinstance(com, dict) else None
    if sid:
        invoke(token, run_id, "com.invoke", {"session_id": sid, "method": "GetNamespace", "args": ["MAPI"]})
        invoke(token, run_id, "com.release", {"session_id": sid})

    ol = invoke(token, run_id, "com.outlook.launch", {"visible": False})
    osid = ((ol.get("data") or {}).get("session_id")) if isinstance(ol, dict) else None
    cal = invoke(token, run_id, "com.outlook.calendar_list", {"session_id": osid or "", "days": 7, "limit": 5})
    events = ((cal.get("data") or {}).get("events")) if isinstance(cal, dict) else None
    if events:
        invoke(
            token,
            run_id,
            "com.outlook.calendar_get",
            {"session_id": osid or "", "entry_id": events[0].get("entry_id"), "include_body": True},
        )
    invoke(token, run_id, "com.outlook.close", {"session_id": osid or "", "quit": False})

    code, sb = req("GET", "/api/v1/tools/sandbox", token=token)
    note("sandbox.list", code == 200, {"status": code, "preview": str(sb)[:500]})
    code, sball = req("POST", "/api/v1/tools/sandbox/run-all", {}, token=token)
    note("sandbox.run_all", code == 200, {"status": code, "preview": str(sball)[:1500]})

    # Local coding agent runtime
    try:
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))
        from agent.tool_registry import ToolContext, execute_tool, get_tool_schemas
        from agent.tools.todo_write import TodoStore
        from agent.types import AgentConfig

        ws = Path(tempfile.mkdtemp())
        cfg = AgentConfig(workspace_root=str(ws), browser_enabled=True, browser_url="http://127.0.0.1:7824")
        ctx = ToolContext(config=cfg, todo_store=TodoStore())
        r1 = execute_tool(ctx, "write_file", {"path": "a.py", "contents": "print(1)\n"})
        r2 = execute_tool(ctx, "str_replace", {"path": "a.py", "old_string": "print(1)", "new_string": "print(2)"})
        r3 = execute_tool(ctx, "grep", {"pattern": "print", "path": "a.py"})
        r4 = execute_tool(ctx, "run_terminal", {"command": 'py -3.12 -c "print(42)"'})
        note("agent.write_file", r1.ok, r1.to_dict())
        note("agent.str_replace", r2.ok, r2.to_dict())
        note("agent.grep", r3.ok, r3.to_dict())
        note("agent.run_terminal", r4.ok, r4.to_dict())
        schemas = {s["function"]["name"] for s in get_tool_schemas(browser_enabled=True)}
        note(
            "agent.browser_schemas",
            "browser.open_session" in schemas,
            {"has_browser": "browser.navigate" in schemas, "count": len(schemas)},
        )
        r5 = execute_tool(ctx, "browser.open_session", {})
        r6 = execute_tool(ctx, "browser.extract_text", {"query": "тест"})
        note("agent.browser.open_session", r5.ok, r5.to_dict())
        note("agent.browser.extract_text", r6.ok, r6.to_dict())
    except Exception as exc:  # noqa: BLE001
        note("agent.runtime", False, {"error": str(exc)})

    _print_report()
    failed = [x for x in RESULTS if not x["ok"]]
    out = Path(__file__).resolve().parents[1] / "logs" / "agent_tool_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON report: {out}")
    return 1 if failed else 0


def _print_report() -> None:
    failed = [x for x in RESULTS if not x["ok"]]
    print("=== AGENT TOOL AUDIT ===")
    print("total", len(RESULTS), "failed", len(failed))
    for item in RESULTS:
        mark = "OK " if item["ok"] else "BAD"
        detail = item["detail"]
        err = ""
        if isinstance(detail, dict):
            err = detail.get("error") or detail.get("summary") or detail.get("preview") or ""
            if isinstance(err, str):
                err = err.replace("\n", " ")[:180]
        print(f"{mark} | {item['tool']} | {err}")
    print("=== FAILED ONLY ===")
    for item in failed:
        print(json.dumps(item, ensure_ascii=False)[:900])


if __name__ == "__main__":
    raise SystemExit(main())
