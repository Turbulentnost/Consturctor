#!/usr/bin/env python3
"""Задачи по одному ACT-документу через OData."""
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

base = env["ODATA_BASE_URL"].rstrip("/")
auth = (env["ERP_LOGIN"], env["ERP_PASSWORD"])
NUMBER = sys.argv[1] if len(sys.argv) > 1 else "АСТ00-00069"


def resolve_user(client: httpx.Client, key: str) -> str:
    if not key or key == "00000000-0000-0000-0000-000000000000":
        return "—"
    r = client.get(f"{base}/Catalog_Пользователи(guid'{key}')?$format=json")
    if r.status_code != 200:
        return key[:8] + "…"
    ud = r.json()
    name = str(ud.get("Description") or "")
    flk = ud.get("ФизическоеЛицо_Key")
    if flk:
        fl = client.get(f"{base}/Catalog_ФизическиеЛица(guid'{flk}')?$format=json")
        if fl.status_code == 200:
            name = str(fl.json().get("Description") or name)
    return name or key[:8] + "…"


def ref_desc(val) -> str:
    if isinstance(val, dict):
        return str(val.get("Description") or "").strip()
    return ""


with httpx.Client(auth=auth, timeout=90) as client:
    num = NUMBER.replace("'", "''")
    path = (
        "Document_ТД_Поручения?$format=json&$top=1"
        f"&$filter=Number eq '{num}'"
        "&$expand=КтоДоложитОЗавершенииМероприятий,СекретарьРК"
    )
    r = client.get(f"{base}/{path}")
    if r.status_code != 200:
        print("OData error:", r.status_code, r.text[:300])
        sys.exit(1)
    rows = r.json().get("value") or []
    if not rows:
        # try latin ACT prefix
        alt = NUMBER.upper().replace("ACT", "АСТ")
        path2 = (
            "Document_ТД_Поручения?$format=json&$top=1"
            f"&$filter=Number eq '{alt.replace(chr(39), chr(39)+chr(39))}'"
            "&$expand=КтоДоложитОЗавершенииМероприятий,СекретарьРК"
        )
        r = client.get(f"{base}/{path2}")
        rows = r.json().get("value") or []
    if not rows:
        print(f"Документ {NUMBER} не найден в OData.")
        sys.exit(2)

    doc = rows[0]
    print("=" * 60)
    print("Номер:", doc.get("Number"))
    print("Дата:", str(doc.get("Date") or "")[:19].replace("T", " "))
    print("О чём:", doc.get("ОЧем") or "—")
    print("Статус:", doc.get("Статус") or "—")
    print("Срок полного устранения:", str(doc.get("СрокПолногоУстраненияНарушений") or "")[:10])
    print("Кто доложит:", ref_desc(doc.get("КтоДоложитОЗавершенииМероприятий")))
    print("Секретарь РК:", ref_desc(doc.get("СекретарьРК")))
    print("=" * 60)

    lines = doc.get("Поручения") or []
    print(f"Задач в табличной части «Поручения»: {len(lines)}\n")
    if not lines:
        print("(строк задач нет)")
        sys.exit(0)

    for i, line in enumerate(lines, 1):
        executor = resolve_user(client, str(line.get("ОтветственноеЛицо_Key") or ""))
        deadline = str(line.get("СрокИсполнения") or "")[:10]
        task = str(line.get("Мероприятие") or "").strip()
        priority = str(line.get("Приоритет") or "").strip()
        print(f"{i}. {task}")
        print(f"   Исполнитель: {executor}")
        print(f"   Срок: {deadline or '—'}")
        if priority:
            print(f"   Приоритет: {priority}")
        print()
