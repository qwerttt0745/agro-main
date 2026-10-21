"""Import two verified regional NAAN publications without rebuilding other books."""
import hashlib
import json
from datetime import datetime, timezone
from pypdf import PdfReader
from app import config, rag
from scripts.import_library import fetch, MANIFEST
from scripts.ingest import ingest

SOURCES = [
 ('naan_zhytomyr_autumn_2025','https://isgpnaan.org/upload/rekomendatsii_-posiv-ozimih-2025.pdf','Осінньо-польові роботи та посів озимих культур на Житомирщині, 2025'),
 ('naan_zhytomyr_spring_2025','https://isgpnaan.org/upload/vesnyano-polovi-roboti-2025.pdf','Весняно-польові роботи на Житомирщині в умовах змін кліматичних чинників, 2025')
]

def main():
    manifest=json.loads(MANIFEST.read_text())
    known={e['id']:e for e in manifest}
    for key,url,title in SOURCES:
        response=fetch(url)
        if not response.content.startswith(b'%PDF'):raise ValueError('Not a PDF')
        path=config.PDF_DIR/(key+'.pdf');path.write_bytes(response.content)
        reader=PdfReader(path)
        first=' '.join((p.extract_text() or '') for p in reader.pages[:3])
        if '2025' not in first or len(first)<500:raise ValueError('Publication needs manual text review')
        count=ingest(path,rag.resources(),rag.embedding_model())
        now=datetime.now(timezone.utc).isoformat()
        known[key]={'id':key,'title':title,'publisher':'Інститут сільського господарства Полісся НААН',
         'region':'UA-Zhytomyr','language':'uk','publication_year':2025,'published_at':None,
         'last_verified_at':now,'retrieved_at':now,'source_url':url,'kind':'pdf','document_type':'regional_recommendations',
         'file':str(path.relative_to(config.ROOT)),'sha256':hashlib.sha256(response.content).hexdigest(),
         'status':'indexed','chunks':count,'pdf_pages':len(reader.pages),
         'license':'Public download from publisher; no open redistribution license asserted. Private household library.',
         'use':'Regional background for 2025; distinguish Polissia and Forest-Steppe; not current weather, outbreak evidence or pesticide authorization'}
        MANIFEST.write_text(json.dumps(list(known.values()),ensure_ascii=False,indent=2))
        print(key,len(reader.pages),'pages',count,'chunks',flush=True)

if __name__=='__main__':main()
