"""Синхронизация опубликованных агентов с общего сервера в локальный backend."""

from __future__ import annotations

import os
import sys

import httpx

AUTH = os.getenv("AUTH_URL", "http://192.168.1.157:7812").rstrip("/")
LOCAL = os.getenv("BACKEND_URL", "http://127.0.0.1:7812").rstrip("/")


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: py sync_agents_from_server.py <FIO> <password>")
        return 1
    fio, password = sys.argv[1], sys.argv[2]
    with httpx.Client(timeout=60.0) as client:
        login = client.post(
            f"{AUTH}/api/v1/auth/login",
            json={"fio": fio, "password": password},
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        items = client.get(f"{AUTH}/api/v1/workflows", headers=headers).json()
        imported = 0
        for item in items:
            if str(item.get("phase") or "") != "done":
                continue
            wid = str(item.get("id") or "")
            detail = client.get(f"{AUTH}/api/v1/workflows/{wid}", headers=headers).json()
            client.post(f"{LOCAL}/api/v1/workflows/import", headers=headers, json=detail).raise_for_status()
            imported += 1
            print("imported:", item.get("title") or wid)
    print(f"Done: {imported} agent(s) -> {LOCAL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
