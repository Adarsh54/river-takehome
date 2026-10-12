"""Metric-independent immutable document index. Definitions never enter the cache key."""
import hashlib
import json
from pathlib import Path
from bs4 import BeautifulSoup
from .extract import clean

VERSION = 'passages-2'


def parse_passages(body):
    if body.startswith(b'%PDF'):
        from io import BytesIO
        from pypdf import PdfReader
        return [{'locator':f'PDF page {i+1}; native text','kind':'page','text':clean(p.extract_text() or '')}
                for i,p in enumerate(PdfReader(BytesIO(body)).pages)]
    soup=BeautifulSoup(body,'lxml')
    for node in soup(['script','style']):node.decompose()
    passages=[]
    headings=[]
    for i,node in enumerate(soup.find_all(['table','p','div','h1','h2','h3','h4']),1):
        if node.name in {'h1','h2','h3','h4'}:
            headings.append(clean(node.get_text(' ',strip=True)));headings=headings[-2:]
            continue
        if node.name=='table':
            if node.find('table'):continue
        elif node.find_parent('table') or node.find(['p','div','table']):continue
        text=clean(node.get_text(' ',strip=True))
        if not text:continue
        # Context is captured once, independently of the current question. Footnotes remain
        # separate passages too; exact adjacent text is retained with an explicit locator.
        before=[clean(x.get_text(' ',strip=True)) for x in node.find_previous_siblings(limit=2)]
        after=[clean(x.get_text(' ',strip=True)) for x in node.find_next_siblings(limit=3)]
        rows=[]
        if node.name=='table':
            for row in node.find_all('tr'):
                rows.append([{'text':clean(cell.get_text(' ',strip=True)),
                    'colspan':cell.get('colspan','1'),'rowspan':cell.get('rowspan','1')}
                    for cell in row.find_all(['th','td'],recursive=False)])
        passages.append({'rows':rows,'section_headings':list(headings),'locator':f'HTML {node.name} block {i}; preceding 2 and following 3 siblings',
            'kind':'table' if node.name=='table' else 'paragraph_or_footnote',
            'text':text,'context':' '.join([*reversed(before),text,*after])})
    return passages or [{'locator':'Document text','kind':'text','text':clean(soup.get_text(' ',strip=True))}]


def document_passages(cache, digest, stats=None):
    cache=Path(cache);folder=cache/'passages'/VERSION;folder.mkdir(parents=True,exist_ok=True)
    path=folder/(digest+'.json')
    body=(cache/digest).read_bytes()
    if hashlib.sha256(body).hexdigest()!=digest:raise ValueError('Source checksum mismatch')
    if path.exists():
        if stats is not None:stats['document_index_hits']=stats.get('document_index_hits',0)+1
        return json.loads(path.read_text())
    found=parse_passages(body)
    for i,p in enumerate(found,1):p['id']=f'{digest}:{VERSION}:{i}'
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(found));temp.replace(path)
    if stats is not None:stats['documents_parsed']=stats.get('documents_parsed',0)+1
    return found


from functools import lru_cache

@lru_cache(maxsize=192)
def _saved_passages(cache, digest):
    return document_passages(cache,digest)


def expand_candidate(candidate, cache):
    """Restore the enclosing table and nearby context without guessing its financial meaning."""
    c=candidate
    if c.get('calculation') or c['method'] in {'ocr_evidence','nport_borrowings_ratio'} or c['source_url'].lower().endswith('.xml'):
        return c
    if not c['quote'].strip():return c
    # A bare XBRL number can occur in many unrelated tables. Keep its original
    # tagged source location instead of attaching an arbitrary matching table.
    if not any(ch.isalpha() for ch in c['quote']):return c
    try:passages=_saved_passages(str(Path(cache).resolve()),c['source_sha256'])
    except (OSError,ValueError):return c  # Source-integrity checks still run before model review.
    matches=[p for p in passages if c['quote'] in p['text'] and len(p['text'])<=32000]
    if not matches:return c
    p=min(matches,key=lambda p:(p['kind']!='table',len(p['text'])))
    context=p.get('context',p['text'])
    if len(context)>40000:context=p['text']
    if context==c['quote'] and not p.get('rows'):return c
    compact_rows=[]
    for row in p.get('rows',[]):
        compact=[];column=0
        for cell in row:
            try:span=max(1,int(cell['colspan']))
            except (ValueError,TypeError):span=1
            if cell['text']:compact.append([column,cell['text'],span,cell['rowspan']])
            column+=span
        if compact:compact_rows.append(compact)
    return dict(c,id=hashlib.sha256((c['id']+p['id']).encode()).hexdigest()[:20],
        parent_candidate_id=c['id'],quote=context,table_rows=compact_rows,table_format="Rows of cells [column index, text, colspan, rowspan]; blank spacer cells omitted, column positions preserved",
        section_headings=p.get('section_headings',[]),
        locator=p['locator']+'; original extraction: '+c['locator'])
