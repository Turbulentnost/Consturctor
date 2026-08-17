"""Probe Action Tracker upload + PSD assistant extraction."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

DOC = Path(
    r"\\192.168.1.198\Files\1.Руководство\Амураль Игорь Борисович\2026\РЕОРГАНИЗАЦИЯ\ПСД\Выход из операционки\Ревезионная комиссия\Регламент исполнения решений\Регламент_исполнения_решений_и_поручений_Action_Tracker_Decision_Log_ООО_НПО_Турбулентность-Дон_v1.docx"
)
BASE = "http://127.0.0.1:7812"


def main() -> int:
    if not DOC.is_file():
        print("DOC missing:", DOC)
        return 1
    with httpx.Client(base_url=BASE, timeout=300.0) as client:
        health = client.get("/health").json()
        print("health dev_mode=", health.get("dev_mode"))
        login = client.post(
            "/api/v1/auth/login",
            json={"fio": "Жалыбин Максим Дмитриевич", "password": "test"},
        )
        print("login", login.status_code)
        if login.status_code != 200:
            print(login.text)
            return 1
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        with DOC.open("rb") as fh:
            up = client.post(
                "/api/v1/regulations/upload",
                headers=headers,
                files={"file": (DOC.name, fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
        print("upload", up.status_code)
        if up.status_code != 200:
            print(up.text[:500])
            return 1
        reg = up.json()
        rid = reg["regulationId"]
        print("regulation", rid, "fragments", len(reg.get("fragments") or []))
        compat = client.post(
            f"/api/v1/regulations/{rid}/role-compatibility",
            headers=headers,
            json={"position": "помощник ПСД", "department": "ПСД"},
        )
        print("compat", compat.status_code, compat.json().get("compatible"), compat.json().get("hint", "")[:120])
        extract = client.post(
            f"/api/v1/regulations/{rid}/function-extraction",
            headers=headers,
            json={"position": "помощник ПСД", "department": "ПСД"},
        )
        print("extract", extract.status_code)
        if extract.status_code != 200:
            print(extract.text[:800])
            return 1
        data = extract.json()
        funcs = data.get("functions") or []
        matches = data.get("matches") or []
        print("functions", len(funcs), "matches", len(matches))
        for fn in funcs[:5]:
            print(" -", fn.get("title") or fn.get("action"), "|", (fn.get("actor") or {}).get("text"))
        out = Path(__file__).resolve().parents[1] / "logs" / "psd_action_tracker_probe.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("saved", out)
    return 0 if funcs or matches else 2


if __name__ == "__main__":
    raise SystemExit(main())
