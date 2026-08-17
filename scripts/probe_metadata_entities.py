import re, httpx, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
env={}
for line in Path('infra/.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); env[k.strip()]=v.strip().strip('"')
base=env['ODATA_BASE_URL'].rstrip('/')
auth=(env['ODATA_USERNAME'], env['ODATA_PASSWORD'])
print('fetch metadata...')
r=httpx.get(base+'/$metadata', auth=auth, timeout=120)
print('status', r.status_code)
text=r.text
tasks=[n for n in set(re.findall(r'EntityType Name="((?:Task|BusinessProcess)_[^"]+)"', text))]
for n in sorted(tasks):
    print(n)
