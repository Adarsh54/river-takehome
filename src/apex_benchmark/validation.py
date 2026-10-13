"""Replay saved evidence checks without API calls; not an independent accuracy benchmark."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from .judgment import validate_decision, JudgmentError
from .metrics import custom_metrics


def recalculate(calc):
    expression = calc['expression']; inputs = calc['inputs']
    if expression == '(product(1 + annual_return_pct / 100) ** (1 / years) - 1) * 100':
        if calc['years'] != len(inputs) or not inputs or any(v <= -100 for v in inputs.values()):
            raise ValueError('Invalid annual return chain')
        return (math.prod(1 + v / 100 for v in inputs.values()) ** (1 / calc['years']) - 1) * 100
    if expression == '((end_index / start_index) ** (1 / years) - 1) * 100':
        return ((inputs['end_index'] / inputs['start_index']) ** (1 / inputs['years']) - 1) * 100
    if expression in {'quarterly_hurdle_pct * 4', 'quarterly_management_fee_pct * 4'}:
        return inputs[expression.split()[0]] * 4
    raise ValueError('Calculation is not covered by the independent replay checker')


def validate_run(run, cache):
    cache = Path(cache); cfg = run['config']; checks = []; hashes = {}
    funds = {f['ticker']: f for f in cfg['funds']}
    for section in ('results', 'nav_history'):
        for r in run[section]:
            errors = []; published = r.get('value') is not None
            record = r.get('judgment') or {}
            if published:
                if not r.get('sources'): errors.append('No source citations')
                if r.get('unresolved_conflict'): errors.append('Unresolved conflict has a published figure')
                if not r.get('period') or r['period'] > cfg['target_period']: errors.append('Invalid observation period')
                if section == 'nav_history' and r.get('requested_period',r['period']) != r['period']:
                    errors.append('Wrong historical observation date')
                for source in r.get('sources', []):
                    digest = source.get('source_sha256','')
                    if digest not in hashes:
                        path = cache / digest
                        hashes[digest] = bool(re.fullmatch('[0-9a-f]{64}',digest) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest)
                    if not hashes[digest]: errors.append('Original source missing or hash mismatch')
                    if not all(source.get(k) for k in ('quote','locator','source_url')): errors.append('Incomplete citation')
                    if source.get('filing_date','9999') > cfg['filing_cutoff']: errors.append('Source filed after cutoff')
                if not record.get('decision'): errors.append('No replayable LLM decision; requires separate review')
            if record.get('decision'):
                packet = {'fund':funds[r['ticker']], 'metric':r['metric'],
                          'filing_cutoff':cfg['filing_cutoff'], 'target_period':cfg['target_period'],
                          'requested_period':r.get('requested_period') if section=='nav_history' else None,
                          'packet_complete':record.get('packet_complete',False),'conflict_contract':True,
                          'evidence':record.get('evidence_considered',[]),
                          'custom_metric_definition':custom_metrics(cfg).get(r['metric'],{})}
                try:
                    validate_decision(record['decision'],packet)
                    if published:
                        decision = record['decision']
                        if decision['decision'] != 'publish' or any(r.get(k) != decision.get(k) for k in ('value','unit','period','basis')):
                            errors.append('Displayed result differs from saved decision')
                except (JudgmentError,ValueError,KeyError,TypeError) as exc:
                    errors.append('Decision replay: '+str(exc))
            calc = r.get('calculation')
            if published and calc:
                try:
                    computed = recalculate(calc)
                    if not all(math.isclose(computed,v,rel_tol=1e-9,abs_tol=1e-9) for v in (calc['output'],r['value'])):
                        errors.append('Calculation does not reconcile')
                except (ValueError,KeyError,ZeroDivisionError,TypeError) as exc: errors.append(str(exc))
            checks.append({'ticker':r['ticker'],'metric':r['metric'],'period':r.get('period'),
                           'section':section,'published':published,
                           'status':'fail' if errors else 'pass' if published else 'gap',
                           'errors':list(dict.fromkeys(errors)), 'reason':r.get('reason',''),
                           'calculation_recomputed':bool(published and calc and not errors)})
    balances=[]
    for report in run.get('nport_reports',[]):
        from decimal import Decimal
        fields=report['fields']
        try:
            difference=Decimal(fields['totAssets']['raw'])-Decimal(fields['totLiabs']['raw'])-Decimal(fields['netAssets']['raw'])
            balances.append({'ticker':report.get('ticker'),'period':report.get('period'),
                             'status':'pass' if abs(difference)<=Decimal('0.02') else 'fail',
                             'difference_usd':str(difference),'tolerance_usd':'0.02'})
        except (KeyError,TypeError,ArithmeticError):
            balances.append({'ticker':report.get('ticker'),'period':report.get('period'),'status':'unavailable'})
    return {'run_id':run.get('run_id'), 'audit_sha256':hashlib.sha256(json.dumps(run,sort_keys=True).encode()).hexdigest(),
            'method':'Saved-decision replay, source hashes, date/citation checks and independent arithmetic; no model calls.',
            'limitations':'Not independent ground truth, retrieval recall, or proof of non-disclosure. Passing does not establish financial correctness.',
            'summary':dict(Counter(c['status'] for c in checks)), 'source_hashes_checked':len(hashes),
            'calculations_recomputed':sum(c['calculation_recomputed'] for c in checks),
            'nport_reconciliations':balances,'checks':checks}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--cache',type=Path,default=Path('.cache/sec'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=validate_run(json.loads(args.audit.read_text()),args.cache)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('summary','source_hashes_checked','calculations_recomputed')}))
    raise SystemExit(1 if result['summary'].get('fail') or any(x['status']=='fail' for x in result['nport_reconciliations']) else 0)

if __name__=='__main__':main()
