from __future__ import annotations

import json
from base64 import b64encode
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

env: dict[str, str] = {}
for line in Path(__file__).with_name(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("//") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip()

BASE = env["ODATA_BASE_URL"].rstrip("/")
AUTH = b64encode(f"{env['ODATA_USERNAME']}:{env['ODATA_PASSWORD']}".encode()).decode()
SAFE = "/()'=,:$"
OUT = Path(__file__).with_name("_tmp_kpi_ship_share.json")

COMMERCIAL = {
    "49480c10-e401-11e8-8283-ac1f6b05524d": "ВЭД",
    "34497ef7-810f-11e4-80d6-001e67112509": "Эталон",
    "9edaa7d4-37a5-11ee-93d3-6cb31113810e": "БМИ",
    "639ec87b-67b6-11eb-8523-ac1f6b05524d": "Ключевые",
    "7587c178-92f6-11f0-96f9-6cb31113810e": "ОДП",
    "bd7b5184-9f9c-11e4-80da-001e67112509": "Газпром",
}
FOCUS = {"БМИ", "Газпром"}


def odata(path: str) -> dict:
    if "?" in path:
        entity, query = path.split("?", 1)
        url = f"{BASE}/{quote(entity, safe='')}?{query}"
    else:
        url = f"{BASE}/{quote(path, safe='')}"
    req = Request(url, headers={"Authorization": f"Basic {AUTH}", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"{exc.code} {path[:180]} {body}") from exc


def fetch_all(entity: str, odata_filter: str, select: str = "", top: int = 200) -> list[dict]:
    rows: list[dict] = []
    skip = 0
    while True:
        parts = [f"$format=json", f"$top={top}", f"$skip={skip}"]
        if odata_filter:
            parts.append(f"$filter={quote(odata_filter, safe=SAFE)}")
        if select:
            parts.append(f"$select={quote(select, safe=SAFE)}")
        batch = odata(f"{entity}?{'&'.join(parts)}").get("value") or []
        rows.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < top:
            break
        skip += top
        if skip > 50_000:
            break
    return rows


def num(raw: object) -> float:
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_names(entity: str, keys: set[str], name_field: str = "Description") -> dict[str, str]:
    names: dict[str, str] = {}
    wanted = [key for key in sorted(keys) if key and key != "00000000-0000-0000-0000-000000000000"]
    for i in range(0, len(wanted), 15):
        batch = wanted[i : i + 15]
        filt = " or ".join(f"Ref_Key eq guid'{key}'" for key in batch)
        for row in fetch_all(entity, filt, select=f"Ref_Key,{name_field}", top=len(batch)):
            names[str(row.get("Ref_Key") or "")] = str(row.get(name_field) or "").strip()
    return names


depts = fetch_all(
    "Catalog_СтруктураПредприятия",
    "DeletionMark eq false",
    select="Ref_Key,Description",
    top=300,
)
dept_names = {str(row.get("Ref_Key") or ""): str(row.get("Description") or "").strip() for row in depts}

docs_filter = (
    "Posted eq true and DeletionMark eq false and "
    "Date ge datetime'2026-09-01T00:00:00' and Date lt datetime'2026-10-01T00:00:00'"
)
docs = fetch_all(
    "Document_РеализацияТоваровУслуг",
    docs_filter,
    select=(
        "Ref_Key,Number,Date,СуммаДокумента,СуммаВзаиморасчетов,Подразделение_Key,"
        "Партнер_Key,Контрагент_Key,Организация_Key,Валюта_Key,Комментарий,ХозяйственнаяОперация,Статус"
    ),
)

partner_names = fetch_names("Catalog_Партнеры", {str(d.get("Партнер_Key") or "") for d in docs})
org_names = fetch_names("Catalog_Организации", {str(d.get("Организация_Key") or "") for d in docs})

by_dept: dict[str, float] = defaultdict(float)
by_partner: dict[str, float] = defaultdict(float)
by_day: dict[str, float] = defaultdict(float)
focus_docs = []
all_docs = []
for doc in docs:
    amount = num(doc.get("СуммаВзаиморасчетов")) or num(doc.get("СуммаДокумента"))
    dept_key = str(doc.get("Подразделение_Key") or "")
    dept = COMMERCIAL.get(dept_key) or dept_names.get(dept_key) or dept_key[:8]
    partner = partner_names.get(str(doc.get("Партнер_Key") or ""), "") or str(doc.get("Партнер_Key") or "")[:8]
    day = str(doc.get("Date") or "")[:10]
    by_dept[dept] += amount
    by_partner[partner] += amount
    by_day[day] += amount
    rec = {
        "number": doc.get("Number"),
        "date": doc.get("Date"),
        "amount": amount,
        "dept": dept,
        "partner": partner,
        "org": org_names.get(str(doc.get("Организация_Key") or ""), ""),
        "comment": str(doc.get("Комментарий") or "")[:160],
        "op": doc.get("ХозяйственнаяОперация"),
        "status": doc.get("Статус"),
    }
    all_docs.append(rec)
    blob = f"{dept} {partner} {rec['comment']}".casefold()
    if any(token in blob for token in ("газпром", "bmi", "бми", "бмми")):
        focus_docs.append(rec)

all_docs.sort(key=lambda item: -item["amount"])
focus_docs.sort(key=lambda item: -item["amount"])

total = sum(by_dept.values())
gaz_bmi_dept = by_dept.get("БМИ", 0) + by_dept.get("Газпром", 0)
commercial_total = sum(by_dept.get(name, 0) for name in COMMERCIAL.values())
partner_focus = 0.0
for name, amount in by_partner.items():
    low = name.casefold()
    if any(token in low for token in ("газпром", "bmi", "бми", "бмми")):
        partner_focus += amount

plan_gaz_bmi = 135_000_000 + 186_042_380
plan_total = 436_108_010

result = {
    "doc_count": len(docs),
    "total": total,
    "gaz_bmi_by_dept": gaz_bmi_dept,
    "share_dept_of_all": (gaz_bmi_dept / total * 100) if total else None,
    "share_dept_of_commercial": (gaz_bmi_dept / commercial_total * 100) if commercial_total else None,
    "partner_focus": partner_focus,
    "share_partner_of_all": (partner_focus / total * 100) if total else None,
    "plan_share": plan_gaz_bmi / plan_total * 100,
    "by_dept": dict(sorted(by_dept.items(), key=lambda kv: -kv[1])),
    "by_partner": dict(sorted(by_partner.items(), key=lambda kv: -kv[1])[:30]),
    "by_day": dict(sorted(by_day.items())),
    "top_docs": all_docs[:20],
    "focus_docs": focus_docs[:30],
    "through_15": None,
}
cut = datetime(2026, 9, 16)
thru = [d for d in all_docs if str(d["date"])[:10] < "2026-09-16"]
thru_total = sum(d["amount"] for d in thru)
thru_focus = sum(d["amount"] for d in thru if d["dept"] in FOCUS)
result["through_15"] = {
    "count": len(thru),
    "total": thru_total,
    "gaz_bmi": thru_focus,
    "share": (thru_focus / thru_total * 100) if thru_total else None,
}

OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: result[k] for k in [
    "doc_count", "total", "gaz_bmi_by_dept", "share_dept_of_all",
    "share_dept_of_commercial", "partner_focus", "share_partner_of_all",
    "plan_share", "by_dept", "through_15"
]}, ensure_ascii=False, indent=2))
print("wrote", OUT)
