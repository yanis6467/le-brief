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
from html.parser import HTMLParser
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
    ('Franceinfo', 'eco', 'Économie', 'https://www.franceinfo.fr/economie.rss'),
    ('Franceinfo', 'markets', 'Marchés', 'https://www.franceinfo.fr/economie/bourse/marches.rss'),
    ('Franceinfo', 'world', 'International', 'https://www.franceinfo.fr/monde.rss'),
    ('Franceinfo', 'france', 'Faits divers', 'https://www.franceinfo.fr/faits-divers.rss'),
    ('Franceinfo', 'france', 'Santé', 'https://www.franceinfo.fr/sante.rss'),
    ('Franceinfo', 'france', 'Personnalités', 'https://www.franceinfo.fr/culture/people.rss'),
    ('Franceinfo', 'france', 'Environnement', 'https://www.franceinfo.fr/meteo.rss'),
    ('Le Monde', 'france', 'Justice', 'https://www.lemonde.fr/police-justice/rss_full.xml'),
]
ALLOWED_HOSTS = {'www.lemonde.fr', 'www.lefigaro.fr', 'lemonde.fr', 'lefigaro.fr', 'www.tradingsat.com', 'tradingsat.com', 'www.franceinfo.fr', 'www.francetvinfo.fr'}
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
    if category=='eco' and re.search(r'petition|arcom',t) and re.search(r'cnews|chaine|assemblee',t):
        return 'france','Politique'
    if category == 'france':
        if re.search(r'etats.unis|japon|bresil|ukraine|israel|gaza|chine|royaume.uni',t) and not re.search(r'france|francais|paris',t):
            return 'world', topic
        for label, pattern in [('Santé',r'sante|hopital|medicament|vaccin|epidemie'),('Éducation',r'lycee|ecole|parcoursup|education|universit'),('Justice',r'proces|tribunal|justice|condamn'),('Faits divers',r'meurtre|incendie|accident|disparition|agression'),('Environnement',r'inondation|tempete|secheresse|meteo|climat')]:
            if re.search(pattern,t):
                return category,label
    if category == 'eco':
        if any('/'+p+'/' in path for p in ['politique', 'societe', 'education', 'culture', 'livres', 'cinema']):
            return 'france', 'Culture' if any(x in path for x in ['culture','livres','cinema']) else 'Société'
        if any(w in t for w in ['cac 40', 'wall street', 'nasdaq', 's&p 500', 'marches financiers', 'bourses europeennes']):
            return 'markets', 'Marchés'
        if any('/'+p+'/' in path for p in ['pixels', 'm-le-mag', 'les-recettes-du-monde']):
            return None, None
    return category, topic

