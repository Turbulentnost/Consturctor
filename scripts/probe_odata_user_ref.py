#!/usr/bin/env python3
"""Find correct user ref for OData Task_ЗадачаИсполнителя.Исполнитель."""

from __future__ import annotations

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
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip().strip('"').strip("'")

BASE = env["ODATA_BASE_URL"].rstrip("/")
USER = (env["ERP_LOGIN"], env["ERP_PASSWORD"])
FIO = env["ERP_LOGIN"]


def scan_catalog(name: str) -> None:
    print(f"\n=== {name} ===")
    offset = 0
    while offset < 8000:
        r = httpx.get(
            f"{BASE}/{name}",
            params={"$format": "json", "$top": "500", "$skip": str(offset)},
            auth=USER,
            timeout=60,
        )
        if r.status_code != 200:
            print("HTTP", r.status_code, r.text[:120])
            return
        rows = r.json().get("value") or []
        if not rows:
            break
        for row in rows:
            desc = (row.get("Description") or row.get("Наименование") or "").strip()
            if desc == FIO or ("Жалыбин" in desc and "Максим" in desc):
                print("MATCH:", desc, "Ref_Key=", row.get("Ref_Key"))
                return
        offset += len(rows)
    print("not found in", offset, "rows")


def sample_tasks() -> None:
    print("\n=== Task sample keys ===")
    r = httpx.get(
        f"{BASE}/Task_ЗадачаИсполнителя",
        params={"$format": "json", "$top": "3", "$orderby": "Date desc"},
        auth=USER,
        timeout=60,
    )
    print("status", r.status_code)
    rows = r.json().get("value") or []
    for row in rows:
        isp_keys = {k: row[k] for k in row if "сполн" in k.lower() or "Executor" in k or "User" in k or "Author" in k}
        print("Number", row.get("Number"), "Executed", row.get("Executed"))
        print("  executor-related:", isp_keys)
        print("  Description", (row.get("Description") or "")[:60])

    # collect unique executor refs from open tasks
    refs: dict[str, int] = {}
    for skip in range(0, 500, 100):
        rr = httpx.get(
            f"{BASE}/Task_ЗадачаИсполнителя",
            params={
                "$format": "json",
                "$top": "100",
                "$skip": str(skip),
                "$filter": "Executed eq false",
            },
            auth=USER,
            timeout=60,
        )
        if rr.status_code != 200:
            break
        batch = rr.json().get("value") or []
        if not batch:
            break
        for row in batch:
            ref = str(row.get("Исполнитель") or row.get("Исполнитель_Key") or "")
            if ref:
                refs[ref] = refs.get(ref, 0) + 1
    print("\nunique executor refs in first 500 open tasks:", len(refs))
    user_ref = "41290a43-5990-11f1-980e-6cb31113810e"
    print("Catalog_Пользователи ref count:", refs.get(user_ref, 0))


def main() -> None:
    for cat in (
        "Catalog_Пользователи",
        "Catalog_ФизическиеЛица",
        "Catalog_Сотрудники",
        "Catalog_Партнеры",
    ):
        scan_catalog(cat)
    sample_tasks()


if __name__ == "__main__":
    main()
