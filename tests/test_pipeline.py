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
    assert r['value'] == 15.25 and r['has_verifiable_evidence'] and r['directly_reported']


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


def test_internal_data_is_automatic_and_future_rows_excluded():
    path = ROOT / 'data/apex_ridge_fund_data.csv'
    for cfg in (CONFIG, dict(CONFIG, apex_data_approved=False, apex_approved_by=None, apex_approval_note=None),
                {k:v for k,v in CONFIG.items() if not k.startswith('apex_')}):
        result = internal_data(path, cfg)
        assert len(result['nav_history']) == 4
        assert result['values']['nav']['period'] == '2024-12-31'
        assert result['values']['nav']['value'] == 25.42
        assert result['values']['return_1y']['value'] == 10.34
    with pytest.raises(ValueError, match='no row for target quarter'):
        internal_data(path, dict(CONFIG, target_period='2023-12-31'))


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
    run = run_pipeline(dict(CONFIG, apex_data_approved=False), BlockedClient(), ROOT/'data/apex_ridge_fund_data.csv', progress=lambda *a,**k:None)
    export(run, tmp_path)
    assert len(run['results']) == 40
    assert all(r['value'] is None and r['status']=='retrieval_incomplete' for r in run['results'])
    assert 'synthetic test response' in (tmp_path/'index.html').read_text()
    from pypdf import PdfReader
    pdftext = ' '.join(p.extract_text() for p in PdfReader(tmp_path/'benchmark.pdf').pages)
    assert 'REVIEW DRAFT' in pdftext and '25.42' in pdftext
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


def test_export_history_anchors_and_approved_internal_values(tmp_path):
    class NoAccess:
        offline = True
        refresh = False
        def json(self, url):
            raise RetrievalError('Test fixture: no sources')
    cfg = dict(CONFIG, apex_data_approved=True, apex_approved_by='Unit test', apex_approval_note='Test approval only')
    run = run_pipeline(cfg, NoAccess(), ROOT/'data/apex_ridge_fund_data.csv', progress=lambda *a,**k:None)
    c = nav_candidate()
    r = resolve_metric([c], FUND, 'nav', cfg)
    run['results'] = [r if x['ticker']=='GBDC' and x['metric']=='nav' else x for x in run['results']]
    run['nav_history'] = [r if x['ticker']=='GBDC' and x['period']=='2024-12-31' else x for x in run['nav_history']]
    export(run, tmp_path)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup((tmp_path/'index.html').read_text(), 'html.parser')
    ids = [n['id'] for n in soup.select('[id]')]
    assert len(ids) == len(set(ids))
    assert soup.select_one('#GBDC-nav') and soup.select_one('#GBDC-nav-2024-12-31')
    assert '15.25' in soup.select_one('#GBDC-nav-2024-12-31').get_text()
    assert 'Apex Ridge approved history' in soup.get_text()
    assert 'APEX,nav,25.42' in (tmp_path/'benchmark.csv').read_text()


def test_nport_transformation_path_is_not_submission_directory():
    from apex_benchmark.sec import filing_documents
    filing = dict(FILING, primaryDocument='xslFormNPORT-P_X01/primary_doc.xml')
    primary, complete = filing_documents(None, '1725472', filing)
    assert '/xslForm' not in primary and '/xslForm' not in complete
    assert primary.endswith('/primary_doc.xml')
    assert complete.endswith('/000000000025000001/0000000000-25-000001.txt')


def test_machine_xml_is_not_treated_as_narrative():
    xml = b'<xbrl><label>Management fee</label><fact>1.25%</fact></xbrl>'
    assert parse_document(xml, FUND, FILING, dict(SOURCE, url='https://www.sec.gov/instance.xml')) == []


def test_http_status_is_not_inferred_from_accession_text():
    missing = RetrievalError('HTTP 404: https://www.sec.gov/24035041.txt', status_code=404)
    denied = RetrievalError('Access denied', status_code=403)
    assert missing.status_code == 404 and denied.status_code == 403


