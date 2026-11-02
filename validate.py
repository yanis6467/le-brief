import json
from pathlib import Path
from urllib.parse import urlparse
r=Path(__file__).resolve().parent
f=json.loads((r/'news.json').read_text())
p=json.loads((r/'policy.json').read_text())
ids=set();valid={'eco','markets','world','france','deals'}
for i in f['items']:
    assert i['id'] not in ids;ids.add(i['id'])
    assert i['category'] in valid and 0<=i['importance']<=100
    assert i['title'].strip() and 1<=len(i['bullets'])<=5
    assert all(urlparse(s['url']).scheme=='https' for s in i['sources'])
    if i['category']=='deals':assert i['dealValueEUR']>=100000000 and i['dealValueSource']
assert p['automaticAIEnabled'] is False and p['paidAPIFallback'] is False
assert p['providerDailyLimitTokens'] is None and p['providerQuotaVerified'] is False
assert p['unknownQuotaAction']=='deny' and p['maximumShare']==0.25
for name in ['index.html','app.js','styles.css','sw.js','manifest.webmanifest','icon-192.png','icon-512.png','apple-touch-icon.png']:
    assert (r/name).is_file(), name
print(f'{len(ids)} fiches valides ; sources HTTPS ; seuil M&A ; politique de budget bloquée ; fichiers PWA présents.')
