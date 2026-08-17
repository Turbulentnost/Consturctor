#!/usr/bin/env python3
"""Simulate a weak agent: minimal gateway API knowledge, naive but ordered tool probes."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib import error, request

BASE = "http://127.0.0.1:7812"
AGENT_FIO = "Test Agent"
AGENT_PASSWORD = "stub"
PROBE_URL = "https://www.example.com"

# Write/destructive tools — weak agent should not expect success.
SKIP_TOOLS = frozenset(
    {
        "onec.attach_file",
        "onec.odata_post",
        "onec.odata_patch",
    }
)


def req(method: str, path: str, body: dict | None = None, token: str | None = None, timeout: float = 120) -> tuple[int, dict | str]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    http_req = request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with request.urlopen(http_req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"raw": raw[:500]}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def obtain_token() -> str:
    code, login = req("POST", "/api/v1/auth/login", {"fio": AGENT_FIO, "password": AGENT_PASSWORD})
    if isinstance(login, dict):
        token = login.get("access_token") or ""
        if token:
            return token
    code, reg = req(
        "POST",
        "/api/v1/auth/register",
        {"fio": AGENT_FIO, "password": AGENT_PASSWORD, "department": "QA"},
    )
    if isinstance(reg, dict):
        return reg.get("access_token") or ""
    raise SystemExit(f"auth failed login={code} register={reg}")


def invoke(
    token: str,
    run_id: str,
    name: str,
    payload: dict,
    *,
    expect_ok: bool = True,
) -> dict:
    http, body = req(
        "POST",
        f"/api/v1/tools/{name}/invoke",
        {"run_id": run_id, "payload": payload},
        token=token,
        timeout=300.0 if name.startswith("onec.com.") else 120.0,
    )
    ok = http == 200 and isinstance(body, dict) and body.get("ok") is True
    if not expect_ok:
        ok = True
    err = body.get("error") if isinstance(body, dict) else str(body)
    summary = None
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict):
        summary = data.get("summary")
    return {
        "step": f"invoke.{name}",
        "ok": ok,
        "detail": {"http": http, "payload": payload, "error": err, "summary": summary, "data": data or {}},
    }


def main() -> int:
    results: list[dict] = []
    run_id = str(uuid.uuid4())
    state: dict[str, str] = {}

    code, health = req("GET", "/api/v1/health")
    results.append({"step": "health", "ok": code == 200, "detail": {"http": code}})

    token = obtain_token()
    results.append({"step": "auth", "ok": bool(token), "detail": {"fio": AGENT_FIO}})

    code, tools = req("GET", "/api/v1/tools", token=token)
    items = tools.get("items") if isinstance(tools, dict) else []
    names = sorted({x.get("name") for x in items if isinstance(x, dict) and x.get("name")})
    results.append({"step": "tools.list", "ok": code == 200 and bool(names), "detail": {"count": len(names)}})

    def run(name: str, payload: dict, *, expect_ok: bool = True) -> dict:
        row = invoke(token, run_id, name, payload, expect_ok=expect_ok)
        results.append(row)
        return row

    def data(row: dict) -> dict:
        payload = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        return payload.get("data") if isinstance(payload.get("data"), dict) else {}

    # Ordered weak-agent walk (reuse run_id for browser session).
    run("shell.run", {"command": "echo weak-agent", "runtime": "sandbox"})
    run("fs.write", {"path": "_weak_agent_probe.txt", "contents": "probe\n"})
    run("fs.list", {"path": "."})
    run("fs.read", {"path": "_weak_agent_probe.txt"})
    run("fs.stat", {"path": "."})
    run("fs.copy", {"from": "_weak_agent_probe.txt", "to": "_weak_agent_probe_copy.txt"})
    run("fs.move", {"from": "_weak_agent_probe_copy.txt", "to": "_weak_agent_probe_moved.txt"})
    run("fs.build_office_file", {"path": "probe.docx", "template": "blank"})

    run("desktop.capabilities", {})
    run("desktop.system_info", {})
    run("desktop.clipboard_write", {"text": "weak-agent"})
    run("desktop.clipboard_read", {})
    run("desktop.open_path", {"path": "."})

    run("imap.list_unread", {"limit": 2})
    search_row = run("imap.search", {"query": "test", "limit": 2})
    if not search_row.get("ok"):
        import time

        time.sleep(2)
        search_row = run("imap.search", {"query": "test", "limit": 2})
    uids = ((search_row.get("detail") or {}).get("data") or {}).get("uids") or []
    if uids:
        run("imap.fetch_message", {"uid": int(uids[0])})

    run("onec.odata_get", {"entity": "Document_ТД_ВходящаяКорреспонденция", "top": 1})
    run("onec.sql_query", {"sql": "SELECT 1 AS x"})

    run("onec.com.status", {})
    qt = run("onec.com.query_tasks", {"limit": 3})
    if qt.get("ok"):
        oc = run("onec.com.connect", {})
        state["onec_sid"] = str(data(oc).get("session_id") or "")
        if state["onec_sid"]:
            run(
                "onec.com.invoke",
                {"session_id": state["onec_sid"], "method": "String", "args": ["probe"]},
            )
            run("onec.com.release", {"session_id": state["onec_sid"]})

    run("browser.open_session", {})
    run("browser.navigate", {"url": PROBE_URL})
    snap = run("browser.snapshot", {})
    refs = data(snap).get("elements") or []
    ref = refs[0]["ref"] if refs else "e1"
    run("browser.click", {"ref": ref})
    run("browser.type", {"selector": "body", "text": "x"})
    run("browser.extract_text", {"url": PROBE_URL, "fetch_first": False, "use_session": True})
    run("browser.screenshot", {"url": PROBE_URL})
    run("browser.tabs", {"action": "list"})
    run("browser.close_session", {})

    run("com.list_apps", {})
    ol = run("com.outlook.launch", {"visible": False})
    state["ol_sid"] = str(data(ol).get("session_id") or "")
    cal = run("com.outlook.calendar_list", {"session_id": state["ol_sid"], "days": 3, "limit": 3})
    events = data(cal).get("events") or []
    if events and state["ol_sid"]:
        run(
            "com.outlook.calendar_get",
            {"session_id": state["ol_sid"], "entry_id": events[0].get("entry_id"), "include_body": True},
        )
    run("com.outlook.close", {"session_id": state["ol_sid"], "quit": False})

    connected = run("com.connect", {"app": "excel"})
    state["com_sid"] = str(data(connected).get("session_id") or "")
    if state["com_sid"]:
        run("com.release", {"session_id": state["com_sid"]})

    for name in names:
        if name in SKIP_TOOLS:
            results.append({"step": f"skip.{name}", "ok": True, "detail": {"reason": "write/destructive"}})

    failed = [r for r in results if not r["ok"]]
    print("=== WEAK AGENT TOOL PROBE ===")
    print(f"steps={len(results)} failed={len(failed)} run_id={run_id}")
    for row in results:
        mark = "OK " if row["ok"] else "BAD"
        detail = row["detail"]
        hint = ""
        if isinstance(detail, dict):
            hint = str(detail.get("error") or detail.get("summary") or detail.get("reason") or "")[:120]
        print(f"{mark} | {row['step']} | {hint}")

    out = Path(__file__).resolve().parents[1] / "logs" / "weak_agent_tool_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
