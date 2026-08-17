import base64, json, urllib.parse, urllib.request, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
env = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("="); env[k.strip()] = v.strip().strip('"').strip("'")
base = env["ODATA_BASE_URL"].rstrip("/")
num = "НП00-004286"
for label, user, pwd in [
    ("odata", env["ODATA_USERNAME"], env["ODATA_PASSWORD"]),
    ("erp", env["ERP_LOGIN"], env["ERP_PASSWORD"]),
]:
    auth = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {auth}"}
    entity_doc = "Document_ТД_ВходящаяКорреспонденция"
    url_doc = f"{base}/{urllib.parse.quote(entity_doc, safe='')}" + "?" + urllib.parse.urlencode({"$filter": f"Number eq '{num}'", "$format": "json"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url_doc, headers=headers), timeout=60) as resp:
            docs = json.loads(resp.read()).get("value") or []
        print(label, "doc ok", len(docs))
        if docs:
            print(" ", {k: docs[0].get(k) for k in ('Number','Date','Комментарий','Содержание','ТемаСлужебнойЗаписки') if k in docs[0]})
    except Exception as exc:
        print(label, "doc fail", exc)
