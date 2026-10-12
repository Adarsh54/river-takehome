from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from .sec import SecClient, RetrievalError, discover, select_filings, filing_documents
from .extract import parse_document, documents_from_submission, METRICS
from .resolve import apply_decisions, resolve_metric, quarter_ends, internal_data
from .report import export


def validate_config(config):
    target = date.fromisoformat(config['target_period'])
    cutoff = date.fromisoformat(config['filing_cutoff'])
    if target > cutoff:
        raise ValueError('Target period must not exceed filing cutoff')
    if target.month not in {3,6,9,12} or target.isoformat() not in quarter_ends(target.isoformat(), 1):
        raise ValueError('Target must be a calendar quarter end')
    if not 1 <= config['history_quarters'] <= 40:
        raise ValueError('history_quarters must be between 1 and 40')
    if len({f['ticker'] for f in config['funds']}) != len(config['funds']):
        raise ValueError('Duplicate fund ticker')


def run_pipeline(config, client, internal_path, decisions=None, progress=print):
    validate_config(config)
    now = datetime.now(timezone.utc).isoformat()
    run = {'schema_version': 1, 'generated_at': now,
        'run_id': hashlib.sha256((now + json.dumps(config, sort_keys=True)).encode()).hexdigest()[:16],
        'config': config, 'mode': 'offline_cache' if client.offline else 'live_refresh' if client.refresh else 'live_with_cache',
        'filings': [], 'documents': [], 'candidates': [], 'errors': [], 'results': [], 'nav_history': [],
        'apex': internal_data(internal_path, config),
        'quarters': quarter_ends(config['target_period'], config['history_quarters'])}
    for fund in config['funds']:
        ticker = fund['ticker']
        progress(f'{ticker}: discovering SEC filings through {config["filing_cutoff"]}', flush=True)
        try:
            inventory = discover(client, fund['cik'], config['filing_cutoff'])
        except RetrievalError as exc:
            run['errors'].append({'ticker': ticker, 'stage': 'discovery', 'error': str(exc)})
            progress(f'{ticker}: {exc}', flush=True)
            continue
        selected = select_filings(inventory, config['target_period'])
        run['filings'].extend([dict(f, ticker=ticker) for f in selected])
        if not selected:
            run['errors'].append({'ticker': ticker, 'stage': 'discovery', 'error': 'No eligible relevant filings discovered; verify CIK and coverage.'})
        for index, filing in enumerate(selected):
            primary, full = filing_documents(client, fund['cik'], filing)
            progress(f'{ticker}: {index+1}/{len(selected)} {filing["form"]} {filing["filingDate"]}', flush=True)
            try:
                body, meta = client.get(full)
                docs = documents_from_submission(body, primary)
                # Some shareholder reports are PDF exhibits rather than HTML in the submission.
                for filename in re.findall(rb'<FILENAME>([^\r\n]+\.pdf)', body, re.I):
                    pdf_url = primary.rsplit('/', 1)[0] + '/' + filename.decode().strip()
                    pdf_body, _ = client.get(pdf_url)
                    docs.append((pdf_url, pdf_body))
                for url, content in docs:
                    digest = hashlib.sha256(content).hexdigest()
                    source = {'url': url, 'sha256': digest, 'submission_sha256': meta['sha256'],
                              'retrieved_at': meta['retrieved_at'], 'submission_url': full}
                    # Cache each parsed exhibit exactly as inspected; keep original submission too.
                    (client.cache / digest).write_bytes(content)
                    found = parse_document(content, fund, filing, source)
                    run['documents'].append(dict(source, ticker=ticker, accession=filing['accessionNumber'],
                        candidates=len(found)))
                    run['candidates'].extend(c.dict() for c in found)
            except (RetrievalError, ValueError) as exc:
                run['errors'].append({'ticker': ticker, 'stage': 'document', 'accession': filing['accessionNumber'], 'error': str(exc)})
                if '403' in str(exc):
                    break  # Honor access rejection; do not hammer the remaining URLs.
    run['candidates'] = list({c['id']: c for c in run['candidates']}.values())
    run['applied_decisions'] = apply_decisions(run['candidates'], decisions or [], config['filing_cutoff'])
    for fund in config['funds']:
        errors = [e for e in run['errors'] if e['ticker'] == fund['ticker']]
        for metric in METRICS:
            run['results'].append(resolve_metric(run['candidates'], fund, metric, config, retrieval_errors=errors))
        for period in run['quarters']:
            run['nav_history'].append(resolve_metric(run['candidates'], fund, 'nav', config, exact_period=period, retrieval_errors=errors))
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(description='Auditable SEC benchmarking; no synthetic competitor fallback.')
    parser.add_argument('--config', type=Path, default=Path('config/engagement.json'))
    parser.add_argument('--apex-data', type=Path, default=Path('data/apex_ridge_fund_data.csv'))
    parser.add_argument('--cache', type=Path, default=Path('.cache/sec'))
    parser.add_argument('--output', type=Path, default=Path('output/latest'))
    parser.add_argument('--decisions', type=Path, help='Reviewed candidate decisions JSON; see docs/review-workflow.md')
    parser.add_argument('--offline', action='store_true', help='Use previously downloaded real SEC responses only')
    parser.add_argument('--refresh', action='store_true', help='Recheck SEC responses instead of using URL cache')
    args = parser.parse_args(argv)
    if args.offline and args.refresh:
        parser.error('--offline and --refresh cannot be combined')
    ua = os.environ.get('SEC_USER_AGENT', '')
    if not ua and not args.offline:
        parser.error('Set SEC_USER_AGENT to your app name and real contact email; see README.')
    try:
        config = json.loads(args.config.read_text())
        decisions = json.loads(args.decisions.read_text()) if args.decisions else []
        client = SecClient(ua or 'offline-cache-only', args.cache, args.offline, args.refresh)
        run = run_pipeline(config, client, args.apex_data, decisions)
        export(run, args.output)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    counts = {}
    for result in run['results']:
        counts[result['status']] = counts.get(result['status'], 0) + 1
    print(json.dumps({'output': str(args.output.resolve()), 'statuses': counts,
        'retrieval_errors': len(run['errors']), 'apex': run['apex']['status']}, indent=2))
    return 2 if run['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
