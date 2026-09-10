#!/usr/bin/env python3
"""Probe meeting themes and protocol number patterns for RK/SD."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
ENTITY = "Document_ТД_Протокол"
THEME_ENTITY = "Catalog_ТД_ТемыСовещаний"


def _client() -> tuple[httpx.Client, str]:
    base = (os.environ.get("ODATA_BASE_URL") or "").strip().rstrip("/")
    user = (os.environ.get("ODATA_USERNAME") or os.environ.get("ERP_LOGIN") or "").strip()
    password = (os.environ.get("ODATA_PASSWORD") or os.environ.get("ERP_PASSWORD") or "").strip()
    if not base or not user:
        raise SystemExit("ODATA not configured")
    return httpx.Client(auth=(user, password), timeout=90.0, verify=False), base


def main() -> None:
    client, base = _client()
    out: dict[str, object] = {}
    with client:
        themes = client.get(
            f"{base}/{THEME_ENTITY}?$top=500&$select=Ref_Key,Description,Code,DeletionMark&$format=json"
        )
        if themes.status_code == 200:
            rows = themes.json().get("value") or []
            hits = [
                row
                for row in rows
                if any(
                    tip in str(row.get("Description") or "").casefold()
                    for tip in (
                        "ревизион",
                        "совет директоров",
                        "сд ",
                        " рк",
                        "псд",
                        "совета директоров",
                    )
                )
            ]
            out["theme_hits"] = hits[:40]
        protos = client.get(
            f"{base}/{ENTITY}?$top=200&$orderby=Date desc&$select=Ref_Key,Number,Date,Posted,DeletionMark,ТемаСовещания_Key,Статус,ВидСовещания&$format=json"
        )
        rows = protos.json().get("value") or [] if protos.status_code == 200 else []
        prefixes = Counter(str(r.get("Number") or "").split("_")[0] for r in rows)
        out["number_prefixes"] = dict(prefixes.most_common(30))
        rk_sd = [
            r
            for r in rows
            if re.search(r"(?i)(^РК|РК_|СД_|СПГ_|СДГ|совет|ревизион)", str(r.get("Number") or ""))
        ]
        out["rk_sd_by_number"] = rk_sd[:30]
        # expand a few themes
        expanded: list[dict[str, object]] = []
        for row in rows[:80]:
            key = str(row.get("ТемаСовещания_Key") or "")
            if not key or key == "00000000-0000-0000-0000-000000000000":
                continue
            detail = client.get(
                f"{base}/{ENTITY}(guid'{row['Ref_Key']}')?$select=Number,Date,Posted,ТемаСовещания/Description&$expand=ТемаСовещания&$format=json"
            )
            if detail.status_code != 200:
                continue
            data = detail.json()
            topic = ""
            theme = data.get("ТемаСовещания")
            if isinstance(theme, dict):
                topic = str(theme.get("Description") or "")
            blob = f"{row.get('Number')} {topic}".casefold()
            if any(t in blob for t in ("ревизион", "совет директоров", "сд ", " рк", "псд")):
                expanded.append(
                    {
                        "Number": data.get("Number") or row.get("Number"),
                        "Date": data.get("Date") or row.get("Date"),
                        "Posted": data.get("Posted"),
                        "Topic": topic,
                        "Ref_Key": row.get("Ref_Key"),
                    }
                )
            if len(expanded) >= 25:
                break
        out["rk_sd_by_topic"] = expanded
        # startswith filters supported?
        for prefix in ("РК", "СД", "СПГ", "ОД", "ПСД"):
            filt = (
                f"{ENTITY}?$top=5&$filter=startswith(Number,'{prefix}')"
                f"&$orderby=Date desc&$select=Number,Date,Posted,ТемаСовещания_Key&$format=json"
            )
            resp = client.get(f"{base}/{filt}")
            out[f"startswith_{prefix}"] = {
                "status": resp.status_code,
                "value": (resp.json().get("value") or [])[:5] if resp.status_code == 200 else resp.text[:300],
            }
    path = ROOT / "scripts" / "_probe_td_protocol_topics.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    main()
