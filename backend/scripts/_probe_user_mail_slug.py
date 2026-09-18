from __future__ import annotations

import httpx

from app.config import settings
from app.clients.erp_sql import find_user_by_fio_relaxed

fio = "Ильченко Екатерина Александровна"
u = find_user_by_fio_relaxed(fio)
print("v8users.name", repr(u.name))
print("v8users.fio", u.fio)

base = settings.odata_base_url.rstrip("/")
auth = (settings.odata_username, settings.odata_password)
for ent in ("Catalog_Пользователи", "Catalog_ПользователиОС"):
    url = f"{base}/{ent}"
    filt = f"substringof('Ильченко', Description) and substringof('Екатерина', Description)"
    r = httpx.get(url, params={"$filter": filt, "$top": 3, "$format": "json"}, auth=auth, timeout=60)
    print(ent, r.status_code, len(r.text))
    if r.status_code == 200:
        for row in r.json().get("value") or []:
            print(" ", {k: row.get(k) for k in row if k in ("Description", "Code", "Ref_Key", "DeletionMark")})
            for k, v in row.items():
                if isinstance(v, str) and "@" in v:
                    print("   email field", k, v)
