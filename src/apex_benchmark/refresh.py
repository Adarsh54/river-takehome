"""Refresh SEC inventories, ingest only new/changed accessions, compare result dependencies."""
import copy
import hashlib
import json
from .sec import discover, select_filings, RetrievalError
from .metrics import augment_custom, metric_labels
from .normalize import qualify_disclosures
from .structured_reports import derive_report_metrics
from .resolve import resolve_metric, quarter_ends, internal_data
from .judgment import build_packet


def cell_key(result, history=False):
    return (result['ticker'],result['metric'],result.get('requested_period') or result['period'] if history else None)


def dependencies(run, result, history=False):
    probe=dict(result)
    if history:probe['requested_period']=result.get('requested_period') or result['period']
    packet=build_packet(run,probe)
    # The cutoff controls selection. Once selection is done, identical evidence for the
    # same historical question does not need re-review merely because the cutoff advanced.
    packet.pop('filing_cutoff',None)
    errors=[e for e in run.get('errors',[]) if e['ticker']==result['ticker']]
    return hashlib.sha256(json.dumps([packet,errors],sort_keys=True).encode()).hexdigest()


def filing_identity(filing):
    return tuple(filing.get(k) for k in ('accessionNumber','form','filingDate','reportDate','primaryDocument'))


def refresh_saved(run,config,client,internal_path,pull,progress=print):
    from .policy import snapshot
    old_config=run['config'];old_funds={f['ticker']:f for f in old_config['funds']}
    old_filings={(f['ticker'],f['accessionNumber']):f for f in run['filings']}
    selected=[];new_by_fund={};keep=set();discovery_errors=[]
    client.refresh=True
    for fund in config['funds']:
        ticker=fund['ticker']
        progress(f'{ticker}: refreshing SEC inventory only',flush=True)
        try:
            filings=select_filings(discover(client,fund['cik'],config['filing_cutoff']),config['target_period'])
        except RetrievalError as exc:
            discovery_errors.append({'ticker':ticker,'stage':'discovery','error':str(exc)})
            filings=[f for (t,_),f in old_filings.items() if t==ticker]
        if not filings:
            discovery_errors.append({'ticker':ticker,'stage':'discovery','error':'No eligible filings found in refreshed SEC inventory.'})
        for f in filings:
            key=(ticker,f['accessionNumber']);old=old_filings.get(key)
            selected.append(dict(f,ticker=ticker))
            urls={d['url'] for d in run['documents'] if d['ticker']==ticker and d['accession']==key[1]}
            failed=any(e['ticker']==ticker and (e.get('accession')==key[1] or e.get('source_url') in urls) for e in run['errors'])
            if old and filing_identity(old)==filing_identity(f) and old_funds.get(ticker)==fund and not failed:
                keep.add(key)
            else:new_by_fund.setdefault(ticker,[]).append(f)
    from .incremental import prepare,compatible_audit
    if not new_by_fund and keep==set(old_filings) and compatible_audit(old_config,config) and not discovery_errors and not run['errors']:
        affected=prepare(run,config,client.cache)
        run['incremental'].update(unchanged_filings_reused=len(keep),new_or_changed_filings=0)
        progress(f'Source refresh: {len(keep)} unchanged filings; {len(affected)} changed policy/metric cells',flush=True)
        client.refresh=False
        return affected
    before={cell_key(r,h):(copy.deepcopy(r),dependencies(run,r,h))
        for h,rows in ((False,run['results']),(True,run['nav_history'])) for r in rows}
    # SEC accessions are immutable identities; amendments are new accessions. Recheck
    # inventory metadata, not thousands of unchanged submission bodies on every refresh.
    client.refresh=False
    client.refresh_accessions={f['accessionNumber'] for t,fs in new_by_fund.items() for f in fs if (t,f['accessionNumber']) in old_filings}
    for name in ('documents','candidates','nport_reports','extraction_diagnostics'):
        run[name]=[x for x in run.get(name,[]) if (x.get('ticker'),x.get('accession')) in keep]
    run['errors']=discovery_errors
    run['config']=config;run['filings']=selected
    run['quarters']=quarter_ends(config['target_period'],config['history_quarters'])
    run['apex']=internal_data(internal_path,config)
    stats={'documents_parsed':0,'document_index_hits':0,'unchanged_filings_reused':len(keep),
           'new_or_changed_filings':sum(map(len,new_by_fund.values()))}
    if new_by_fund:
        fresh=pull([f for f in config['funds'] if f['ticker'] in new_by_fund],new_by_fund)
        for name in ('documents','candidates','nport_reports','extraction_diagnostics','errors'):
            run[name].extend(fresh.get(name,[]))
        for key in ('documents_parsed','document_index_hits'):stats[key]+=fresh.get('incremental',{}).get(key,0)
    run['incremental']=stats
    # Derived facts are content-cached per document; normalization reads saved facts.
    run['candidates'].extend(derive_report_metrics(run['documents'],run['filings'],config,client.cache))
    run['candidates']=[c for c in run['candidates'] if c.get('method')!='qualified_disclosure']
    run['candidates'].extend(qualify_disclosures(run['candidates'],run['filings'],config))
    augment_custom(run,client.cache)
    run['candidates']=list({c['id']:c for c in run['candidates']}.values())
    affected=set();results=[];history=[]
    for fund in config['funds']:
        errors=[e for e in run['errors'] if e['ticker']==fund['ticker']]
        for metric,period,h in [(m,None,False) for m in metric_labels(config)]+[('nav',p,True) for p in run['quarters']]:
            result=resolve_metric(run['candidates'],fund,metric,config,exact_period=period,retrieval_errors=errors)
            key=cell_key(result,h);old=before.get(key)
            saved_policy=run.get('comparison_policy_snapshot',snapshot(old_config)).get(metric)
            if old and old[1]==dependencies(run,result,h) and saved_policy==snapshot(config).get(metric):result=old[0]
            else:affected.add(key)
            (history if h else results).append(result)
    run['results']=results;run['nav_history']=history
    valid={cell_key(r,h) for h,rows in ((False,results),(True,history)) for r in rows}
    run['llm_judgments']=[j for j in run.get('llm_judgments',[]) if (j['ticker'],j['metric'],j.get('requested_period')) in valid-affected]
    progress(f"Source refresh: {stats['unchanged_filings_reused']} unchanged filings reused; {stats['new_or_changed_filings']} new/changed; {len(affected)} affected cells",flush=True)
    return affected
