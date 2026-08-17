import httpx, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
env={}
for line in Path('infra/.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); env[k.strip()]=v.strip().strip('"')
base=env['ODATA_BASE_URL'].rstrip('/')
svc=(env['ODATA_USERNAME'], env['ODATA_PASSWORD'])
user=(env.get('ERP_LOGIN',''), env.get('ERP_PASSWORD',''))
entity='Task_ЗадачаИсполнителя'
for label, auth in [('service', svc), ('user', user)]:
    r=httpx.get(f"{base}/{entity}", params={'$format':'json','$top':'20','$filter':'Executed eq false'}, auth=auth, timeout=60)
    rows=r.json().get('value',[]) if r.status_code==200 else []
    execs=sorted({str(x.get('Исполнитель')) for x in rows})
    print(label, 'status', r.status_code, 'rows', len(rows), 'executors', len(execs))
    for t in rows[:5]:
        print(' ', t.get('Number'), str(t.get('Исполнитель'))[:8], (t.get('Description') or '')[:50])
