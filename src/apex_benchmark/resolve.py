"""Per-value selection, reviewer decisions, conflicts and temporal controls."""
from __future__ import annotations
import calendar
import csv
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from .extract import METRICS
from .metrics import metric_labels, custom_metrics


def quarter_ends(target, count):
    end = date.fromisoformat(target)
    index = end.year * 4 + (end.month - 1) // 3
    result = []
    for q in range(index - count + 1, index + 1):
        year, quarter = divmod(q, 4)
        month = (quarter + 1) * 3
        result.append(f'{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]}')
    return result


def apply_decisions(candidates, decisions, cutoff):
    """A reviewer may interpret a source, but cannot add an uncited number."""
    by_id = {c['id']: c for c in candidates}
    applied = []
    seen = set()
    for entry in decisions:
        cid = entry['candidate_id']
        if cid in seen:
            raise ValueError(f'Duplicate decision for {cid}')
        seen.add(cid)
        if cid not in by_id:
            raise ValueError(f'Decision references unknown or changed evidence: {cid}')
        c = by_id[cid]
        if entry.get('action') not in {'accept', 'reject'}:
            raise ValueError('Decision action must be accept or reject')
        if not entry.get('reviewer') or not entry.get('reason'):
            raise ValueError('Reviewer identity and rationale are mandatory')
        c['review'] = entry
        c['eligible'] = False
        if entry['action'] == 'accept':
            if c.get('method') == 'nport_borrowings_ratio':
                raise ValueError('Derived N-PORT borrowing scope requires an implemented benchmark rule, not a quoted-value override')
            if c.get('method') == 'ocr_evidence' and entry.get('visual_verified') is not True:
                raise ValueError('OCR acceptance requires visual_verified=true after checking the original PDF')
            required = ['value', 'period', 'basis', 'share_class', 'evidence_text', 'unit']
            if any(entry.get(k) in (None, '') for k in required):
                raise ValueError(f'Accepted decision requires {required}')
            value = float(entry['value'])
            if not math.isfinite(value):
                raise ValueError('Value must be finite')
            if entry['evidence_text'] not in c['quote']:
                raise ValueError('Evidence text must occur verbatim in the cited source passage')
            # Require a source number equal to the accepted value (no ad hoc calculations).
            import re
            tokens = re.findall(r'\(?-?\d[\d,]*(?:\.\d+)?\)?', entry['evidence_text'])
            from .extract import number
            if not any(number(t) == value for t in tokens):
                raise ValueError('Accepted number must be present in the evidence text; derived metrics need a implemented formula')
            date.fromisoformat(entry['period'])
            if entry['period'] > cutoff or c['filing_date'] > cutoff:
                raise ValueError('Accepted evidence exceeds filing cutoff')
            if entry['unit'] != c['unit']:
                raise ValueError('Unit conversion requires an explicit supported transformation')
            for k in ['value', 'period', 'basis', 'share_class']:
                c[k] = entry[k]
            c['eligible'] = True
            c['reasons'] = ['Human-reviewed interpretation: ' + entry['reason']]
        applied.append(cid)
    return applied


def compatible(c, fund):
    if c['metric'].startswith('return_'):
        return c['basis'] == fund['return_basis'] and c['share_class'] == fund['share_class']
    if c['metric'] == 'management_fee':
        return c['basis'].startswith('contractual:')
    if c['metric'] == 'effective_fee':
        return c['basis'].startswith('effective:')
    if c['metric'] == 'nav':
        expected = 'book_value' if fund['structure'] == 'mortgage_reit' else 'nav'
        return c['basis'] == expected and c['share_class'] == fund['share_class']
    if c['metric'] == 'leverage':
        return c['basis'].startswith('debt_to_equity:')
    if c['metric'] == 'distribution_yield':
        return c['basis'].startswith('annualized:')
    return c['basis'] != 'unconfirmed'


