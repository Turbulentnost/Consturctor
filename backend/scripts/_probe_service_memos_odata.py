# -*- coding: utf-8 -*-
"""One-off: pull ERP service memos via OData (URL query, same as onec_tools)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402
from app.config import settings  # noqa: E402

ENTITY = "Document_ТД_СлужебнаяЗаписка"
THEME_MEETING = "cad8df76-73cc-11ea-8341-ac1f6b05524d"
OUT = BACKEND / "scripts" / "_probe_service_memos_odata.out.json"


def _brief(row: dict) -> dict:
    who = row.get("Ответственный")
    return {
        "number": row.get("Number"),
        "date": str(row.get("Date") or "")[:19],
        "status": row.get("Статус"),
        "posted": row.get("Posted"),
        "direction": row.get("Направление"),
        "topic": row.get("ТемаСовещания") or row.get("ТемаСлужебнойЗаписки"),
        "from": who.get("Description") if isinstance(who, dict) else None,
        "text": str(row.get("ТекстСлужебнойЗаписки") or "")[:180],
    }


def main() -> int:
    base = (settings.odata_base_url or "").strip().rstrip("/")
    user = (settings.odata_username or "").strip()
    password = settings.odata_password or ""
    print("base_set:", bool(base), "user_set:", bool(user))
    if not base or not user or not password:
        print("ODATA credentials missing")
        return 2

    date_filter = quote(
        "DeletionMark eq false and Date ge datetime'2026-09-01T00:00:00'",
        safe="=,'():",
    )
    theme_filter = quote(
        f"DeletionMark eq false and ТемаСлужебнойЗаписки eq cast(guid'{THEME_MEETING}', 'Edm.String')",
        safe="=,'():",
    )
    theme_guid_filter = quote(
        f"DeletionMark eq false and ТемаСлужебнойЗаписки eq guid'{THEME_MEETING}'",
        safe="=,'():",
    )
    number_filter = quote("Number eq '000016146'", safe="=,'():")
    select = quote(
        "Ref_Key,Number,Date,Posted,Статус,ТемаСлужебнойЗаписки,ТемаСовещания,Направление,ТекстСлужебнойЗаписки",
        safe=",",
    )
    expand = "Ответственный"

    paths = {
        "from_2026_sep": (
            f"{ENTITY}?$format=json&$top=20&$orderby=Date desc"
            f"&$filter={date_filter}&$select={select}&$expand={expand}"
        ),
        "number_16146": (
            f"{ENTITY}?$format=json&$top=5&$filter={number_filter}"
            f"&$select={select}&$expand={expand}"
        ),
        "theme_guid": (
            f"{ENTITY}?$format=json&$top=10&$orderby=Date desc"
            f"&$filter={theme_guid_filter}&$select={select}"
        ),
        "theme_cast": (
            f"{ENTITY}?$format=json&$top=5&$filter={theme_filter}&$select={select}"
        ),
    }

    report: dict = {}
    with httpx.Client(timeout=90, auth=(user, password)) as client:
        for name, path in paths.items():
            url = f"{base}/{path}"
            print("===", name)
            response = client.get(url, headers={"Accept": "application/json"})
            print("status", response.status_code)
            if response.status_code != 200:
                print(response.text[:500])
                report[name] = {"status": response.status_code, "text": response.text[:500]}
                continue
            payload = response.json()
            rows = [row for row in (payload.get("value") or []) if isinstance(row, dict)]
            print("count", len(rows))
            brief = [_brief(row) for row in rows]
            report[name] = {"status": 200, "count": len(rows), "rows": brief}
            for i, item in enumerate(brief[:12], 1):
                print(
                    f"{i}. {item['number']} {item['date']} {item['status']} "
                    f"| {item['from']} | {item['topic']}"
                )

    theme_ids = sorted(
        {
            str(item.get("topic") or "")
            for block in report.values()
            if isinstance(block, dict)
            for item in block.get("rows") or []
            if isinstance(item.get("topic"), str)
            and len(item["topic"]) == 36
            and item["topic"].count("-") == 4
        }
    )
    themes = {}
    with httpx.Client(timeout=45, auth=(user, password)) as client:
        for theme_id in theme_ids:
            url = f"{base}/Catalog_ТД_ТемыСлужебныхЗаписок(guid'{theme_id}')?$format=json&$select=Description"
            response = client.get(url, headers={"Accept": "application/json"})
            if response.status_code == 200:
                themes[theme_id] = (response.json() or {}).get("Description")
            else:
                themes[theme_id] = f"catalog {response.status_code}"
    print("=== themes")
    for theme_id, name in themes.items():
        print(theme_id, "->", name)

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
