"""Versioned user metric definitions and source-bound, reported-value retrieval."""
from __future__ import annotations
import hashlib
import json
import re
from bs4 import BeautifulSoup
from .extract import METRICS, Candidate, clean


def custom_metrics(config):
    return {m['id']: m for m in config.get('custom_metrics', [])}


def metric_labels(config):
    return {**METRICS, **{m['id']: f"{m['label']} ({m['unit']})" for m in config.get('custom_metrics', [])}}


def validate_metrics(config):
    seen=set(METRICS)
    for m in config.get('custom_metrics', []):
        if not isinstance(m,dict) or not re.fullmatch(r'custom_[a-z][a-z0-9_]{0,47}',m.get('id','')):
            raise ValueError('Custom metric IDs must start with custom_ and contain lowercase letters, numbers or underscores.')
        if m['id'] in seen: raise ValueError('Duplicate metric ID')
        seen.add(m['id'])
        for key,limit in [('label',100),('definition',2000),('unit',32)]:
            if not isinstance(m.get(key),str) or not m[key].strip() or len(m[key])>limit:
                raise ValueError(f'Custom metric requires {key} (maximum {limit} characters).')
        if m.get('scope') not in {'fund','share_class'}: raise ValueError('Metric scope must be fund or share_class')
        if m.get('period_basis') not in {'point_in_time','fiscal_year','trailing_12_months'}:
            raise ValueError('Choose point_in_time, fiscal_year, or trailing_12_months')
        if not isinstance(m.get('keywords'),list) or not 1<=len(m['keywords'])<=12 or any(not isinstance(k,str) or not k.strip() or len(k)>100 for k in m['keywords']):
            raise ValueError('Provide 1 to 12 literal search phrases, each 1 to 100 characters.')
        if m.get('calculation','reported_only')!='reported_only':
            raise ValueError('Custom metrics currently support disclosed values only, not user formulas.')


def definition_hash(metric):
    return hashlib.sha256(json.dumps(metric,sort_keys=True).encode()).hexdigest()


def extract_custom(body, fund, filing, source, definitions):
    """Keep complete tables and adjacent context; never auto-approve a numeric regex guess."""
    if not definitions or source['url'].lower().endswith('.xml'):
        return []
    passages=[]
    if body.startswith(b'%PDF'):
        from io import BytesIO
        from pypdf import PdfReader
        reader=PdfReader(BytesIO(body))
        passages=[(f'PDF page {i+1}; native text',clean(page.extract_text() or '')) for i,page in enumerate(reader.pages)]
    else:
        soup=BeautifulSoup(body,'lxml')
        for tag in soup(['script','style']):tag.decompose()
        for i,table in enumerate(soup.find_all('table'),1):
            if table.find('table'):continue
            text=clean(table.get_text(' ',strip=True))
            if text:passages.append((f'HTML table {i}',text))
        for i,block in enumerate(soup.find_all(['p','div']),1):
            if block.find_parent('table') or block.find(['p','div','table']):continue
            text=clean(block.get_text(' ',strip=True))
            if text:passages.append((f'Custom text block {i}',text))
        if not passages:passages=[('Document text',clean(soup.get_text(' ',strip=True)))]
    result=[]
    for m in definitions:
        for loc,text in passages:
            if not any(k.lower() in text.lower() for k in m['keywords']):continue
            result.append(Candidate(ticker=fund['ticker'],metric=m['id'],value=None,unit=m['unit'],
                period=filing.get('reportDate',''),basis='unconfirmed',share_class='unconfirmed',
                filing_date=filing['filingDate'],form=filing['form'],accession=filing['accessionNumber'],
                source_url=source['url'],source_sha256=source['sha256'],locator=loc,quote=text,
                method='custom_reported_evidence',eligible=False,
                reasons=['User-defined metric requires interpretation of definition, period, unit and scope.'],
                extraction_meta={'metric_definition_sha256':definition_hash(m)}).dict())
    return result


def augment_custom(run, cache):
    """Re-extract custom definitions from immutable downloaded documents without new SEC calls."""
    from pathlib import Path
    definitions=list(custom_metrics(run['config']).values())
    run['candidates']=[c for c in run['candidates'] if not c['metric'].startswith('custom_')]
    if not definitions:return
    funds={f['ticker']:f for f in run['config']['funds']}
    filings={(f['ticker'],f['accessionNumber']):f for f in run['filings']}
    parsed=Path(cache)/'custom';parsed.mkdir(exist_ok=True)
    for doc in run['documents']:
        fund=funds.get(doc['ticker']);filing=filings.get((doc['ticker'],doc['accession']))
        if not fund or not filing:continue
        key=hashlib.sha256(json.dumps([doc,fund,filing,definitions,'custom-v2'],sort_keys=True).encode()).hexdigest()
        path=parsed/(key+'.json')
        try:
            body=(Path(cache)/doc['sha256']).read_bytes()
            if hashlib.sha256(body).hexdigest()!=doc['sha256']:raise ValueError('Custom extraction source checksum mismatch')
            if path.exists():found=json.loads(path.read_text())
            else:
                found=extract_custom(body,fund,filing,{'url':doc['url'],'sha256':doc['sha256']},definitions)
                path.write_text(json.dumps(found))
            run['candidates'].extend(found)
        except (OSError,ValueError) as exc:
            run['errors'].append({'ticker':doc['ticker'],'stage':'parse','error':str(exc),'source_url':doc['url']})
    # Existing page OCR remains subject to the same visual-verification gate.
    for c in list(run['candidates']):
        if c['method']!='ocr_evidence':continue
        for m in definitions:
            if not any(k.lower() in c['quote'].lower() for k in m['keywords']):continue
            clone=dict(c,metric=m['id'],value=None,unit=m['unit'],basis='unconfirmed',eligible=False)
            clone['id']=hashlib.sha256((c['id']+definition_hash(m)).encode()).hexdigest()[:20]
            clone['extraction_meta']=dict(c.get('extraction_meta',{}),metric_definition_sha256=definition_hash(m))
            run['candidates'].append(clone)
    run['candidates']=list({c['id']:c for c in run['candidates']}.values())