def _resolve_metric(candidates, fund, metric, config, exact_period=None, retrieval_errors=None):
    relevant = [c for c in candidates if c['ticker'] == fund['ticker'] and c['metric'] == metric]
    relevant = [c for c in relevant if c['filing_date'] <= config['filing_cutoff']]
    eligible = [c for c in relevant if c['eligible'] and c['value'] is not None and compatible(c, fund)
                and c['period'] and c['period'] <= config['target_period']]
    if exact_period:
        eligible = [c for c in eligible if c['period'] == exact_period]
    result = {'ticker': fund['ticker'], 'metric': metric, 'label': metric_labels(config)[metric], 'value': None,
        'unit': custom_metrics(config).get(metric, {}).get('unit', 'USD/share' if metric == 'nav' else 'x' if metric == 'leverage' else '%'),
        'period': exact_period or '', 'status': 'needs_review' if relevant else 'not_found',
        'reason': 'Relevant evidence requires interpretation.' if relevant else
        'No supported value extracted from inspected documents; this does not establish non-disclosure.',
        'sources': [], 'candidate_ids': [c['id'] for c in relevant], 'basis': '',
        'comparability': 'Not assessed', 'lag_days': None}
    if retrieval_errors:
        extraction_only = all(isinstance(e, dict) and e.get('stage') in {'ocr', 'parse'} for e in retrieval_errors)
        result.update(status='extraction_incomplete' if extraction_only else 'retrieval_incomplete',
            reason='Source extraction incomplete; inspect OCR/parser errors before publication.' if extraction_only
            else 'SEC retrieval incomplete; availability and freshness cannot be certified.')
        # Preserve available evidence for review but never silently publish an older value.
        return result
    if not eligible:
        return result
    latest_period = max(c['period'] for c in eligible)
    chosen = [c for c in eligible if c['period'] == latest_period]
    # Do not suppress contradictions simply because one filing is newer.
    values = {(c['value'], c['basis'], c['share_class']) for c in chosen}
    precision_selected = None
    if len(values)>1 and len({(c['basis'],c['share_class']) for c in chosen})==1 and all(c.get('reported_precision_pct') for c in chosen):
        precise=min(chosen,key=lambda c:c['reported_precision_pct'])
        if all(abs(c['value']-precise['value']) <= c['reported_precision_pct']/2 + 1e-9 for c in chosen):
            precision_selected=precise
    if len(values) > 1 and precision_selected is None:
        result.update(status='conflict', reason='Accepted sources disagree for the same reporting period. Explicit reviewer rejection/rationale required.',
                      sources=chosen, period=latest_period)
        return result
    latest_filing = max(c['filing_date'] for c in chosen)
    # A newer relevant unresolved passage can change the interpretation. Surface it.
    unresolved = [c for c in relevant if not c['eligible'] and c.get('review', {}).get('action') != 'reject'
                  and c['filing_date'] >= latest_filing and c['value'] is not None]
    scoped_conflicts = [c for c in unresolved if c['period'] == latest_period
                       and compatible(c, fund) and c['value'] != chosen[0]['value']]
    if scoped_conflicts:
        result.update(status='needs_review', reason='Unresolved extraction candidates in the same or newer filing may change this value.',
                      sources=chosen, period=latest_period)
        return result
    selected = precision_selected or max(chosen, key=lambda c: (c['filing_date'], c['accession']))
    # Historical observations are evaluated against their requested quarter, not
    # against today's comparison quarter; old history is not stale current data.
    lag = (date.fromisoformat(exact_period or config['target_period']) - date.fromisoformat(latest_period)).days
    result.update(value=selected['value'], period=latest_period, basis=selected['basis'], sources=chosen,
        status='supported', lag_days=lag,
        reason='Source, unit, period and basis checks passed; PM and compliance approval still required.',
        comparability='Book value per share; not interchangeable with fund NAV' if fund['structure'] == 'mortgage_reit' and metric == 'nav'
            else 'Definition-specific; compare bases before use' if metric in {'leverage', 'distribution_yield', 'management_fee', 'effective_fee'}
            else 'Shareholder return for listed vehicles; NAV-based return for interval funds' if metric.startswith('return_')
            else 'As labeled')
    if any(c.get('review', {}).get('action') == 'accept' for c in chosen):
        result['decision_author'] = 'human'
    if precision_selected:
        result['reason'] += (' Source values reconcile within their explicitly reported rounding precision. '
                             f"The most precise figure, {selected['value']:.2f}%, is used; all source versions are retained.")
    if selected.get('method') in {'qualified_disclosure','annual_return_chain','return_index_ratio','dated_financial_table'}:
        result['reason'] += ' ' + ' '.join(selected.get('reasons', []))
    if selected.get('calculation'):
        result['calculation'] = selected['calculation']
        result['reason'] += ' Calculation: ' + selected['calculation']['expression'] + '.'
    if selected.get('nav_return_comparison'):
        comparison = selected['nav_return_comparison']
        result['nav_return_comparison'] = comparison
        result['reason'] += (f" Same-period 1Y NAV-based return: {comparison['nav_return_1y_pct']}%; "
                            f"shareholder return: {comparison['shareholder_return_1y_pct']}%; "
                            f"difference: {comparison['difference_percentage_points']:.2f} percentage points. {comparison['note']}")
    if unresolved:
        result['status'] = 'supported_with_review'
        result['unresolved_candidate_ids'] = [c['id'] for c in unresolved]
        result['reason'] += (f' {len(unresolved)} other numeric candidates have unconfirmed context or duplicate source values. '
                             'The explicitly dated and definition-matched source is used; other passages remain in the review queue, not treated as comparable facts.')
    if lag > config.get('stale_after_days', 120):
        result['status'] = 'lagged'
        result['reason'] += f' Reporting period is {lag} days behind target.'
    return result


