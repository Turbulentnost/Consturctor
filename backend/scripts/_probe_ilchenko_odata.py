from __future__ import annotations

import uuid

import httpx

from app.config import settings

user_hex = "A2DCC949FEDEC70D40318ABA83C618F4"
guid = str(uuid.UUID(bytes_le=bytes.fromhex(user_hex)))
base = settings.odata_base_url.rstrip("/")
auth = (settings.odata_username, settings.odata_password)
cat = "Catalog_Пользователи"
fio = "Ильченко Екатерина Александровна"

for filt in (
    f"Description eq '{fio.replace(chr(39), chr(39)+chr(39))}'",
    f"Ref_Key eq guid'{guid}'",
):
    r = httpx.get(
        f"{base}/{cat}",
        auth=auth,
        timeout=90,
        params={"$top": 3, "$filter": filt, "$format": "json"},
    )
    print("filter", filt[:80])
    print("status", r.status_code, r.text[:200])
    if r.status_code == 200:
        for row in r.json().get("value") or []:
            for k, v in sorted(row.items()):
                if v in (None, "", False, 0):
                    continue
                if isinstance(v, str) and len(v) > 200:
                    continue
                if "@" in str(v) or k.lower() in ("code", "description", "ref_key"):
                    print(" ", k, v)
