#!/usr/bin/env python3
"""End-to-end: regulation → draft → ready agent + tool smoke tests."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:7812"
DOC = Path(
    r"c:\Users\mdj\Desktop\РЕГЛАМЕНТ ОПЕРАЦИОННОГО СОПРОВОЖДЕНИЯ ПОРУЧЕНИЙ "
    r"ПОМОЩНИКОМ ПРЕДСЕДАТЕЛЯ СОВЕТА ДИРЕКТОРОВ.docx"
)
FIO = "Жалыбин Максим Дмитриевич"
PASSWORD = "dev123"
POSITION = "помощник председателя совета директоров"
DEPARTMENT = "ПСД"
LOG = Path(__file__).resolve().parents[1] / "logs" / "psd_chairman_agent_build.json"

TOOL_SMOKE = (
    ("onec.com.status", {}),
    ("onec.com.query_tasks", {"limit": 3}),
    ("fs.write", {"path": "_psd_agent_probe.txt", "contents": "psd-agent-probe\n"}),
    ("fs.read", {"path": "_psd_agent_probe.txt"}),
    ("fs.stat", {"path": "_psd_agent_probe.txt"}),
)


def main() -> int:
    if not DOC.is_file():
        print("DOC not found:", DOC)
        return 1
    report: dict = {"steps": [], "errors": []}

    with httpx.Client(base_url=BASE, timeout=300.0) as client:
        health = client.get("/health").json()
        report["health"] = health
        print("health", health.get("status"), "dev_mode", health.get("dev_mode"))

        login = client.post(
            "/api/v1/auth/login",
            json={"fio": FIO, "password": PASSWORD},
        )
        if login.status_code != 200:
            report["errors"].append(f"login {login.status_code}: {login.text[:300]}")
            _save(report)
            return 1
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        report["user"] = login.json().get("user")
        _step(report, "login", "ok")

        with DOC.open("rb") as fh:
            up = client.post(
                "/api/v1/regulations/upload",
                headers=headers,
                files={
                    "file": (
                        DOC.name,
                        fh,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
        if up.status_code != 200:
            report["errors"].append(f"upload {up.status_code}: {up.text[:500]}")
            _save(report)
            return 1
        reg = up.json()
        rid = reg["regulationId"]
        report["regulationId"] = rid
        report["fragments"] = len(reg.get("fragments") or [])
        _step(report, "upload", f"{rid} fragments={report['fragments']}")

        compat = client.post(
            f"/api/v1/regulations/{rid}/role-compatibility",
            headers=headers,
            json={"position": POSITION, "department": DEPARTMENT},
        ).json()
        report["compatibility"] = compat
        _step(report, "compatibility", str(compat.get("compatible")))

        extract = client.post(
            f"/api/v1/regulations/{rid}/function-extraction",
            headers=headers,
            json={"position": POSITION, "department": DEPARTMENT},
        )
        if extract.status_code != 200:
            report["errors"].append(f"extract {extract.status_code}: {extract.text[:800]}")
            _save(report)
            return 1
        role = extract.json()
        run_id = role["runId"]
        funcs = role.get("functions") or []
        matches = role.get("matches") or []
        report["roleMatchRunId"] = run_id
        report["functionsCount"] = len(funcs)
        report["matchesCount"] = len(matches)
        _step(report, "function-extraction", f"funcs={len(funcs)} run={run_id}")
        if not funcs and not matches:
            report["errors"].append("no functions extracted")
            _save(report)
            return 2

        draft = client.post(
            f"/api/v1/regulations/{rid}/role-matches/{run_id}/draft",
            headers=headers,
        )
        if draft.status_code != 200:
            report["errors"].append(f"draft {draft.status_code}: {draft.text[:500]}")
            _save(report)
            return 1
        draft_body = draft.json()
        draft_id = draft_body["draftId"]
        report["draftId"] = draft_id
        _step(report, "create-draft", draft_id)

        ready_draft = client.post(
            f"/api/v1/agents/drafts/{draft_id}/readiness",
            headers=headers,
        )
        if ready_draft.status_code != 200:
            report["errors"].append(f"readiness {ready_draft.status_code}: {ready_draft.text[:500]}")
            _save(report)
            return 1
        draft_detail = ready_draft.json()
        readiness = draft_detail.get("readiness") or {}
        readiness_run_id = readiness.get("readinessRunId") or draft_detail.get("readinessRunId") or ""
        report["readinessRunId"] = readiness_run_id
        _step(report, "readiness-run", readiness_run_id)

        questions = readiness.get("questions") or []
        for question in questions:
            if question.get("answered"):
                continue
            qid = question.get("questionId") or question.get("id") or ""
            quick = (question.get("quickAnswers") or ["по регламенту Action Tracker / 1С ERP"])[0]
            ans = client.post(
                f"/api/v1/regulations/{rid}/readiness/{readiness_run_id}/answers",
                headers=headers,
                json={"questionId": qid, "answer": quick},
            )
            if ans.status_code != 200:
                report["errors"].append(f"answer {qid}: {ans.status_code} {ans.text[:200]}")
            readiness = ans.json()
        report["readinessAfterAnswers"] = {
            "status": readiness.get("status"),
            "score": readiness.get("score"),
            "answered": sum(1 for q in readiness.get("questions") or [] if q.get("answered")),
            "total": len(readiness.get("questions") or []),
        }
        _step(report, "readiness-answers", report["readinessAfterAnswers"])

        status = client.patch(
            f"/api/v1/agents/drafts/{draft_id}/status",
            headers=headers,
            json={"status": "ready"},
        )
        if status.status_code != 200:
            report["errors"].append(f"status {status.status_code}: {status.text[:300]}")
        else:
            draft_detail = status.json()
            suggestions = draft_detail.get("agentSuggestions") or []
            report["agentSuggestions"] = suggestions
            _step(report, "status-ready", f"suggestions={len(suggestions)}")

        if not (draft_detail.get("agentSuggestions") or []):
            func_id = (funcs[0] if funcs else {}).get("functionId") or ""
            if func_id:
                passport = client.post(
                    "/api/v1/regulations/passport/draft-from-suggestion",
                    headers=headers,
                    json={
                        "regulationId": rid,
                        "roleMatchRunId": run_id,
                        "functionId": func_id,
                        "agentTitle": "ИИ-агент: сопровождение поручений ПСД",
                        "draftId": draft_id,
                    },
                )
                report["passport"] = {
                    "status": passport.status_code,
                    "source": (passport.json().get("passport") or {}).get("source") if passport.status_code == 200 else passport.text[:300],
                }
                _step(report, "passport", str(report["passport"]))

        tools = client.get(f"/api/v1/agents/drafts/{draft_id}/tools", headers=headers)
        if tools.status_code == 200:
            items = tools.json().get("items") or []
            report["draftToolsCount"] = len(items)
            report["draftToolsSample"] = [t.get("name") for t in items[:15]]
            _step(report, "draft-tools", len(items))

        run_id_tools = f"probe-{uuid.uuid4().hex[:12]}"
        tool_results = []
        for name, payload in TOOL_SMOKE:
            inv = client.post(
                f"/api/v1/tools/{name}/invoke",
                headers=headers,
                json={"run_id": run_id_tools, "payload": payload},
                timeout=180.0,
            )
            body = inv.json() if inv.headers.get("content-type", "").startswith("application/json") else {"raw": inv.text[:200]}
            ok = inv.status_code == 200 and isinstance(body, dict) and body.get("ok") is True
            tool_results.append({"tool": name, "http": inv.status_code, "ok": ok, "error": body.get("error") if isinstance(body, dict) else None})
        report["toolSmoke"] = tool_results
        _step(report, "tool-smoke", f"ok={sum(1 for t in tool_results if t['ok'])}/{len(tool_results)}")

        listing = client.get("/api/v1/agents/drafts", headers=headers).json()
        found = any(item.get("draftId") == draft_id for item in listing.get("items") or [])
        report["draftListed"] = found
        report["draftsTotal"] = len(listing.get("items") or [])
        _step(report, "draft-list", f"found={found} total={report['draftsTotal']}")

    _save(report)
    print("draftId", report.get("draftId"))
    print("suggestions", len(report.get("agentSuggestions") or []))
    print("tool smoke ok", sum(1 for t in report.get("toolSmoke") or [] if t.get("ok")))
    print("saved", LOG)
    return 0 if report.get("draftListed") and not report.get("errors") else 3


def _step(report: dict, name: str, detail: str) -> None:
    report["steps"].append({"step": name, "detail": str(detail)})
    print(f"[{name}] {detail}")


def _save(report: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
