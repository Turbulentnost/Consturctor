#!/usr/bin/env python3
"""Probe DOK HTTP Tasks API body formats from infra/.env."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    env[key.strip()] = value.strip().strip('"').strip("'")

URL = env.get("DOK_HTTP_URL", "").strip('"')
AUTH = (env.get("DOK_HTTP_USER", ""), env.get("DOK_HTTP_PASSWORD", ""))
FIO = env.get("ERP_LOGIN", "")
TIMEOUT = float(env.get("DOK_HTTP_TIMEOUT", "30"))


def try_call(label: str, method: str, url: str, **kwargs) -> None:
    try:
        resp = httpx.request(method, url, auth=AUTH, timeout=TIMEOUT, **kwargs)
        body = resp.text[:300].replace("\n", " ")
        print(f"{label}: {resp.status_code} len={len(resp.text)} {body}")
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: FAIL {exc}")


def main() -> None:
    print("URL:", URL)
    print("User:", FIO)
    user_ref = "41290a43-5990-11f1-980e-6cb31113810e"
    urls = [URL, URL.rstrip("/") + "/User"]
    bodies = [
        ("json-user", {"Content-Type": "application/json"}, json.dumps({"user": FIO})),
        ("json-login", {"Content-Type": "application/json"}, json.dumps({"login": FIO})),
        ("json-guid", {"Content-Type": "application/json"}, json.dumps({"user": user_ref})),
        ("text-fio", {"Content-Type": "text/plain; charset=utf-8"}, FIO),
        ("text-guid", {"Content-Type": "text/plain; charset=utf-8"}, user_ref),
        ("form-user", {"Content-Type": "application/x-www-form-urlencoded"}, f"user={FIO}"),
        (
            "1c-xml-structure",
            {"Content-Type": "application/xml; charset=utf-8"},
            f"""<?xml version="1.0" encoding="UTF-8"?>
<Structure xmlns="http://v8.1c.ru/8.1/data/core"
 xmlns:xs="http://www.w3.org/2001/XMLSchema"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Property name="Пользователь">
    <Value xsi:type="xs:string">{FIO}</Value>
  </Property>
</Structure>""",
        ),
        (
            "1c-xml-user-node",
            {"Content-Type": "application/xml; charset=utf-8"},
            f'<?xml version="1.0"?><user>{FIO}</user>',
        ),
        (
            "1c-value-string",
            {"Content-Type": "text/plain; charset=utf-8"},
            f'{{"Пользователь":"{FIO}"}}',
        ),
    ]
    query_params = [
        {},
        {"user": FIO},
        {"User": FIO},
        {"login": FIO},
        {"UserName": FIO},
        {"user": user_ref},
        {"UserID": user_ref},
    ]
    for url in urls:
        print(f"\n=== {url} ===")
        for qp in query_params:
            label = json.dumps(qp, ensure_ascii=False) if qp else "{}"
            try_call(f"GET params={label}", "GET", url, params=qp or None)
        for name, headers, content in bodies:
            try_call(f"POST {name}", "POST", url, headers=headers, content=content.encode("utf-8"))


if __name__ == "__main__":
    main()
