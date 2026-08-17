"""Probe OData: user auth + tasks by executor."""
from __future__ import annotations

import json
import re
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
SERVICE = (env.get("ODATA_USERNAME", ""), env.get("ODATA_PASSWORD", ""))
USER = (env.get("ERP_LOGIN", ""), env.get("ERP_PASSWORD", ""))
FIO = env.get("ERP_LOGIN", "")


def odata_msg(text: str) -> str:
    m = re.search(r"<m:message>(.*?)</m:message>", text)
    return m.group(1) if m else text[:200]


def get(path: str, *, auth: tuple[str, str], params: dict | None = None) -> httpx.Response:
    url = f"{BASE}/{path.lstrip('/')}"
    return httpx.get(url, params=params or {}, auth=auth, timeout=45.0)


def try_auth(label: str, auth: tuple[str, str]) -> None:
    print(f"\n=== AUTH {label} ===")
    r = get("BusinessProcess_Задание", auth=auth, params={"$format": "json", "$top": "2"})
    print("status", r.status_code, odata_msg(r.text) if r.status_code != 200 else f"rows={len(r.json().get('value', []))}")


def compare_auth_visibility() -> None:
    print("\n=== RLS: service vs user ===")
    params = {"$format": "json", "$top": "10", "$filter": "Completed eq false and Started eq true"}
    rs = get("BusinessProcess_Задание", auth=SERVICE, params=params)
    ru = get("BusinessProcess_Задание", auth=USER, params=params) if USER[0] else None
    if rs.status_code != 200:
        print("service fail", odata_msg(rs.text))
        return
    svc = rs.json().get("value", [])
    print("service open tasks", len(svc))
    if ru is not None:
        print("user status", ru.status_code, "rows", len(ru.json().get("value", [])) if ru.status_code == 200 else odata_msg(ru.text))
    execs = sorted({str(t.get("Исполнитель")) for t in svc})
    print("distinct executors in service sample", len(execs), execs[:3])


def find_user_ref(auth: tuple[str, str]) -> str | None:
    print("\n=== FIND USER Ref_Key ===")
    attempts = [
        ("startswith", f"startswith(Description, '{FIO.split()[0]}')"),
        ("contains substringof", f"substringof('{FIO.split()[0]}', Description)"),
    ]
    for label, flt in attempts:
        r = get("Catalog_Пользователи", auth=auth, params={"$format": "json", "$top": "20", "$filter": flt})
        print("Catalog filter", label, "->", r.status_code, odata_msg(r.text) if r.status_code != 200 else len(r.json().get("value", [])))
        if r.status_code == 200:
            for row in r.json().get("value", []):
                desc = (row.get("Description") or "").strip()
                if FIO in desc or desc == FIO:
                    ref = row.get("Ref_Key")
                    print("match", desc, ref)
                    return str(ref)
    return None


def sample_task_fields(auth: tuple[str, str]) -> None:
    print("\n=== TASK FIELDS ===")
    r = get("BusinessProcess_Задание", auth=auth, params={"$format": "json", "$top": "1"})
    if r.status_code != 200:
        print("fail", odata_msg(r.text))
        return
    rows = r.json().get("value", [])
    if not rows:
        print("no rows")
        return
    row = rows[0]
    for k, v in sorted(row.items()):
        if any(x in k for x in ("Исп", "User", "Author", "Автор", "Completed", "Started", "Date", "Number", "Наим")):
            print(f"  {k}: {v}")


def test_executor_filter(auth: tuple[str, str], user_ref: str | None) -> None:
    print("\n=== EXECUTOR FILTER ===")
    ref = user_ref or "c312aa56-c212-11e2-838d-001e67112509"
    flt = f"Исполнитель eq guid'{ref}' and Completed eq false"
    r = get("BusinessProcess_Задание", auth=auth, params={"$format": "json", "$top": "5", "$filter": flt})
    print("filter", flt[:70], "->", r.status_code)
    if r.status_code == 200:
        for t in r.json().get("value", []):
            print(" ", t.get("Number"), t.get("Наименование", "")[:70])
    else:
        print(odata_msg(r.text))


def filter_tasks(auth: tuple[str, str], user_ref: str | None) -> None:
    print("\n=== FILTER TASKS ===")
    filters = [
        "Completed eq false",
        "Started eq true and Completed eq false",
    ]
    if user_ref:
        filters.append(f"Исполнитель eq guid'{user_ref}' and Completed eq false")
        filters.append(f"Исполнитель eq guid'{user_ref}'")
    for flt in filters:
        r = get(
            "BusinessProcess_Задание",
            auth=auth,
            params={"$format": "json", "$top": "5", "$filter": flt},
        )
        msg = odata_msg(r.text) if r.status_code != 200 else str(len(r.json().get("value", [])))
        print(f"  filter={flt[:60]} -> {r.status_code} {msg}")


def probe_metadata() -> None:
    print("\n=== METADATA ENTITIES ===")
    r = httpx.get(f"{BASE}/$metadata", auth=SERVICE, timeout=60.0)
    print("metadata", r.status_code, "bytes", len(r.content))
    if r.status_code != 200:
        return
    text = r.text
    for pattern in (r"EntityType Name=\"(Task_[^\"]+)\"", r"EntityType Name=\"(BusinessProcess_[^\"]+)\""):
        names = sorted(set(re.findall(pattern, text)))
        for name in names[:15]:
            print(" ", name)
        if len(names) > 15:
            print("  ...", len(names), "total")


def main() -> None:
    print("BASE", BASE)
    print("FIO", FIO)
    try_auth("service", SERVICE)
    if USER[0]:
        try_auth("user", USER)
    compare_auth_visibility()
    probe_metadata()
    auth = USER if USER[0] else SERVICE
    sample_task_fields(SERVICE)
    ref = find_user_ref(SERVICE)
    test_executor_filter(SERVICE, ref)
    filter_tasks(SERVICE, ref)
    if ref:
        r = get(
            "BusinessProcess_Задание",
            auth=SERVICE,
            params={
                "$format": "json",
                "$top": "10",
                "$filter": f"Исполнитель eq guid'{ref}' and Completed eq false",
            },
        )
        if r.status_code == 200:
            print("\n=== USER OPEN TASKS (sample) ===")
            for t in r.json().get("value", [])[:10]:
                print(t.get("Number"), t.get("Date", "")[:10], t.get("Наименование", "")[:80])
    if USER[0] and USER != SERVICE:
        filter_tasks(USER, ref)


if __name__ == "__main__":
    main()
