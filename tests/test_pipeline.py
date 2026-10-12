"""Synthetic unit fixtures only; never used as competitor output."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from apex_benchmark.sec import SecClient, RetrievalError, discover, select_filings
from apex_benchmark.extract import parse_document, documents_from_submission, number
from apex_benchmark.resolve import resolve_metric, apply_decisions, internal_data, quarter_ends
from apex_benchmark.cli import run_pipeline, validate_config
from apex_benchmark.report import export

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config/engagement.json').read_text())
FUND = CONFIG['funds'][2]
FILING = {'filingDate': '2025-02-10', 'reportDate': '2024-12-31', 'form': '10-Q',
          'accessionNumber': '0000000000-25-000001', 'primaryDocument': 'test.htm'}
SOURCE = {'url': 'https://www.sec.gov/Archives/test.htm', 'sha256': 'test-only'}


def nav_doc(value='15.25', context_extra='', unit='iso4217:USD', scale='0'):
    return f'''<html><body><xbrli:context id="c"><xbrli:entity>{context_extra}</xbrli:entity><xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period></xbrli:context>
    <xbrli:unit id="u"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>{unit}</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
    <table><tr><td>NAV per common share</td><td><ix:nonFraction id="f1" name="us-gaap:NetAssetValuePerShare" contextRef="c" unitRef="u" scale="{scale}">{value}</ix:nonFraction></td></tr></table></body></html>'''.encode()


def nav_candidate():
    return next(c.dict() for c in parse_document(nav_doc(), FUND, FILING, SOURCE) if c.method == 'inline_xbrl')


def test_xbrl_exact_units_period_and_locator():
    c = nav_candidate()
    assert c['value'] == 15.25 and c['eligible']
    assert c['period'] == '2024-12-31' and 'context=c' in c['locator']
    assert '15.25' in c['quote']
    r = resolve_metric([c], FUND, 'nav', CONFIG)
    assert r['value'] == 15.25 and r['confidence'] == 'medium'


@pytest.mark.parametrize('kwargs', [{'unit':'iso4217:EUR'}, {'context_extra':'<xbrldi:explicitMember>PreferredStock</xbrldi:explicitMember>'}])
def test_ambiguous_units_or_dimensions_not_published(kwargs):
    c = next(c for c in parse_document(nav_doc(**kwargs), FUND, FILING, SOURCE) if c.method == 'inline_xbrl')
    assert not c.eligible


def test_interval_class_requires_review():
    c = next(c for c in parse_document(nav_doc(), CONFIG['funds'][0], FILING, SOURCE) if c.method == 'inline_xbrl')
    assert not c.eligible


def test_scale_and_parentheses():
    c = next(c for c in parse_document(nav_doc('1525', scale='-2'), FUND, FILING, SOURCE) if c.method == 'inline_xbrl')
    assert c.value == 15.25
    assert number('(2.50)') == -2.5
    assert number('NaN') is None


def test_future_filings_and_periods_excluded():
    c = nav_candidate()
    c['filing_date'] = '2025-03-01'
    assert resolve_metric([c], FUND, 'nav', CONFIG)['value'] is None
    c['filing_date'] = '2025-02-10'
    c['period'] = '2025-01-31'
    assert resolve_metric([c], FUND, 'nav', CONFIG)['value'] is None


def test_conflicting_same_period_values_withheld():
    a, b = nav_candidate(), nav_candidate()
    b.update(value=15.5, accession='amendment', filing_date='2025-02-20', id='other')
    r = resolve_metric([a,b], FUND, 'nav', CONFIG)
    assert r['status'] == 'conflict' and r['value'] is None


def test_retrieval_failure_does_not_silently_use_existing_value():
    r = resolve_metric([nav_candidate()], FUND, 'nav', CONFIG, retrieval_errors=['blocked'])
    assert r['status'] == 'retrieval_incomplete' and r['value'] is None


def test_wrong_return_basis_rejected():
    c = nav_candidate()
    c.update(metric='return_1y', basis='net_nav')
    assert resolve_metric([c], FUND, 'return_1y', CONFIG)['value'] is None


def test_fee_rule_keeps_waiver_expiration_and_requires_review():
    body = b'<p>The management fee is 1.25% of gross assets. A temporary waiver expires December 31, 2025.</p>'
    candidates = parse_document(body, FUND, FILING, SOURCE)
    c = next(c for c in candidates if c.metric == 'management_fee')
    assert c.value == 1.25 and not c.eligible and 'expires December 31, 2025' in c.quote


def test_evidence_anchored_review():
    c = nav_candidate()
    decision = {'candidate_id':c['id'], 'action':'accept', 'reviewer':'Test reviewer', 'reason':'Checked source',
                'value':15.25, 'unit':'USD/share', 'period':'2024-12-31', 'basis':'nav', 'share_class':'Common', 'evidence_text':'15.25'}
    apply_decisions([c], [decision], '2025-02-28')
    assert c['review']['reviewer'] == 'Test reviewer'
    decision['value'] = 999
    with pytest.raises(ValueError, match='number must be present'):
        apply_decisions([c], [decision], '2025-02-28')
    decision['value'], decision['evidence_text'] = 15.25, 'fabricated 15.25'
    with pytest.raises(ValueError, match='verbatim'):
        apply_decisions([c], [decision], '2025-02-28')


def test_historical_discovery_cutoff_and_dedup():
    class Client:
        def json(self, url):
            if 'older.json' in url:
                return {'accessionNumber':['old'], 'filingDate':['2025-02-28'], 'form':['10-K']}
            return {'filings': {'recent': {'accessionNumber':['future'], 'filingDate':['2026-01-01'], 'form':['10-K']},
                               'files':[{'name':'older.json', 'filingFrom':'2024-01-01', 'filingTo':'2025-12-31'}]}}
    found = discover(Client(), '1', '2025-02-28')
    assert len(found) == 1 and found[0]['accessionNumber'] == 'old'


def test_all_supplements_retained_not_top_n():
    rows = [dict(FILING, form='497', accessionNumber=str(i)) for i in range(25)]
    assert len(select_filings(rows, '2024-12-31')) == 25


def test_exhibits_are_parsed():
    body = b'<DOCUMENT>\n<FILENAME>ex99.htm\n<TEXT><p>annual report</p></TEXT></DOCUMENT>'
    docs = documents_from_submission(body, 'https://www.sec.gov/Archives/x/primary.htm')
    assert docs[0][0].endswith('/ex99.htm') and b'annual report' in docs[0][1]


def test_internal_data_is_gated_and_future_rows_excluded():
    path = ROOT / 'data/apex_ridge_fund_data.csv'
    assert internal_data(path, CONFIG)['values'] == {}
    cfg = dict(CONFIG, apex_data_approved=True)
    with pytest.raises(ValueError, match='approver'):
        internal_data(path, cfg)
    cfg.update(apex_approved_by='Test only', apex_approval_note='Synthetic approval for unit testing only')
    result = internal_data(path, cfg)
    assert len(result['nav_history']) == 4
    assert result['values']['nav']['period'] == '2024-12-31'
    assert result['values']['nav']['value'] == 25.42


def test_quarters_no_future_leak():
    quarters = quarter_ends('2024-12-31',8)
    assert quarters[0] == '2023-03-31' and quarters[-1] == '2024-12-31'


def test_cache_integrity_and_offline_no_network(tmp_path):
    client = SecClient('unit-test', tmp_path, offline=True)
    url = 'https://data.sec.gov/submissions/CIK0000000001.json'
    with pytest.raises(RetrievalError, match='No cached'):
        client.get(url)
    key = hashlib.sha256(url.encode()).hexdigest()
    (tmp_path/f'{key}.json').write_text(json.dumps({'sha256':'bad'}))
    (tmp_path/'bad').write_bytes(b'modified')
    with pytest.raises(RetrievalError, match='checksum'):
        client.get(url)


def test_full_failure_run_exports_honest_report(tmp_path):
    class BlockedClient:
        offline = False
        refresh = True
        def json(self, url):
            raise RetrievalError('HTTP 403 synthetic test response')
    run = run_pipeline(CONFIG, BlockedClient(), ROOT/'data/apex_ridge_fund_data.csv', progress=lambda *a,**k:None)
    export(run, tmp_path)
    assert len(run['results']) == 40
    assert all(r['value'] is None and r['status']=='retrieval_incomplete' for r in run['results'])
    assert 'synthetic test response' in (tmp_path/'index.html').read_text()
    from pypdf import PdfReader
    pdftext = ' '.join(p.extract_text() for p in PdfReader(tmp_path/'benchmark.pdf').pages)
    assert 'REVIEW DRAFT' in pdftext and '25.42' not in pdftext
    assert (tmp_path/'benchmark.csv').exists()


def test_explicit_shareholder_return_table_and_annualization():
    body = b'''<table><caption>Average annual returns as of December 31, 2024; distributions reinvested</caption>
    <tr><th>Return basis</th><th>1 year</th><th>3 years</th><th>5 years</th></tr>
    <tr><td>Common stock total shareholder return</td><td>8.0%</td><td>7.2%</td><td>6.1%</td></tr></table>'''
    found = [c.dict() for c in parse_document(body, FUND, FILING, SOURCE)]
    result = resolve_metric(found, FUND, 'return_3y', CONFIG)
    assert result['value'] == 7.2 and result['basis'] == 'shareholder'
    bad = body.replace(b'Average annual', b'Cumulative')
    found = [c.dict() for c in parse_document(bad, FUND, FILING, SOURCE)]
    assert resolve_metric(found, FUND, 'return_3y', CONFIG)['value'] is None
