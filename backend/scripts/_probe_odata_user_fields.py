from __future__ import annotations

import httpx

from app.config import settings

base = settings.odata_base_url.rstrip("/")
auth = (settings.odata_username, settings.odata_password)
cat = "Catalog_Пользователи"
filt = (
    "startswith(Description,'Ильченко') and substringof('Екатерина',Description)"
)
r = httpx.get(
    f"{base}/{cat}",
    auth=auth,
    timeout=90,
    params={"$top": 1, "$filter": filt, "$format": "json"},
)
print("status", r.status_code)
row = (r.json().get("value") or [{}])[0]
for k in sorted(row.keys()):
    v = row[k]
    if v not in (None, "", False, 0):
        print(k, repr(v)[:160])
