"""Fetch a curated set of official sources; snapshots are not live regulatory verification."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from app import config
from scripts.ingest import split

HUB = 'https://extension.umn.edu/agriculture/crop-production/nutrient-management-for-minnesota-crops'
TOPICS = {
 'Corn fertilizer guidelines':'Кукурудза: живлення', 'Soybean fertilizer guidelines':'Соя: живлення',
 'Barley':'Ячмінь: живлення', 'Buckwheat':'Гречка: живлення', 'Wheat':'Пшениця: живлення',
 'Canola':'Ріпак: живлення', 'Sunflower':'Соняшник: живлення',
 'Understanding nitrogen in soils':'Азот у ґрунті', 'Guide to using urea as a crop fertilizer in Minnesota':'Карбамід',
 'Understanding phosphorus fertilizers':'Фосфорні добрива', 'Guide to potassium for Minnesota crops':'Калій',
 'Sulfur':'Сірка', 'Zinc':'Цинк', 'Boron':'Бор', 'Lime needs in Minnesota':'Вапнування',
 'Understanding plant analysis for crops':'Аналіз рослин', 'Understanding the soil test report':'Аналіз ґрунту'}
PDFS = [
 ('sops_research_2025_1','https://journal.sops.gov.ua/issue/download/19223/12529','Сортовивчення та охорона прав на сорти рослин, 2025, №1','УІЕСР / НАН України','UA','uk',2025),
 ('sare_soils_2021','https://www.sare.org/wp-content/uploads/Building-Soils-for-Better-Crops.pdf','Building Soils for Better Crops, 4th edition','SARE / USDA NIFA','US','en',2021),
 ('sare_cover_crops_2007','https://www.sare.org/wp-content/uploads/Managing-Cover-Crops-Profitably.pdf','Managing Cover Crops Profitably, 3rd edition','SARE / USDA NIFA','US','en',2007),
 ('fao_nutrition_2006','https://www.fao.org/4/a0443e/a0443e.pdf','Plant Nutrition for Food Security','FAO','International','en',2006),
 ('ifa_nutrition','https://assets.fsnforum.fao.org/public/discussions/contributions/IFA_nutrientmanagementbook_ENG_webversion.pdf','Nutrient Management Handbook','IFA (hosted by FAO FSN Forum)','International','en',None),
]

OUT = config.DATA / 'sources'
MANIFEST = config.DATA / 'library_manifest.json'


def fetch(url):
    response = requests.get(url, timeout=(10, 45), headers={'User-Agent':'AgroLibrary/1.0 (personal research library)'})
    response.raise_for_status()
    if len(response.content) > 60_000_000:
        raise ValueError('File exceeds 60 MB')
    return response


def extract_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    article = soup.select_one('article') or soup.select_one('main')
    if article is None:
        raise ValueError('No article/main content')
    for element in article.select('script,style,nav,footer,form,button'):
        element.decompose()
    for table in article.find_all('table'):
        rows = [' | '.join(cell.get_text(' ', strip=True) for cell in row.find_all(['th','td']))
                for row in table.find_all('tr')]
        table.replace_with('\nTABLE\n' + '\n'.join(rows) + '\nEND TABLE\n')
    text = article.get_text('\n', strip=True)
    if len(text) < 500:
        raise ValueError('Article too short')
    title = soup.find('h1')
    return title.get_text(' ', strip=True) if title else '', text


def download(pdf_only=False):
    OUT.mkdir(parents=True, exist_ok=True)
    entries = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    known = {e['id']:e for e in entries}
    now = datetime.now(timezone.utc).isoformat()
    try:
        soup = BeautifulSoup('' if pdf_only else fetch(HUB).text, 'html.parser')
    except requests.RequestException as exc:
        print('Hub unavailable:', type(exc).__name__, flush=True)
        soup = BeautifulSoup('', 'html.parser')
    links = {}
    for a in soup.find_all('a', href=True):
        label = ' '.join(a.get_text(' ', strip=True).split())
        if label in TOPICS:
            links[label] = urljoin(HUB,a['href'])
    links.update({
        'Wheat':'https://extension.umn.edu/node/11226',
        'Canola':'https://extension.umn.edu/node/8521',
        'Sunflower':'https://extension.umn.edu/node/8671',
        'Guide to using urea as a crop fertilizer in Minnesota':'https://extension.umn.edu/node/8501',
    })
    if pdf_only:
        links = {}
    for label, url in links.items():
        key = 'umn_' + hashlib.sha256(url.encode()).hexdigest()[:12]
        try:
            response = fetch(url)
            title, text = extract_html(response.text)
            sections = split(text, size=4000, overlap=200)
            path = OUT / f'{key}.json'
            path.write_text(json.dumps({'title': title, 'sections':sections},ensure_ascii=False,indent=2))
            known[key] = {'id':key,'title':title,'topic_uk':TOPICS[label],'publisher':'University of Minnesota Extension',
                          'region':'US-Minnesota','language':'en','publication_year':None,
                          'retrieved_at':now,'source_url':response.url,'kind':'web','file':str(path.relative_to(config.ROOT)),
                          'sha256':hashlib.sha256(response.content).hexdigest(),'status':'downloaded',
                          'use':'background_only; rates require local validation; not Ukrainian product authorization'}
            print('Downloaded', TOPICS[label], len(sections), 'sections',flush=True)
        except Exception as exc:
            print('FAILED',label,type(exc).__name__,str(exc)[:120],flush=True)
    for key,url,title,publisher,region,language,year in PDFS:
        try:
            response = fetch(url)
            if not response.content.startswith(b'%PDF'):
                raise ValueError('Response is not PDF')
            path = config.PDF_DIR / f'{key}.pdf'
            path.write_bytes(response.content)
            known[key] = {'id':key,'title':title,'publisher':publisher,'region':region,'language':language,
                          'publication_year':year,'retrieved_at':now,'source_url':response.url,'kind':'pdf',
                          'file':str(path.relative_to(config.ROOT)),'sha256':hashlib.sha256(response.content).hexdigest(),
                          'status':'downloaded','use':'background_only; not current pesticide authorization'}
            print('Downloaded PDF',key,flush=True)
        except Exception as exc:
            print('FAILED',key,type(exc).__name__,str(exc)[:120],flush=True)
    MANIFEST.write_text(json.dumps(list(known.values()),ensure_ascii=False,indent=2))


def index():
    from app.rag import embedding_model, resources
    from scripts.ingest import ingest
    col, model = resources(), embedding_model()
    entries = json.loads(MANIFEST.read_text())
    for entry in entries:
        if entry.get('status') == 'excluded':
            continue
        path = config.ROOT / entry['file']
        if entry['kind'] == 'pdf':
            count = ingest(path,col,model)
        else:
            snapshot = json.loads(path.read_text())
            documents,metas,ids = [],[],[]
            for section, text in enumerate(snapshot['sections'],1):
                for j, chunk in enumerate(split(text)):
                    if len(chunk) < 61:
                        continue
                    documents.append(chunk)
                    metas.append({'source':str(path.resolve()),'page':section})
                    ids.append(f"{entry['id']}-{entry['sha256']}-p{section}-{j}")
            if not documents:
                raise ValueError('Empty snapshot')
            embeddings = model.encode(['passage: '+snapshot['title']+'\n'+d for d in documents],
                                      normalize_embeddings=True,batch_size=32,show_progress_bar=False)
            old = col.get(where={'source':str(path.resolve())},include=[])['ids']
            for i in range(0,len(ids),100):
                col.upsert(ids=ids[i:i+100],documents=documents[i:i+100],metadatas=metas[i:i+100],embeddings=embeddings[i:i+100].tolist())
            stale = sorted(set(old)-set(ids))
            if stale: col.delete(ids=stale)
            count = len(ids)
        entry['status']='indexed'; entry['chunks']=count
        MANIFEST.write_text(json.dumps(entries,ensure_ascii=False,indent=2))
        print('Indexed',entry['id'],count,flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--pdf-only',action='store_true')
    parser.add_argument('--fetch',action='store_true');parser.add_argument('--index',action='store_true')
    args=parser.parse_args()
    if args.fetch: download(args.pdf_only)
    if args.index: index()