APEX_COLUMNS = {'return_1y': 'net_return_1y_pct', 'return_3y': 'net_return_3y_pct',
    'return_5y': 'net_return_5y_pct', 'management_fee': 'management_fee_pct',
    'incentive_fee': 'incentive_fee_pct', 'hurdle': 'incentive_hurdle_pct',
    'nav': 'nav_per_share_usd', 'leverage': 'leverage_ratio_dte', 'distribution_yield': 'distribution_yield_pct'}


def internal_data(path: Path, config):
    approved = config.get('apex_data_approved', False)
    if approved and not (config.get('apex_approved_by') and config.get('apex_approval_note')):
        raise ValueError('Apex approval requires approver identity and approval note')
    if not approved:
        return {'status': 'withheld', 'reason': 'Dana disputed the starter data provenance. Awaiting source and row approval.',
                'values': {}, 'nav_history': []}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    history = []
    values = {}
    for row_number, row in enumerate(csv.DictReader(path.open()), 2):
        quarter, year = row['quarter'].split()
        month = int(quarter[1]) * 3
        period = f'{year}-{month:02d}-{calendar.monthrange(int(year), month)[1]}'
        if config['apex_history_start'] <= period <= config['target_period']:
            history.append({'period': period, 'value': float(row['nav_per_share_usd']), 'row': row_number})
        if period == config['target_period']:
            values = {metric: {'value': float(row[column]), 'period': period,
                'source': str(path), 'row': row_number, 'column': column, 'sha256': digest,
                'evidence_rationale': 'Client-approved internal input', 'approval': config['apex_approval_note']}
                for metric, column in APEX_COLUMNS.items()}
    return {'status': 'approved' if values else 'target_period_absent', 'values': values, 'nav_history': history,
        'reason': 'History begins Q1 2024. Later rows excluded from this historical comparison.'}


def resolve_metric(candidates, fund, metric, config, exact_period=None, retrieval_errors=None):
    from .evidence import annotate_result
    return annotate_result(_resolve_metric(candidates, fund, metric, config, exact_period, retrieval_errors))
