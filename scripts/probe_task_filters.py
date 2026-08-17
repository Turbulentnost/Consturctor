import httpx, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
env={}
for line in Path('infra/.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); env[k.strip()]=v.strip().strip('"')
base=env['ODATA_BASE_URL'].rstrip('/')
auth=(env['ODATA_USERNAME'], env['ODATA_PASSWORD'])
ref='570178f6-b0fd-11e0-be8f-cbb269b2aa2d'
filters=[
    f"Исполнитель eq guid'{ref}'",
    f"Исполнитель_Key eq guid'{ref}'",
    'ПринятаКИсполнению eq true',
    'Выполнена eq false',
    'Executed eq false',
]
for flt in filters:
    r=httpx.get(f"{base}/Task_ЗадачаИсполнителя", params={'$format':'json','$top':'3','$filter':flt}, auth=auth, timeout=45)
    msg=len(r.json().get('value',[])) if r.status_code==200 else r.text[:150].replace('\n',' ')
    print(flt, '->', r.status_code, msg)
