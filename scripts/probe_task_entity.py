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

def probe(entity, auth, flt=None):
    params={'$format':'json','$top':'5'}
    if flt: params['$filter']=flt
    r=httpx.get(f"{base}/{entity}", params=params, auth=auth, timeout=60)
    print('\n===', entity, 'auth', auth[0][:20], 'filter', (flt or '-')[:50], '->', r.status_code)
    if r.status_code==200:
        rows=r.json().get('value',[])
        print('rows', len(rows))
        if rows:
            row=rows[0]
            for k,v in sorted(row.items()):
                if any(x in k for x in ('Исп','User','Completed','Date','Number','Наим','Subject','Description','Автор','Business')):
                    print(' ',k,':',v)
    else:
        print(r.text[:220])

for entity in ['Task_ЗадачаИсполнителя','BusinessProcess_Задание']:
    probe(entity, svc)
    probe(entity, user)
    probe(entity, svc, 'Completed eq false')
    probe(entity, user, 'Completed eq false')