def test_book_value_columns_follow_explicit_dates():
    body = b'''<table><tr><td colspan="2"></td><td colspan="2">December 31, 2023</td><td colspan="2">December 31, 2024</td></tr>
    <tr><td colspan="6">Common stockholders' equity</td></tr>
    <tr><td colspan="2">Book value per share</td><td>$</td><td>15.52</td><td>$</td><td>14.76</td></tr></table>'''
    cs = [c for c in parse_document(body, CONFIG['funds'][3], FILING, SOURCE) if c.method=='dated_per_share_table']
    assert {(c.period,c.value) for c in cs} == {('2023-12-31',15.52),('2024-12-31',14.76)}


def test_unknown_narrative_basis_flags_review_without_fabricating_conflict():
    a=nav_candidate()
    other=dict(a,id='unscoped',eligible=False,basis='unconfirmed',value=99,filing_date='2025-02-20')
    r=resolve_metric([a,other],FUND,'nav',CONFIG)
    assert r['value']==15.25 and r['status']=='supported_with_review'
    assert r['unresolved_candidate_ids']==['unscoped']
    other.update(basis='nav')
    assert resolve_metric([a,other],FUND,'nav',CONFIG)['value'] is None


def test_identical_passages_in_different_filings_keep_distinct_provenance():
    first=next(c for c in parse_document(nav_doc(),FUND,FILING,SOURCE) if c.method=='inline_xbrl')
    amended=dict(FILING,accessionNumber='0000000000-25-000002',filingDate='2025-02-20')
    second=next(c for c in parse_document(nav_doc(),FUND,amended,SOURCE) if c.method=='inline_xbrl')
    assert first.id != second.id


def test_historical_observation_is_not_flagged_as_stale_current_data():
    c=nav_candidate();c['period']='2023-03-31'
    history=resolve_metric([c],FUND,'nav',CONFIG,exact_period='2023-03-31')
    latest=resolve_metric([c],FUND,'nav',CONFIG)
    assert history['lag_days']==0 and history['status']=='supported'
    assert latest['status']=='lagged'


def test_qualified_contract_rate_distinguishes_historical_fee_and_target_leverage():
    from apex_benchmark.normalize import qualify_disclosures
    c=nav_candidate()
    c.update(quote='The base management fee is calculated at an annual rate equal to 1.0 % (or 1.375 % for periods ending on or before June 30, 2023) of the fair value of the average adjusted gross assets of the Company.',metric='management_fee')
    fs=[dict(FILING,ticker='GBDC')]
    values=qualify_disclosures([c],fs,CONFIG)
    assert values[0]['value']==1.0 and values[0]['eligible']
    c.update(quote='We target a GAAP debt-to-equity ratio between 0.85x and 1.25x. Our asset coverage and GAAP debt-to-equity ratio was 180.8% and 1.24x, respectively.',metric='leverage')
    values=qualify_disclosures([c],fs,CONFIG)
    assert values[0]['value']==1.24


def test_quarterly_fee_annualization_keeps_minimum_and_formula():
    from apex_benchmark.normalize import qualify_disclosures
    c=nav_candidate();c.update(ticker='KREF',quote='The Manager is entitled to a quarterly management fee equal to the greater of $62,500 or 0.375% of weighted average adjusted equity.',metric='management_fee')
    values=qualify_disclosures([c],[dict(FILING,ticker='KREF')],CONFIG)
    assert values[0]['value']==1.5
    assert values[0]['calculation']['inputs']['quarterly_management_fee_pct']==0.375
    assert '$62,500' in values[0]['reasons'][0]


def test_distribution_selects_exact_class_not_first_rate():
    from apex_benchmark.normalize import qualify_disclosures
    c=nav_candidate();c.update(ticker='TAKIX',quote='The annualized distribution rates were Class A 9.5%, Class I 10.0%, Class L 9.5%.',metric='distribution_yield')
    values=qualify_disclosures([c],[dict(FILING,ticker='TAKIX',form='N-CSR')],CONFIG)
    assert values[0]['value']==10.0 and values[0]['share_class']=='Class I'


