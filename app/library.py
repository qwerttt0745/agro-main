"""Only expose PDFs inside the configured library, never paths supplied by a client."""
import hashlib
import json
from pathlib import Path
from app import config


def files():
    root = config.PDF_DIR.resolve()
    result = {}
    for path in sorted(root.rglob('*.pdf')):
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            continue
        key = hashlib.sha256(str(path.relative_to(root)).encode()).hexdigest()[:24]
        result[key] = path
    return result


def source_url(source, page):
    matches = [(key, path) for key, path in files().items()
               if path.name == Path(source).name]
    if len(matches) != 1:
        return None
    return f'/library/{matches[0][0]}/pdf#page={page}'


def manifest():
    path = config.DATA / 'library_manifest.json'
    return json.loads(path.read_text()) if path.exists() else []


def provenance(source):
    matches = [e for e in manifest() if Path(e['file']).name == Path(source).name]
    if len(matches) == 1:
        return matches[0]
    if Path(source).name == 'TVPR_2_2010.pdf':
        return {'title': 'Технології виробництва продукції рослинництва, 2010',
                'publication_year':2010, 'region':'UA', 'language':'uk', 'status':'indexed',
                'use':'Історичне навчальне джерело; не підтверджує чинні норми застосування препаратів.'}
    return {'title':Path(source).name, 'publication_year':None, 'region':'невідомий',
            'use':'Походження та актуальність не перевірені.'}


def catalog():
    rows = []
    for key, path in files().items():
        item = provenance(path).copy()
        if item.get('status') == 'excluded':
            continue
        item.update({'document':path.name,'url':f'/library/{key}/pdf'})
        item.pop('file',None)
        rows.append(item)
    return rows
