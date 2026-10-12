from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from .sec import SecClient, RetrievalError, discover, select_filings, filing_documents
from .extract import parse_document, documents_from_submission, METRICS
from .resolve import apply_decisions, resolve_metric, quarter_ends, internal_data
from .report import export
from .normalize import qualify_disclosures
from .structured_reports import derive_report_metrics
from .metrics import metric_labels, validate_metrics, augment_custom

PARSER_VERSION = hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes()
    for name in ('extract.py', 'nport.py', 'pdf_extract.py'))).hexdigest()


def validate_config(config):
    validate_metrics(config)
    if not isinstance(config.get('funds'),list) or not config['funds']:
        raise ValueError('At least one fund is required')
    for fund in config['funds']:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,23}',fund.get('ticker','')) or not re.fullmatch(r'\d{1,10}',fund.get('cik','')):
            raise ValueError('Each fund needs a safe comparison label and a numeric CIK')
        if fund.get('structure') not in {'interval','bdc','mortgage_reit','other'} or fund.get('return_basis') not in {'shareholder','net_nav'} or not fund.get('share_class'):
            raise ValueError('Each fund needs structure, return basis and share class')
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


def run_pipeline(config, client, internal_path, decisions=None, progress=print, ocr_mode='auto'):
    validate_config(config)
    from .pdf_extract import ocr_environment
    ocr_runtime = ocr_environment()
    now = datetime.now(timezone.utc).isoformat()
    run = {'schema_version': 1, 'generated_at': now,
        'run_id': hashlib.sha256((now + json.dumps(config, sort_keys=True)).encode()).hexdigest()[:16],
        'config': config, 'mode': 'offline_cache' if client.offline else 'live_refresh' if client.refresh else 'live_with_cache',
        'filings': [], 'documents': [], 'nport_reports': [], 'extraction_diagnostics': [],
        'ocr': {'mode': ocr_mode, **ocr_runtime}, 'candidates': [], 'errors': [], 'results': [], 'nav_history': [],
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
                    parse_key = hashlib.sha256(json.dumps([digest, source, fund, filing, PARSER_VERSION, ocr_mode, ocr_runtime], sort_keys=True).encode()).hexdigest()
                    parsed_dir = client.cache / 'parsed'
                    parsed_dir.mkdir(exist_ok=True)
                    parsed_path = parsed_dir / (parse_key + '.json')
                    if parsed_path.exists():
                        parsed = json.loads(parsed_path.read_text())
                    else:
                        diagnostics, structured = [], []
                        try:
                            found = [c.dict() for c in parse_document(content, fund, filing, source,
                                diagnostics=diagnostics, structured=structured,
                                ocr_mode=ocr_mode, ocr_environment=ocr_runtime)]
                        except (ValueError, OSError) as exc:
                            found = []
                            diagnostics.append({'stage': 'parse', 'status': 'failed', 'error': str(exc)})
                        parsed = {'candidates': found, 'diagnostics': diagnostics, 'structured': structured}
                        # Failures are retried on rerun (e.g. missing language data or transient OCR timeout).
                        if not any(d.get('error') for d in diagnostics):
                            parsed_path.write_text(json.dumps(parsed, allow_nan=False))
                    if not url.lower().endswith('.xml'):
                        from .passages import document_passages
                        document_passages(client.cache,digest,run.setdefault('incremental',{}))
                    found = parsed['candidates']
                    run['nport_reports'].extend(parsed['structured'])
                    for diagnostic in parsed['diagnostics']:
                        diagnostic = dict(diagnostic, ticker=ticker, accession=filing['accessionNumber'], source_url=url)
                        run['extraction_diagnostics'].append(diagnostic)
                        if diagnostic.get('error'):
                            run['errors'].append(diagnostic)
                    run['documents'].append(dict(source, ticker=ticker, accession=filing['accessionNumber'],
                        candidates=len(found)))
                    run['candidates'].extend(found)
            except (RetrievalError, ValueError) as exc:
                run['errors'].append({'ticker': ticker, 'stage': 'document', 'accession': filing['accessionNumber'], 'error': str(exc)})
                progress(f'{ticker}: {exc}', flush=True)
                if isinstance(exc, RetrievalError) and exc.status_code == 403:
                    break  # Honor access rejection; do not hammer the remaining URLs.
    run['candidates'] = list({c['id']: c for c in run['candidates']}.values())
    if run['documents']:
        run['candidates'].extend(derive_report_metrics(run['documents'], run['filings'], config, client.cache))
    run['candidates'].extend(qualify_disclosures(run['candidates'], run['filings'], config))
    if config.get('custom_metrics'):
        progress('Gathering source passages for custom metric definitions',flush=True)
        augment_custom(run, client.cache)
    run['applied_decisions'] = apply_decisions(run['candidates'], decisions or [], config['filing_cutoff'])
    for fund in config['funds']:
        errors = [e for e in run['errors'] if e['ticker'] == fund['ticker']]
        for metric in metric_labels(config):
            run['results'].append(resolve_metric(run['candidates'], fund, metric, config, retrieval_errors=errors))
        for period in run['quarters']:
            run['nav_history'].append(resolve_metric(run['candidates'], fund, 'nav', config, exact_period=period, retrieval_errors=errors))
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(description='Auditable SEC benchmarking; no synthetic competitor fallback.')
    parser.add_argument('--retry-unfinished',action='store_true',help='Explicitly retry unfinished AI cells in addition to configuration changes')
    parser.add_argument('--render-audit',type=Path,help='Generate reports from saved decisions only; no source or AI calls')
    parser.add_argument('--from-audit', type=Path, help='Update only changed metrics/funds against a saved audit; preserve other decisions')
    parser.add_argument('--llm', choices=['on', 'cached', 'off'], default='on',
                        help='Model judgment (default), cache-only replay, or explicitly labeled parser-only review')
    parser.add_argument('--review-concurrency',type=int,default=3,choices=range(1,5),help='Maximum independent AI reviews (1–4; default 3)')
    parser.add_argument('--model', help='Override OPENAI_MODEL for judgment')
    parser.add_argument('--config', type=Path, default=Path('config/engagement.json'))
    parser.add_argument('--apex-data', type=Path, default=Path('data/apex_ridge_fund_data.csv'))
    parser.add_argument('--cache', type=Path, default=Path('.cache/sec'))
    parser.add_argument('--output', type=Path, default=Path('output/latest'))
    parser.add_argument('--decisions', type=Path, help='Reviewed candidate decisions JSON; see docs/review-workflow.md')
    parser.add_argument('--ocr', choices=['auto', 'always', 'off'], default='auto',
                        help='OCR sparse-text PDF pages automatically, every page, or disable with explicit gap flags')
    parser.add_argument('--offline', action='store_true', help='Use previously downloaded real SEC responses only')
    parser.add_argument('--refresh', action='store_true', help='Recheck SEC responses instead of using URL cache')
    args = parser.parse_args(argv)
    if args.render_audit:
        export(json.loads(args.render_audit.read_text()),args.output)
        return 0
    if args.from_audit and args.refresh:
        parser.error('--refresh requires fresh source discovery; omit --from-audit')
    if args.offline and args.refresh:
        parser.error('--offline and --refresh cannot be combined')
    from dotenv import load_dotenv
    load_dotenv(Path('.env'), override=False)
    if args.offline and args.llm == 'on':
        parser.error('--offline requires --llm cached or --llm off; no model network calls in offline mode')
    ua = os.environ.get('SEC_USER_AGENT', '')
    if not ua and not args.offline and not args.from_audit:
        parser.error('Set SEC_USER_AGENT to your app name and real contact email; see README.')
    started=time.perf_counter()
    timings={}
    try:
        config = json.loads(args.config.read_text())
        decisions = json.loads(args.decisions.read_text()) if args.decisions else []
        judge = None
        if args.llm != 'off':
            from .judgment import NumberedJudge
            judge = NumberedJudge(os.environ.get('OPENAI_API_KEY'), args.model or os.environ.get('OPENAI_MODEL', 'gpt-5.4'),
                                args.cache / 'judgments', offline=args.llm=='cached')
        print('Stage: source preparation',flush=True)
        source_started=time.perf_counter()
        affected=None
        if args.from_audit:
            run = json.loads(args.from_audit.read_text())
            from .incremental import prepare
            validate_config(config)
            def pull_funds(funds):
                client=SecClient(ua or 'offline-cache-only',args.cache,args.offline,args.refresh)
                return run_pipeline(dict(config,funds=funds),client,args.apex_data,decisions,ocr_mode=args.ocr)
            if decisions:
                raise ValueError('Explicit manual decisions require a source rebuild; omit --from-audit.')
            print('Reusing saved decisions; retrieving evidence only for changed dependencies',flush=True)
            affected=prepare(run,config,args.cache,pull_funds=pull_funds)
            run['reprocessed_from_run_id'] = run['run_id']
            run['source_run_mode'] = run.get('source_run_mode', run['mode'])
            run['mode'] = 'reprocessed_audit'
            run['generated_at'] = datetime.now(timezone.utc).isoformat()
            run['run_id'] = hashlib.sha256(run['generated_at'].encode()).hexdigest()[:16]
            run['apex'] = internal_data(args.apex_data, config)
        else:
            client = SecClient(ua or 'offline-cache-only', args.cache, args.offline, args.refresh)
            run = run_pipeline(config, client, args.apex_data, decisions, ocr_mode=args.ocr)
        if args.retry_unfinished and affected is not None:
            affected.update((r['ticker'],r['metric'],r['period'] if history else None)
                for history,items in ((False,run['results']),(True,run['nav_history'])) for r in items
                if r.get('decision_author','rules_only') in {'llm_not_completed','rules_only'})
        timings['source_preparation_seconds']=round(time.perf_counter()-source_started,3)
        print('Stage: AI review',flush=True)
        review_started=time.perf_counter()
        if judge:
            from .judgment import adjudicate_run
            adjudicate_run(run, judge, args.cache, concurrency=args.review_concurrency, affected=affected)
        else:
            run['judgment_mode'] = 'rules_only' if affected is None else 'saved_decisions_with_rules_only_updates'
            if affected is None:
                run.pop('llm_judgments', None)
                run.pop('rule_results', None)
                run.pop('rule_nav_history', None)
        timings['ai_review_seconds']=round(time.perf_counter()-review_started,3)
        print('Stage: report generation',flush=True)
        export_started=time.perf_counter()
        from .evidence import migrate_evidence_contract
        migrate_evidence_contract(run)
        export(run, args.output)
        timings['report_generation_seconds']=round(time.perf_counter()-export_started,3)
        timings['total_seconds']=round(time.perf_counter()-started,3)
        timings['source_mode']='saved_audit' if args.from_audit else run['mode']
        timings['review_mode']=run['judgment_mode']
        timings['incremental']=run.get('incremental',{})
        timings['model_network_responses']=sum(not p.get('cache_hit',True) for j in run.get('llm_judgments',[]) for p in [j.get('provenance',{}),j.get('initial_attempt',{}).get('provenance',{})])
        if 'model_network_responses' in run.get('incremental',{}):timings['model_network_responses']=run['incremental']['model_network_responses']
        (args.output/'timings.json').write_text(json.dumps(timings,indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    counts = {}
    for result in run['results']:
        counts[result['status']] = counts.get(result['status'], 0) + 1
    print(json.dumps({'output': str(args.output.resolve()), 'statuses': counts,
        'retrieval_errors': sum(e['stage'] not in {'ocr', 'parse'} for e in run['errors']),
        'extraction_errors': sum(e['stage'] in {'ocr', 'parse'} for e in run['errors']), 'apex': run['apex']['status'],
        'judgment_mode': run.get('judgment_mode'),
        'llm_decisions_accepted': sum(j.get('validation')=='passed' for j in run.get('llm_judgments', [])),
        'llm_decisions_not_completed': sum(j.get('validation')=='not_accepted' for j in run.get('llm_judgments', []))}, indent=2))
    return 2 if run['errors'] or any(j.get('validation')=='not_accepted' for j in run.get('llm_judgments', [])) else 0


if __name__ == '__main__':
    sys.exit(main())
