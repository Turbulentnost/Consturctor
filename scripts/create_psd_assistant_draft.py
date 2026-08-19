#!/usr/bin/env python3
"""Upload PSD assistant regulation and create an agent draft on local NewConstructor."""

from __future__ import annotations

import json
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
LOG = Path(__file__).resolve().parents[1] / "logs" / "psd_assistant_draft.json"


def main() -> int:
    if not DOC.is_file():
        print("DOC not found:", DOC)
        return 1
    report: dict = {"steps": [], "errors": []}

    with httpx.Client(base_url=BASE, timeout=600.0) as client:
        health = client.get("/health").json()
        report["health"] = {k: health.get(k) for k in ("status", "dev_mode", "auth_stub", "llm_provider")}
        print("health", report["health"])

        login = client.post("/api/v1/auth/login", json={"fio": FIO, "password": PASSWORD})
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
        )
        if compat.status_code != 200:
            report["errors"].append(f"compat {compat.status_code}: {compat.text[:400]}")
            _save(report)
            return 1
        compat_body = compat.json()
        report["compatibility"] = {
            "compatible": compat_body.get("compatible"),
            "hint": compat_body.get("hint"),
            "matchedTerms": compat_body.get("matchedTerms"),
        }
        _step(report, "compatibility", str(compat_body.get("compatible")))

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
        report["roleMatchRunId"] = run_id
        report["functionsCount"] = len(funcs)
        report["functions"] = [
            {
                "functionId": f.get("functionId"),
                "title": f.get("title") or f.get("action"),
                "action": f.get("action"),
                "object": f.get("object"),
            }
            for f in funcs
        ]
        _step(report, "function-extraction", f"funcs={len(funcs)} run={run_id}")
        if not funcs:
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
        report["draftStatus"] = draft_body.get("status")
        report["draftTitle"] = draft_body.get("title")
        _step(report, "create-draft", f"{draft_id} status={draft_body.get('status')}")

        ready_draft = client.post(
            f"/api/v1/agents/drafts/{draft_id}/readiness",
            headers=headers,
        )
        if ready_draft.status_code != 200:
            report["errors"].append(f"readiness {ready_draft.status_code}: {ready_draft.text[:500]}")
            _save(report)
            return 1
        detail = ready_draft.json()
        readiness = detail.get("readiness") or {}
        report["readinessRunId"] = readiness.get("readinessRunId") or detail.get("readinessRunId")
        report["readiness"] = {
            "status": readiness.get("status"),
            "score": readiness.get("score"),
            "questions": len(readiness.get("questions") or []),
            "unanswered": sum(1 for q in readiness.get("questions") or [] if not q.get("answered")),
        }
        report["draftStatusAfterReadiness"] = detail.get("status")
        _step(report, "readiness", str(report["readiness"]))

        listing = client.get("/api/v1/agents/drafts", headers=headers).json()
        items = listing.get("items") or []
        found = any(item.get("draftId") == draft_id for item in items)
        report["draftListed"] = found
        report["draftsTotal"] = len(items)
        report["drafts"] = [
            {"draftId": i.get("draftId"), "status": i.get("status"), "title": i.get("title")}
            for i in items
        ]
        _step(report, "draft-list", f"found={found} total={len(items)}")

    _save(report)
    print("draftId", report.get("draftId"))
    print("saved", LOG)
    return 0 if report.get("draftListed") and not report.get("errors") else 3


def _step(report: dict, name: str, detail: str) -> None:
    report["steps"].append({"step": name, "detail": str(detail)})
    print(f"[{name}] {detail}", flush=True)


def _save(report: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
