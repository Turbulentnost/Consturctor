"""Quick probe: create workflow + plan/stream."""
from __future__ import annotations

import httpx

BASE = "http://127.0.0.1:7812"
DOC = r"c:\Users\mdj\Desktop\РЕГЛАМЕНТ ОПЕРАЦИОННОГО СОПРОВОЖДЕНИЯ ПОРУЧЕНИЙ ПОМОЩНИКОМ ПРЕДСЕДАТЕЛЯ СОВЕТА ДИРЕКТОРОВ.docx"


def main() -> None:
    r = httpx.post(
        f"{BASE}/api/v1/auth/login",
        json={"fio": "Жалыбин Максим Дмитриевич", "password": "x"},
        timeout=30,
    )
    print("login", r.status_code, r.text[:200])
    token = r.json().get("access_token", "")
    headers = {"Authorization": f"Bearer {token}"}

    r = httpx.get(f"{BASE}/api/v1/workflows/health", headers=headers, timeout=30)
    print("wf health", r.status_code, r.text)

    from pathlib import Path

    files = []
    if Path(DOC).is_file():
        files = [("files", (Path(DOC).name, Path(DOC).open("rb"), "application/octet-stream"))]
    r = httpx.post(
        f"{BASE}/api/v1/workflows",
        headers=headers,
        data={"notes": ""},
        files=files,
        timeout=120,
    )
    print("create", r.status_code, r.text[:400])
    if r.status_code >= 400:
        return
    wf_id = r.json()["id"]
    print("wf_id", wf_id)

    print("plan stream start")
    with httpx.Client(timeout=60.0) as client:
        with client.stream(
            "POST",
            f"{BASE}/api/v1/workflows/{wf_id}/plan/stream",
            headers={**headers, "Accept": "text/event-stream"},
        ) as resp:
            print("stream status", resp.status_code)
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    print(line[:800])
                    if '"type": "error"' in line or '"type": "workflow"' in line:
                        break


if __name__ == "__main__":
    main()
