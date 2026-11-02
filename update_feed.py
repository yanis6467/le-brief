"""Free, deterministic RSS collection. No model, API key or paid service."""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit

UTC = dt.timezone.utc
FEEDS = [
    ('Le Monde', 'eco', 'Économie', 'https://www.lemonde.fr/economie/rss_full.xml'),
    ('Le Figaro', 'eco', 'Économie', 'https://www.lefigaro.fr/rss/figaro_economie.xml'),
    ('BFM Bourse', 'markets', 'Marchés', 'https://www.tradingsat.com/rssbourse.xml'),
    ('Le Figaro', 'markets', 'Bourse', 'https://www.lefigaro.fr/rss/figaro_bourse.xml'),
    ('Le Monde', 'world', 'International', 'https://www.lemonde.fr/international/rss_full.xml'),
    ('Le Figaro', 'world', 'International', 'https://www.lefigaro.fr/rss/figaro_international.xml'),
    ('Le Monde', 'france', 'Politique', 'https://www.lemonde.fr/politique/rss_full.xml'),
    ('Le Monde', 'france', 'Société', 'https://www.lemonde.fr/societe/rss_full.xml'),
    ('Le Monde', 'france', 'Éducation', 'https://www.lemonde.fr/education/rss_full.xml'),
    ('Le Monde', 'france', 'Culture', 'https://www.lemonde.fr/culture/rss_full.xml'),
    ('Le Figaro', 'france', 'France', 'https://www.lefigaro.fr/rss/figaro_actualite-france.xml'),
]
ALLOWED_HOSTS = {'www.lemonde.fr', 'www.lefigaro.fr', 'lemonde.fr', 'lefigaro.fr', 'www.tradingsat.com', 'tradingsat.com'}
STOP = set('dans pour avec sans plus une des les aux sur par est sont cette comme apres avant leur entre fait france monde direct nouveau nouvelle'.split())

def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value or ''))).strip()

def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.lower()) if not unicodedata.combining(c))

def canonical(value):
    u = urlsplit(value)
    if u.scheme != 'https' or u.hostname not in ALLOWED_HOSTS:
        return None
    return urlunsplit((u.scheme, u.netloc, u.path, '', ''))

def tokens(title):
    return set(re.findall(r'\b[a-z0-9]{3,}\b', norm(title))) - STOP

def same_story(a, b):
    if {s['url'] for s in a['sources']} & {s['url'] for s in b['sources']}:
        return True
    if a['category'] != b['category']:
        return False
    x, y = tokens(a['title']), tokens(b['title'])
    # Do not conflate updates whose announced figures differ.
    if re.findall(r'\d+(?:[.,]\d+)?', a['title']) != re.findall(r'\d+(?:[.,]\d+)?', b['title']):
        return False
    return len(x & y) >= 6 and len(x & y) / max(1, len(x | y)) >= .82

def classify(category, topic, title, url):
    path = urlsplit(url).path
    t = norm(title)
    if category == 'eco':
        if any('/'+p+'/' in path for p in ['politique', 'societe', 'education', 'culture', 'livres', 'cinema']):
            return 'france', 'Culture' if any(x in path for x in ['culture','livres','cinema']) else 'Société'
        if any(w in t for w in ['cac 40', 'wall street', 'nasdaq', 's&p 500', 'marches financiers', 'bourses europeennes']):
            return 'markets', 'Marchés'
        if any('/'+p+'/' in path for p in ['pixels', 'm-le-mag', 'les-recettes-du-monde']):
            return None, None
    return category, topic

def score(title, description, category, published, now):
    t = norm(title + ' ' + description)
    # Explainable editorial rules: breadth and consequences outrank recency.
    groups = [
        (22, r'inflation|taux directeur|banque centrale|reserve federale|\bbce\b|\bfed\b|droits? de douane|\bpib\b'),
        (20, r'guerre|cessez.le.feu|nucleaire|attaque|invasion|frappes|sanctions'),
        (18, r'budget|election|presidentiell|premier ministre|gouvernement|assemblee|dissolution|reforme'),
        (16, r'wall street|cac 40|nasdaq|s&p 500|bourses|krach|recession|chomage|obligataire|dette souveraine'),
        (12, r'milliard|millions de|national|europeen|etats.unis|zone euro|chine'),
        (8, r'education|lycee|sante|justice|attentat|meurtre|alerte|deces|prix litteraire|medicis|goncourt'),
    ]
    base = 38 + sum(weight for weight, pattern in groups if re.search(pattern, t))
    hours = max(0, (now-published).total_seconds()/3600)
    return min(99, max(0, base + int(max(0, 10-hours/12))))

def excerpt(description, title):
    description = plain(description)
    if description.startswith(title):
        description = description[len(title):].lstrip(' :.-')
    if not description or norm(description) == norm(title):
        return []
    # Copy only the publisher's short public feed teaser; do not infer facts.
    words = description.split()
    if len(words) > 50:
        description = ' '.join(words[:50]).rstrip('.,;:') + '…'
    parts = re.split(r'(?<=[.!?])\s+(?=[A-ZÀ-Ö])', description)
    return parts if len(parts) <= 2 else [description]