class ArticleHTML(HTMLParser):
    """Read JSON-LD and article paragraphs, never navigation or suggestions."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[];self.scripts=[];self.paragraphs=[];self.script=None;self.paragraph=None

    def handle_starttag(self,tag,attrs):
        a=dict(attrs);marker=(a.get('class','')+' '+a.get('id','')).lower()
        blocked=tag in ('nav','aside','footer','header','noscript','style') or bool(re.search(r'newsletter|related|recommend|smartfeed|comment|advert|paywall|subscription',marker))
        active=tag=='article' or a.get('itemprop')=='articleBody' or bool(re.search(r'article[_-]+(?:body|content|paragraph)|t-content__body|c-body|c-text',marker))
        self.stack.append((tag,blocked,active))
        if tag=='script' and a.get('type')=='application/ld+json':self.script=[]
        if tag=='p' and not any(x[1] for x in self.stack) and any(x[2] for x in self.stack):self.paragraph=[]
        if tag=='br' and self.paragraph is not None:self.paragraph.append(' ')
        if tag in ('br','hr','img','meta','link','input','source','wbr'):self.stack.pop()

    def handle_data(self,data):
        if self.script is not None:self.script.append(data)
        elif self.paragraph is not None and not any(x[0] in ('script','style') for x in self.stack):self.paragraph.append(data)

    def handle_endtag(self,tag):
        if tag=='script' and self.script is not None:
            self.scripts.append(''.join(self.script));self.script=None
        if tag=='p' and self.paragraph is not None:
            self.paragraphs.append(plain(''.join(self.paragraph)));self.paragraph=None
        for k in range(len(self.stack)-1,-1,-1):
            if self.stack[k][0]==tag:
                del self.stack[k:];break

def objects(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():yield from objects(child)
    elif isinstance(value,list):
        for child in value:yield from objects(child)

def article_text(markup,title,url):
    if re.search(r'isAccessibleForFree["\x27]?\s*[:=]\s*["\x27]?false',markup,re.I):return '', 'restricted'
    if re.search(r'itemprop=["\x27]isAccessibleForFree["\x27][^>]*content=["\x27]false',markup,re.I):return '', 'restricted'
    parser=ArticleHTML();parser.feed(markup)
    main=[]
    for script in parser.scripts:
        try:data=json.loads(script)
        except (ValueError,TypeError):continue
        for obj in objects(data):
            if 'Article' not in str(obj.get('@type','')):continue
            h=tokens(plain(obj.get('headline','')));target=tokens(title)
            if h and len(h & target)/max(1,len(target)) < .45:continue
            main.append(obj)
    if any(o.get('isAccessibleForFree') in (False,'false') or any(p.get('isAccessibleForFree') in (False,'false') for p in objects(o.get('hasPart'))) for o in main):
        return '', 'restricted'
    if re.search(r'article r[eé]serv[eé] aux abonn[eé]s|pour lire la suite.{0,60}abonn',markup,re.I):return '', 'restricted'
    for obj in main:
        body=obj.get('articleBody')
        if isinstance(body,str) and len(body)>200:return plain(body),'public'
    text='\n'.join(p for p in parser.paragraphs if len(p)>45)
    return (text,'public') if len(text)>200 else ('','unavailable')

def key_sentences(text,title,max_words=95):
    """Extract complete, complementary sentences. Never manufacture a number."""
    text=re.sub(r'(?<=[a-zà-ö])\.(?=\d)', '.\n', text)
    sentences=re.split(r'(?<=[.!?])\s+|(?<=[.!?])(?=[A-ZÀ-Ö])|\n+',text)
    title_tokens=tokens(title);title_figures=set(re.findall(r'\d+(?:[.,]\d+)?',title))
    candidates=[]
    for index,sentence in enumerate(sentences):
        sentence=plain(sentence).strip()
        if sentence.count('"')%2:sentence=sentence.strip('"')
        if sentence.count('«')!=sentence.count('»'):sentence=sentence.strip('«» ')
        words=sentence.split();t=norm(sentence);v=tokens(sentence)
        if not 8<=len(words)<=52 or len(v-title_tokens)<3:continue
        if re.search(r'abonnez|newsletter|cookies|cliquez|transcription|reportage ci.dessus|a lire aussi|lire egalement|retrouvez|notre selection|\bcopyright\b',t):continue
        if re.match(r'^(il|elle|ils|elles|cela|ceci|ce dernier|cette derniere|celui.ci|celle.ci|c.est|mais aussi)\b',t):continue
        overlap=len(v & title_tokens)/max(1,len(title_tokens))
        if len(v-title_tokens)/max(1,len(v))<.25:continue
        figures=set(re.findall(r'\d+(?:[.,]\d+)?',sentence))
        number=bool(figures-title_figures and re.search(r'%|euros?|dollars?|millions?|milliards?|points?|personnes?|victimes?|lycees?|ans|mois|jours?|metres?|heures?',t))
        action=bool(re.search(r'annonce|adopt|prevoit|prevu|decid|augmente|baisse|recul|croiss|contre|coute|cout|atteint|publie|decede|condamn|interdi|devra|permet|concerne|genere|revenus?|perte|benefice',t))
        if not number and re.search(r'nous deplorons|regrettable|contre.product|paradoxal|a mon avis|selon moi',t):continue
        rating=overlap*4+number*5+action*2+2/(1+index/4)
        candidates.append((rating,index,sentence,v,len(words)))
    selected=[];total=0
    for rating,index,sentence,v,size in sorted(candidates,reverse=True):
        if total+size>max_words:continue
        if any(len(v & old[3])/max(1,len(v | old[3]))>.55 for old in selected):continue
        selected.append((rating,index,sentence,v,size));total+=size
        if len(selected)==3:break
    return [s[2] for s in sorted(selected,key=lambda x:x[1])]

def enrich_item(item,previous,now,blocked):
    if item.get('provenance') not in ('rss-excerpt','article-extract'):return item
    old=previous.get(item['id'])
    if old and old.get('provenance')=='article-extract' and old.get('summaryInput')==item.get('summaryInput'):
        try:
            if now-dt.datetime.fromisoformat(old['enrichedAt'])<dt.timedelta(hours=12):
                return dict(item,bullets=old['bullets'],provenance='article-extract',enrichedAt=old['enrichedAt'],detailLevel='article',context=old.get('context'),sources=[dict(item['sources'][0],access='public'),*item['sources'][1:]])
        except (ValueError,KeyError):pass
    url=item['sources'][0]['url'];host=urlsplit(url).hostname
    if host in blocked:return item
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'LeBrief/1.2 public news reader'})
        with urllib.request.urlopen(req,timeout=8) as response:
            if urlsplit(response.url).hostname not in ALLOWED_HOSTS:return item
            raw=response.read(2_500_001)
        if len(raw)>2_500_000:return item
        text,access=article_text(raw.decode('utf-8','replace'),item['title'],url)
        points=key_sentences(text,item['title']) if text else []
        if len(points)>=2:
            period=re.search(r'résultats (?:du|de son) ((?:premier|deuxième|troisième|quatrième|[1-4]e?r?) trimestre)',text,re.I)
            context='Résultats du '+period.group(1) if period else None
            return dict(item,bullets=points,provenance='article-extract',enrichedAt=now.isoformat(),detailLevel='article',context=context,sources=[dict(item['sources'][0],access='public'),*item['sources'][1:]])
    except Exception as exc:
        if getattr(exc,'code',None) in (401,403,429):blocked.add(host)
    return dict(item,detailLevel='preview')

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
        if re.search(r'^(en direct|direct|replay|podcast|quiz)|que faire de l.action|faut.il acheter|notre selection|nos conseils|horoscope|mots croises|tribune|le point de vue|il y a \d+ ans|comment |pourquoi ', norm(title)) or '/replay-radio/' in link:
            continue
        cat, top = classify(category, topic, title, link)
        if not cat:
            continue
        description = plain(entry.findtext('description'))
        if re.search(r'bitcoin|crypto|ethereum', norm(title)) and not re.search(r'interdi|regula|faillit|pirat|fraude|loi|etf', norm(title+' '+description)):
            continue
        points = excerpt(description, title)
        importance = score(title, description, cat, pub, now)
        if cat in ('eco','markets') and importance < 50:
            continue
        out.append(dict(id='rss-'+hashlib.sha256(link.encode()).hexdigest()[:18],revision=1,
            category=cat,topic=top,title=title,bullets=points,publishedAt=pub.isoformat(),
            updatedAt=pub.isoformat(),importance=importance,
            sources=[dict(publisher=publisher,url=link,access='extrait')],verifiedAt=now.date().isoformat(),
            provenance='rss-excerpt',summaryInput=hashlib.sha256((title+description+'|extract-v2').encode()).hexdigest(),detailLevel='preview'))
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
    reviewed = [i for i in prior.values() if i['category'] != 'deals' and i.get('provenance') not in ('rss-excerpt','article-extract') and now-dt.datetime.fromisoformat(i['publishedAt'].replace('Z','+00:00')).replace(tzinfo=UTC) <= dt.timedelta(days=7)]
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
    # A market price recap becomes stale quickly. Keep the latest CAC session
    # instead of filling the feed with its opening, intraday and closing moves.
    grouped = [i for i in grouped if i['category'] != 'markets' or
        now-dt.datetime.fromisoformat(i['publishedAt'].replace('Z','+00:00')).replace(tzinfo=UTC) <= dt.timedelta(hours=72)]
    cac = [i for i in grouped if i['category']=='markets' and re.match(r'^cac 40\s*:',norm(i['title']))]
    if cac:
        latest = max(cac,key=lambda i:i['publishedAt'])
        grouped = [i for i in grouped if i not in cac or i is latest]
    selected = []
    for category, limit in [('eco',12),('markets',12),('world',12),('france',16)]:
        candidates = [i for i in grouped if i['category']==category]
        topics, chosen = {}, []
        if category=='france':
            for topic in ['Politique','Société','Éducation','Santé','Justice','Faits divers','Culture','Environnement','Personnalités']:
                candidate=next((i for i in candidates if i['topic']==topic and i['importance']>=43),None)
                if candidate:chosen.append(candidate);topics[topic]=1
        for item in candidates:
            if item in chosen:continue
            if topics.get(item['topic'],0) < (3 if category=='france' else limit):
                chosen.append(item);topics[item['topic']]=topics.get(item['topic'],0)+1
            if len(chosen)==limit:
                break
        if len(chosen)<min(8,limit):
            chosen.extend(i for i in candidates if i not in chosen and len(chosen)<min(8,limit))
        selected.extend(chosen)
    blocked=set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        selected=list(pool.map(lambda i:enrich_item(i,prior,now,blocked),selected))
    selected=[i for i in selected if i['bullets']]
    if any(not any(i['category']==cat for i in selected) for cat in ['eco','markets','world','france']):
        raise RuntimeError('Une rubrique principale est vide : dernier lot conservé.')
    for item in selected:
        old = prior.get(item['id'])
        if old:
            item['revision'] = old['revision'] + (content_signature(item)!=content_signature(old))
    return dict(schemaVersion=1,edition=now.astimezone(ZoneInfo('Europe/Paris')).date().isoformat(),
        preparedAt=now.isoformat(),generationMode='rss-rules',automaticAI=False,
        automationStatus='hourly-rss',items=selected,feedHealth=sorted(statuses,key=lambda s:s['url']),
        editorialPolicy='Courts extraits factuels des articles accessibles ou aperçu RSS ; aucun appel IA ; pas de contournement des abonnements.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='site/data/news.json');args=p.parse_args()
    path=Path(args.output)
    previous=json.loads(path.read_text()) if path.exists() else {}
    feed=collect(previous,dt.datetime.now(UTC))
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(feed,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)
    print(json.dumps({'items':len(feed['items']),'successfulFeeds':sum(s['ok'] for s in feed['feedHealth']),'articleDetails':sum(i.get('provenance')=='article-extract' for i in feed['items']),'categories':{c:sum(i['category']==c for i in feed['items']) for c in ['eco','markets','world','france']}}))

if __name__=='__main__':
    main()
