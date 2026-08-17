import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
env = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
import win32com.client
conn = f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
doc = app.Metadata.Documents.ТД_ВходящаяКорреспонденция
print("Attributes:")
for i in range(doc.Attributes.Count()):
    print(" ", doc.Attributes.Get(i).Name)
print("\nTabularSections:")
for i in range(doc.TabularSections.Count()):
    print(" ", doc.TabularSections.Get(i).Name)