def fetch_source(spec, now):
    publisher, category, topic, url = spec
    req = urllib.request.Request(url, headers={'User-Agent':'LeBrief/1.1 (public RSS reader; https://github.com/yanis6467/le-brief)'})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000 or b'<!ENTITY' in data.upper():
        raise ValueError('Flux refusé : taille ou entité XML')
    root = ET.fromstring(data)
    entries = root.findall('.//item')
    if not entries:
        raise ValueError('Flux RSS vide ou invalide')
    out = []
    for entry in entries[:80]:
        title, link = plain(entry.findtext('title')), canonical(entry.findtext('link') or '')
        try:
            pub = parsedate_to_datetime(entry.findtext('pubDate') or '').astimezone(UTC)
        except (ValueError, TypeError):
            continue
        if not link or not title or pub > now + dt.timedelta(minutes=10) or now-pub > dt.timedelta(days=7):
            continue
        # Advice, opinion, quizzes, live video and repeat explainers are not breaking facts.
        if re.search(r'^(en direct|direct|replay|podcast|quiz)|que faire de l.action|faut.il acheter|notre selection|nos conseils|horoscope|mots croises|tribune|le point de vue|il y a \d+ ans|[«\"]|comment |pourquoi ', norm(title)):
            continue
        cat, top = classify(category, topic, title, link)
        if not cat:
            continue
        description = plain(entry.findtext('description'))
        if re.search(r'bitcoin|crypto|ethereum', norm(title)) and not re.search(r'interdi|regula|faillit|pirat|fraude|loi|etf', norm(title+' '+description)):
            continue
        points = excerpt(description, title)
        if not points:
            continue
        importance = score(title, description, cat, pub, now)
        if cat in ('eco','markets') and importance < 50:
            continue
        out.append(dict(id='rss-'+hashlib.sha256(link.encode()).hexdigest()[:18],revision=1,
            category=cat,topic=top,title=title,bullets=points,publishedAt=pub.isoformat(),
            updatedAt=pub.isoformat(),importance=importance,
            sources=[dict(publisher=publisher,url=link,access='extrait')],verifiedAt=now.date().isoformat(),
            provenance='rss-excerpt',note='Titre et court extrait du flux RSS public de '+publisher+'. Classement automatique par règles ; aucun résumé généré par IA.'))
    return out

def content_signature(item):
    return json.dumps([item['title'],item['bullets'],item['sources']],sort_keys=True,ensure_ascii=False)

def collect(previous, now):
    results, statuses = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        pending = {pool.submit(fetch_source, spec, now): spec for spec in FEEDS}
        for task in concurrent.futures.as_completed(pending):
            spec = pending[task]
            try:
                batch = task.result()
                results.extend(batch)
                statuses.append(dict(publisher=spec[0],url=spec[3],ok=True,candidates=len(batch)))
            except Exception as exc:
                statuses.append(dict(publisher=spec[0],url=spec[3],ok=False,error=type(exc).__name__))
    if sum(s['ok'] for s in statuses) < 3 or len(results) < 8:
        raise RuntimeError('Collecte insuffisante : le dernier lot est conservé.')
    prior = {i['id']:i for i in previous.get('items',[])}
    # Keep manually reviewed items only while recent, and preserve reviews for the same URL.
    reviewed = [i for i in prior.values() if i.get('provenance') != 'rss-excerpt' and now-dt.datetime.fromisoformat(i['publishedAt'].replace('Z','+00:00')).replace(tzinfo=UTC) <= dt.timedelta(days=7)]
    for i in reviewed:
        i = dict(i)
        i['importance'] = min(i['importance'], score(i['title'],' '.join(i['bullets']),i['category'],dt.datetime.fromisoformat(i['publishedAt'].replace('Z','+00:00')).replace(tzinfo=UTC),now))
        results.append(i)
    results.sort(key=lambda i:(-i['importance'], -dt.datetime.fromisoformat(i['publishedAt'].replace('Z','+00:00')).replace(tzinfo=UTC).timestamp(), i['id']))
    grouped = []
    for item in results:
        duplicate = next((g for g in grouped if same_story(item,g)),None)
        if duplicate:
            # Extra references do not imply independent verification.
            for source in item['sources']:
                if source['url'] not in {s['url'] for s in duplicate['sources']}:
                    duplicate['sources'].append(source)
            continue
        grouped.append(item)
    selected = []
    for category, limit in [('eco',12),('markets',12),('world',12),('france',15),('deals',8)]:
        candidates = [i for i in grouped if i['category']==category]
        topics, chosen = {}, []
        for item in candidates:
            if topics.get(item['topic'],0) < (4 if category=='france' else limit):
                chosen.append(item);topics[item['topic']]=topics.get(item['topic'],0)+1
            if len(chosen)==limit:
                break
        if len(chosen)<min(8,limit):
            chosen.extend(i for i in candidates if i not in chosen and len(chosen)<min(8,limit))
        selected.extend(chosen)
    if any(not any(i['category']==cat for i in selected) for cat in ['eco','markets','world','france']):
        raise RuntimeError('Une rubrique principale est vide : dernier lot conservé.')
    for item in selected:
        old = prior.get(item['id'])
        if old:
            item['revision'] = old['revision'] + (content_signature(item)!=content_signature(old))
    return dict(schemaVersion=1,edition=now.astimezone(ZoneInfo('Europe/Paris')).date().isoformat(),
        preparedAt=now.isoformat(),generationMode='rss-rules',automaticAI=False,
        automationStatus='hourly-rss',items=selected,feedHealth=sorted(statuses,key=lambda s:s['url']),
        editorialPolicy='Titres et extraits RSS publics ; tri déterministe ; aucun appel IA ; pas de contournement des abonnements.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='site/data/news.json');args=p.parse_args()
    path=Path(args.output)
    previous=json.loads(path.read_text()) if path.exists() else {}
    feed=collect(previous,dt.datetime.now(UTC))
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(feed,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)
    print(json.dumps({'items':len(feed['items']),'successfulFeeds':sum(s['ok'] for s in feed['feedHealth']),'categories':{c:sum(i['category']==c for i in feed['items']) for c in ['eco','markets','world','france','deals']}}))

if __name__=='__main__':
    main()
