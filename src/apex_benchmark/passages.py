"""Metric-independent immutable document index. Definitions never enter the cache key."""
import hashlib
import json
from pathlib import Path
from bs4 import BeautifulSoup
from .extract import clean

VERSION = 'passages-1'


def parse_passages(body):
    if body.startswith(b'%PDF'):
        from io import BytesIO
        from pypdf import PdfReader
        return [{'locator':f'PDF page {i+1}; native text','kind':'page','text':clean(p.extract_text() or '')}
                for i,p in enumerate(PdfReader(BytesIO(body)).pages)]
    soup=BeautifulSoup(body,'lxml')
    for node in soup(['script','style']):node.decompose()
    passages=[]
    for i,node in enumerate(soup.find_all(['table','p','div']),1):
        if node.name=='table':
            if node.find('table'):continue
        elif node.find_parent('table') or node.find(['p','div','table']):continue
        text=clean(node.get_text(' ',strip=True))
        if not text:continue
        # Context is captured once, independently of the current question. Footnotes remain
        # separate passages too; exact adjacent text is retained with an explicit locator.
        before=[clean(x.get_text(' ',strip=True)) for x in node.find_previous_siblings(limit=2)]
        after=[clean(x.get_text(' ',strip=True)) for x in node.find_next_siblings(limit=3)]
        passages.append({'locator':f'HTML {node.name} block {i}; preceding 2 and following 3 siblings',
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
