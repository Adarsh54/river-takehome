"""Versioned user metric definitions and source-bound, reported-value retrieval."""
from __future__ import annotations
import hashlib
import json
import re
from .extract import METRICS, Candidate


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
        fields=m.get('context_fields',[])
        if not isinstance(fields,list) or len(fields)>10 or any(not isinstance(f,str) or not f.strip() or len(f)>80 for f in fields) or len(fields)!=len(set(fields)):
            raise ValueError('Provide up to 10 unique context fields, each 1 to 80 characters.')
        if m.get('calculation','reported_only')!='reported_only':
            raise ValueError('Custom metrics currently support disclosed values only, not user formulas.')


def definition_hash(metric):
    return hashlib.sha256(json.dumps(metric,sort_keys=True).encode()).hexdigest()


def candidates_from_passages(passages, fund, filing, source, definitions):
    result=[]
    for m in definitions:
        for passage in passages:
            text=passage.get('context',passage['text'])
            if not any(k.lower() in text.lower() for k in m['keywords']):continue
            result.append(Candidate(ticker=fund['ticker'],metric=m['id'],value=None,unit=m['unit'],
                period=filing.get('reportDate',''),basis='unconfirmed',share_class='unconfirmed',
                filing_date=filing['filingDate'],form=filing['form'],accession=filing['accessionNumber'],
                source_url=source['url'],source_sha256=source['sha256'],locator=passage['locator'],quote=text,
                method='custom_reported_evidence',eligible=False,
                reasons=['User-defined metric requires interpretation of definition, period, unit and scope.'],
                extraction_meta={'metric_definition_sha256':definition_hash(m),
                                 'passage_id':passage.get('id')}).dict())
    return result


def extract_custom(body, fund, filing, source, definitions):
    from .passages import parse_passages
    if not definitions or source['url'].lower().endswith('.xml'):return []
    return candidates_from_passages(parse_passages(body),fund,filing,source,definitions)


def augment_custom(run, cache, affected=None):
    """Retrieve only affected custom definitions from saved, metric-independent passages."""
    definitions=[m for m in custom_metrics(run['config']).values() if affected is None or m['id'] in affected]
    run['candidates']=[c for c in run['candidates'] if not c['metric'].startswith('custom_') or (affected is not None and c['metric'] not in affected)]
    if not definitions:return
    funds={f['ticker']:f for f in run['config']['funds']}
    filings={(f['ticker'],f['accessionNumber']):f for f in run['filings']}
    from .passages import document_passages
    stats=run.setdefault('incremental',{})
    stats.setdefault('documents_parsed',0)
    stats.setdefault('document_index_hits',0)
    for doc in run['documents']:
        fund=funds.get(doc['ticker']);filing=filings.get((doc['ticker'],doc['accession']))
        if not fund or not filing or doc['url'].lower().endswith('.xml'):continue
        try:
            passages=document_passages(cache,doc['sha256'],stats)
            found=candidates_from_passages(passages,fund,filing,doc,definitions)
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
