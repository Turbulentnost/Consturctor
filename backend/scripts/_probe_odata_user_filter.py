from __future__ import annotations

import httpx

from app.config import settings

base = settings.odata_base_url.rstrip("/")
auth = (settings.odata_username, settings.odata_password)
cat = "Catalog_Пользователи"

for filt in (
    "startswith(Description,'Ильченко')",
    "substringof('Ильченко',Description)",
):
    r = httpx.get(
        f"{base}/{cat}",
        auth=auth,
        timeout=90,
        params={"$top": 5, "$filter": filt, "$format": "json"},
    )
    print(filt, r.status_code)
    if r.status_code == 200:
        for row in r.json().get("value") or []:
            print(" ", row.get("Description"), row.get("Code"), row.get("Ref_Key"))
    else:
        print(r.text[:250])
