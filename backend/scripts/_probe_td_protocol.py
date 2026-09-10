#!/usr/bin/env python3
"""One-off probe: Document_ТД_Протокол OData fields and sample rows."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

ENTITY = "Document_ТД_Протокол"


def main() -> int:
    base = (os.environ.get("ODATA_BASE_URL") or "").strip().rstrip("/")
    user = (os.environ.get("ODATA_USERNAME") or os.environ.get("ERP_LOGIN") or "").strip()
    password = (os.environ.get("ODATA_PASSWORD") or os.environ.get("ERP_PASSWORD") or "").strip()
    if not base or not user:
        print("ODATA not configured", file=sys.stderr)
        return 1
    auth = (user, password)
    with httpx.Client(auth=auth, timeout=60.0, verify=False) as client:
        meta = client.get(f"{base}/$metadata", headers={"Accept": "application/xml"})
        print("metadata_status", meta.status_code)
        props: list[str] = []
        if meta.status_code == 200:
            match = re.search(
                r'EntityType Name="Document_ТД_Протокол"[^>]*>(.*?)</EntityType>',
                meta.text,
                re.S,
            )
            if match:
                props = re.findall(r'Property Name="([^"]+)"', match.group(1))
                print("property_count", len(props))
                for name in props:
                    print("prop", name)
        select = ",".join(
            p
            for p in (
                "Ref_Key",
                "Number",
                "Date",
                "Posted",
                "DeletionMark",
                "ТемаСовещания",
                "ТемаСлужебнойЗаписки",
                "Ответственный_Key",
                "Подразделение_Key",
                "ВидСовещания",
                "ОрганизацияСовещания",
                "МестоПроведенияСовещания",
                "ДатаПроведенияСовещания",
                "Комментарий",
                "Инициатор",
                "РуководительСовещания_Key",
            )
            if not props or p in props
        )
        query = (
            f"{ENTITY}?$top=5&$orderby=Date desc&$select={select}&$format=json"
        )
        sample = client.get(f"{base}/{query}")
        print("sample_status", sample.status_code)
        out = ROOT / "scripts" / "_probe_td_protocol_result.json"
        payload: dict[str, object] = {"properties": props, "samples": [], "filters": {}}
        if sample.status_code == 200:
            rows = sample.json().get("value") or []
            print("sample_count", len(rows))
            payload["samples"] = rows[:5]
        else:
            payload["sample_error"] = sample.text[:2000]
        full = client.get(
            f"{base}/{ENTITY}?$top=1&$orderby=Date desc&$format=json"
        )
        if full.status_code == 200:
            vals = full.json().get("value") or []
            if vals:
                payload["full_row_keys"] = sorted(vals[0].keys())
                payload["full_row"] = vals[0]
        # RK / SD themed filter probes
        for needle in ("ревизион", "совет директоров", "РК", "СД"):
            filt = (
                f"{ENTITY}?$top=3&$filter=contains(tolower(ТемаСовещания),'{needle.lower()}')"
                f"&$orderby=Date desc&$select=Number,Date,ТемаСовещания&$format=json"
            )
            resp = client.get(f"{base}/{filt}")
            print("filter", needle, resp.status_code, end=" ")
            if resp.status_code == 200:
                vals = resp.json().get("value") or []
                print("hits", len(vals))
                payload["filters"][needle] = vals
            else:
                print("err")
                payload["filters"][needle] = {"error": resp.text[:500]}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
