"""Quick probe: filter tasks by executor via OData."""
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
AUTH = (env["ODATA_USERNAME"], env["ODATA_PASSWORD"])
FIO = env.get("ERP_LOGIN", "")
ENTITY = "Task_ЗадачаИсполнителя"


def get(params: dict) -> httpx.Response:
    return httpx.get(f"{BASE}/{ENTITY}", params=params, auth=AUTH, timeout=60.0)


def msg(r: httpx.Response) -> str:
    if r.status_code == 200:
        return f"rows={len(r.json().get('value', []))}"
    return r.text[:180].replace("\n", " ")


print("FIO:", FIO)
# sample row to get executor field names
r0 = get({"$format": "json", "$top": "1"})
if r0.status_code == 200 and r0.json().get("value"):
    row = r0.json()["value"][0]
    exec_ref = row.get("Исполнитель")
    print("sample executor:", exec_ref)
    print("fields:", [k for k in row if "Исп" in k or "Executed" in k or "Принят" in k])

filters = [
    "Executed eq false",
    "ПринятаКИсполнению eq true",
    "Executed eq false and ПринятаКИсполнению eq true",
]
if r0.status_code == 200 and r0.json().get("value"):
    ref = r0.json()["value"][0].get("Исполнитель")
    filters.extend([
        f"Исполнитель eq guid'{ref}'",
        f"Executed eq false and Исполнитель eq guid'{ref}'",
    ])

print("\n=== FILTERS ===")
for flt in filters:
    r = get({"$format": "json", "$top": "5", "$filter": flt})
    print(flt[:70], "->", r.status_code, msg(r))

# user auth vs service - same first row?
USER = (env.get("ERP_LOGIN", ""), env.get("ERP_PASSWORD", ""))
if USER[0]:
    rs = get({"$format": "json", "$top": "3", "$filter": "Executed eq false"})
    ru = httpx.get(
        f"{BASE}/{ENTITY}",
        params={"$format": "json", "$top": "3", "$filter": "Executed eq false"},
        auth=USER,
        timeout=60,
    )
    svc_nums = [x.get("Number") for x in (rs.json().get("value") or [])]
    usr_nums = [x.get("Number") for x in (ru.json().get("value") or [])]
    print("\nRLS same list?", svc_nums == usr_nums, "service", svc_nums, "user", usr_nums)

if r0.status_code == 200 and r0.json().get("value"):
    ref = r0.json()["value"][0].get("Исполнитель")
    print("\n=== COMBINED FILTER EFFECT ===")
    for label, flt in [
        ("open only", "Executed eq false"),
        ("open+executor", f"Executed eq false and Исполнитель eq guid'{ref}'"),
    ]:
        r = get({"$format": "json", "$top": "20", "$filter": flt})
        rows = r.json().get("value", []) if r.status_code == 200 else []
        execs = {str(x.get("Исполнитель")) for x in rows}
        print(label, r.status_code, "rows", len(rows), "executors", len(execs))
        for t in rows[:3]:
            print(" ", t.get("Number"), str(t.get("Исполнитель"))[:12], (t.get("Description") or "")[:40])
