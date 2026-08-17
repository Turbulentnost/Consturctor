import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
env = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("="); env[k.strip()] = v.strip().strip('"').strip("'")
import win32com.client
conn = f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
cat = app.Metadata.Catalogs.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы
print("file catalog attrs:")
for i in range(cat.Attributes.Count()):
    n = cat.Attributes.Get(i).Name
    if any(x in n.lower() for x in ("текст", "text", "извле", "хран", "data", "данн")):
        print(" ", n)