def test_annual_return_chain_compounds_instead_of_averaging():
    from apex_benchmark.structured_reports import annualized_return
    assert annualized_return([20,-20]) == pytest.approx(-2.0204102887)
    with pytest.raises(ValueError):annualized_return([-100])


def test_return_index_is_converted_to_percentage_with_reinvestment_evidence():
    from apex_benchmark.structured_reports import parse_financial_report
    body=b'''<p>The cumulative total stockholder return assumes all dividends are reinvested.</p>
    <table><tr><td></td><td>12/31/2019</td><td>12/31/2021</td><td>12/31/2023</td><td>12/31/2024</td></tr>
    <tr><td>KKR Real Estate Finance Trust, Inc.</td><td>100.0</td><td>123.0</td><td>99.5</td><td>83.7</td></tr></table>'''
    cs=parse_financial_report(body,CONFIG['funds'][3],dict(FILING,form='10-K'),SOURCE)
    current=next(c for c in cs if c['metric']=='return_1y')
    assert current['value']==pytest.approx((83.7/99.5-1)*100)
    assert current['basis']=='shareholder' and current['calculation']['inputs']['years']==1
    assert not parse_financial_report(body.replace(b'reinvested',b'paid in cash'),CONFIG['funds'][3],dict(FILING,form='10-K'),SOURCE)


def test_class_i_financial_highlights_preserve_negative_returns_and_nav():
    from apex_benchmark.structured_reports import parse_financial_report
    body=b'''<table><tr><td>CLASS I</td><td>2024</td><td>2023</td><td>2022</td></tr>
    <tr><td>Total Return, at Net Asset Value (2)</td><td>10.8%</td><td>14.15%</td><td>(0.79)%</td></tr>
    <tr><td>Net asset value, end of period</td><td>$8.55</td><td>$8.52</td><td>$8.28</td></tr></table>
    <p>Distributions are reinvested. Returns reflect net investment results.</p>'''
    cs=parse_financial_report(body,CONFIG['funds'][1],dict(FILING,form='N-CSR'),SOURCE)
    c=next(c for c in cs if c['metric']=='return_3y')
    assert c['value']==pytest.approx(((1.108*1.1415*0.9921)**(1/3)-1)*100)
    assert any(c['metric']=='nav' and c['period']=='2024-12-31' and c['value']==8.55 for c in cs)
    assert not parse_financial_report(body.replace(b'CLASS I',b'CLASS A'),CONFIG['funds'][1],dict(FILING,form='N-CSR'),SOURCE)


def test_rounded_summary_reconciles_to_precise_financial_highlights():
    c=nav_candidate();c.update(metric='return_1y',unit='%',basis='shareholder',value=15.77,reported_precision_pct=0.01)
    summary=dict(c,id='rounded',value=15.8,reported_precision_pct=0.1)
    r=resolve_metric([summary,c],FUND,'return_1y',CONFIG)
    assert r['value']==15.77 and 'rounding precision' in r['reason']
    summary['value']=16.0
    assert resolve_metric([summary,c],FUND,'return_1y',CONFIG)['status']=='conflict'


def test_interim_nav_uses_end_date_without_annualizing_transition_period():
    from apex_benchmark.structured_reports import parse_financial_report
    body=b'''<p>Consolidated Financial Highlights Class I</p><table>
    <tr><td></td><td>For the Six Months Ended September 30, 2024 (Unaudited)</td><td>For the Period January 1, 2022 through March 31, 2022</td></tr>
    <tr><td>Net asset value, end of period</td><td>$10.93</td><td>$10.79</td></tr>
    <tr><td>Total return</td><td>6.52%</td><td>1.79%</td></tr></table><p>Distributions are reinvested.</p>'''
    cs=parse_financial_report(body,CONFIG['funds'][0],dict(FILING,form='N-CSRS',reportDate='2024-09-30'),SOURCE)
    assert {(c['period'],c['value']) for c in cs}=={('2024-09-30',10.93),('2022-03-31',10.79)}
    assert all(c['metric']=='nav' for c in cs)
