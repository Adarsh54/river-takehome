"""Explicit dependency planning: a definition edit invalidates only that metric."""
from .metrics import custom_metrics, augment_custom, metric_labels
from .resolve import resolve_metric


def compatible_audit(prior, current):
    return {k:v for k,v in prior.items() if k not in {'custom_metrics','funds'}} == {
        k:v for k,v in current.items() if k not in {'custom_metrics','funds'}}


def prepare(run, config, cache, pull_funds=None):
    prior=run['config']
    if not compatible_audit(prior,config):raise ValueError('Period or source policy changed; rebuild source discovery.')
    old=custom_metrics(prior);new=custom_metrics(config)
    changed={k for k in old.keys()|new.keys() if old.get(k)!=new.get(k)}
    oldfunds={f['ticker']:f for f in prior['funds']}
    funds={f['ticker']:f for f in config['funds']}
    changed_funds={t for t,f in funds.items() if oldfunds.get(t)!=f}
    removed=set(oldfunds)-set(funds)
    discard=changed_funds|removed
    run['config']=config
    run['incremental']={'changed_metrics':sorted(changed),'changed_funds':sorted(changed_funds),
                        'documents_parsed':0,'document_index_hits':0}
    for key in ('results','nav_history','rule_results','rule_nav_history','candidates','filings','documents','errors','llm_judgments','nport_reports','extraction_diagnostics'):
        if key in run:run[key]=[x for x in run[key] if x.get('ticker') not in discard]
    # Retain all unrelated candidates and decisions byte-for-byte, including old gaps.
    run['results']=[r for r in run['results'] if r['metric'] not in changed]
    if 'rule_results' in run:run['rule_results']=[r for r in run['rule_results'] if r['metric'] not in changed]
    run['llm_judgments']=[r for r in run.get('llm_judgments',[]) if r['metric'] not in changed]
    augment_custom(run,cache,affected=changed)
    affected=set()
    for fund in config['funds']:
        if fund['ticker'] in changed_funds:continue
        errors=[e for e in run['errors'] if e['ticker']==fund['ticker']]
        for metric in sorted(changed & new.keys()):
            run['results'].append(resolve_metric(run['candidates'],fund,metric,config,retrieval_errors=errors))
            affected.add((fund['ticker'],metric,None))
    if changed_funds:
        if pull_funds is None:raise ValueError('New or changed funds need a source pull')
        fresh=pull_funds([f for f in config['funds'] if f['ticker'] in changed_funds])
        for key in ('results','nav_history','rule_results','rule_nav_history','candidates','filings','documents','errors','nport_reports','extraction_diagnostics'):
            run.setdefault(key,[]).extend(fresh.get(key,[]))
        for r in fresh['results']:affected.add((r['ticker'],r['metric'],None))
        for r in fresh['nav_history']:affected.add((r['ticker'],r['metric'],r['period']))
        for name in ('documents_parsed','document_index_hits'):
            run['incremental'][name]+=fresh.get('incremental',{}).get(name,0)
    order={(f['ticker'],m):i for i,(f,m) in enumerate((f,m) for f in config['funds'] for m in metric_labels(config))}
    run['results'].sort(key=lambda r:order[(r['ticker'],r['metric'])])
    return affected
