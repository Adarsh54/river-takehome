import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_judgment import run, RESULT, C
from test_scope import CONFIG,F,FILING
from apex_benchmark.judgment import build_packet
from apex_benchmark.passages import document_passages,expand_candidate
from apex_benchmark.evidence import evidence_label
from apex_benchmark.refresh import refresh_saved


def test_history_has_its_own_measurement_target():
    r=run();r['candidates']=[dict(C,period='2024-06-30')]
    p=build_packet(r,dict(RESULT,requested_period='2024-06-30'))
    assert p['target_period']==p['requested_period']=='2024-06-30'
    assert p['measurement_request']=='Historical observation exactly at 2024-06-30'
    current=build_packet(r,RESULT)
    assert 'earlier disclosed periods are valid' in current['measurement_request']


def test_context_recovers_headers_rows_and_class_without_reparsing(tmp_path,monkeypatch):
    body=b'<h2>Class I</h2><table><tr><th>Year ended</th><th>June 30, 2024</th><th>June 30, 2023</th></tr><tr><td>NAV per share</td><td>8.58</td><td>8.24</td></tr></table>'
    digest=hashlib.sha256(body).hexdigest();(tmp_path/digest).write_bytes(body)
    document_passages(tmp_path,digest)
    monkeypatch.setattr('apex_benchmark.passages.parse_passages',lambda b:pytest.fail('Reparsed unchanged document'))
    c=dict(C,source_sha256=digest,quote='NAV per share 8.58 8.24')
    x=expand_candidate(c,tmp_path)
    assert 'June 30, 2024' in x['quote'] and x['table_rows'][1][1][1]=='8.58'
    assert x['section_headings']==['Class I'] and x['parent_candidate_id']==c['id']
    assert c['quote']=='NAV per share 8.58 8.24'


@pytest.mark.parametrize('author,reason,label',[
 ('llm_not_completed','No matching cached LLM judgment; no network call made.','AI review pending'),
 ('llm_not_completed','Citation validation failed','AI review failed'),
 ('llm_not_completed','No retrieved passages available for model assessment.','Evidence not found'),
 ('llm','Only origination spread is disclosed in these passages.','Reviewed — value not established'),
])
def test_gap_labels_do_not_claim_nondisclosure(author,reason,label):
    assert evidence_label(dict(RESULT,decision_author=author,reason=reason))==label


def refresh_fixture():
    r=run();r['config']=dict(CONFIG,funds=[F]);r.update(filings=[copy.deepcopy(FILING)],documents=[],nport_reports=[],extraction_diagnostics=[],quarters=['2024-12-31'],llm_judgments=[])
    return r


def test_unchanged_inventory_does_not_ingest_parse_or_review(tmp_path,monkeypatch):
    r=refresh_fixture();before=copy.deepcopy(r['results'])
    monkeypatch.setattr('apex_benchmark.refresh.discover',lambda *a:[FILING])
    monkeypatch.setattr('apex_benchmark.refresh.derive_report_metrics',lambda *a:pytest.fail('Unneeded extraction'))
    def pull(*a):pytest.fail('Unchanged filing was pulled')
    affected=refresh_saved(r,r['config'],SimpleNamespace(cache=tmp_path,refresh=False),None,pull,progress=lambda *a,**k:None)
    assert not affected and r['results']==before
    assert r['incremental']['unchanged_filings_reused']==1


def test_only_new_accession_is_ingested(tmp_path,monkeypatch):
    r=refresh_fixture();new=dict(FILING,accessionNumber='new',filingDate='2025-02-20')
    monkeypatch.setattr('apex_benchmark.refresh.discover',lambda *a:[new,FILING])
    monkeypatch.setattr('apex_benchmark.refresh.derive_report_metrics',lambda *a:[])
    monkeypatch.setattr('apex_benchmark.refresh.qualify_disclosures',lambda *a:[])
    monkeypatch.setattr('apex_benchmark.refresh.internal_data',lambda *a:{'status':'withheld','values':{}})
    calls=[]
    def pull(funds,selection):
        calls.append(selection)
        return {'candidates':[dict(C,accession='new',filing_date='2025-02-20')],'documents':[],'errors':[]}
    affected=refresh_saved(r,r['config'],SimpleNamespace(cache=tmp_path,refresh=False),None,pull,progress=lambda *a,**k:None)
    assert calls==[{'TEST':[new]}]
    assert ('TEST','management_fee',None) in affected
    assert r['incremental']['new_or_changed_filings']==1


def test_provider_failure_exports_gaps_instead_of_crashing_workers(tmp_path):
    from apex_benchmark.judgment import adjudicate_run,ProviderError
    from test_judgment import BODY,HASH
    (tmp_path/HASH).write_bytes(BODY)
    r=run();r['results']=[dict(RESULT,ticker=f'T{i}') for i in range(8)]
    r['config']['funds']=[dict(r['config']['funds'][0],ticker=f'T{i}') for i in range(8)]
    r['candidates']=[dict(C,ticker=f'T{i}') for i in range(8)]
    class Down:
        offline=False
        def judge(self,p):raise ProviderError('LLM API HTTP 401 (test)')
    adjudicate_run(r,Down(),tmp_path,concurrency=2,progress=lambda *a,**k:None)
    assert len(r['llm_judgments'])==8 and all(x['value'] is None for x in r['results'])
    assert list((tmp_path/'decisions/failures').glob('*.json'))


def test_explicit_table_date_can_resolve_unqualified_parser_period():
    from test_judgment import packet,decision
    from apex_benchmark.judgment import validate_decision,JudgmentError
    p=packet();p['evidence'][0]['period']='';d=decision()
    assert validate_decision(d,p)
    d['period']='2024-09-30'
    with pytest.raises(JudgmentError,match='reporting date'):validate_decision(d,p)


def test_changed_filing_does_not_reopen_other_metrics(tmp_path,monkeypatch):
    from apex_benchmark.resolve import resolve_metric,quarter_ends
    from apex_benchmark.metrics import metric_labels
    r=refresh_fixture();r['results']=[resolve_metric(r['candidates'],F,m,r['config']) for m in metric_labels(r['config'])]
    r['nav_history']=[resolve_metric(r['candidates'],F,'nav',r['config'],exact_period=p) for p in quarter_ends(r['config']['target_period'],8)]
    new=dict(FILING,accessionNumber='new',filingDate='2025-02-20')
    monkeypatch.setattr('apex_benchmark.refresh.discover',lambda *a:[new,FILING])
    monkeypatch.setattr('apex_benchmark.refresh.derive_report_metrics',lambda *a:[])
    monkeypatch.setattr('apex_benchmark.refresh.qualify_disclosures',lambda *a:[])
    monkeypatch.setattr('apex_benchmark.refresh.internal_data',lambda *a:{'status':'withheld','values':{}})
    old_history=copy.deepcopy(r['nav_history'])
    def pull(*args):return {'candidates':[dict(C,id='amended',accession='new',filing_date='2025-02-20')],'documents':[],'errors':[]}
    affected=refresh_saved(r,r['config'],SimpleNamespace(cache=tmp_path,refresh=False),None,pull,progress=lambda *a,**k:None)
    assert affected=={('TEST','management_fee',None)}
    assert r['nav_history']==old_history


def test_percentage_footnotes_and_prose_parentheses_do_not_change_values():
    from apex_benchmark.judgment import numeric_tokens
    from apex_benchmark.extract import number
    assert [number(x) for x in numeric_tokens('Annualized hurdle of 6.00%).')]==[6.0]
    assert [number(x) for x in numeric_tokens('Dividend yield 11.3%5')]==[11.3,5]
    assert [number(x) for x in numeric_tokens('Loss ($0.11); return (0.79%)')]==[-.11,-.79]


def test_history_excludes_undated_other_filings_but_keeps_same_filing_context():
    r=run();r['candidates']=[dict(C,period='2024-06-30'),dict(C,id='context',period='',quote='The share class is Common.'),dict(C,id='boilerplate',accession='other',period='',quote='Illustrative examples of dilution.')]
    p=build_packet(r,dict(RESULT,requested_period='2024-06-30'))
    assert {c['id'] for c in p['evidence']}=={'source1','context'}
    assert p['excluded_undated_unrelated_passages']==1


def test_nav_retrieval_distinguishes_actual_observations_from_dilution_examples():
    from apex_benchmark.judgment import nav_observation_candidate
    assert nav_observation_candidate(dict(C,quote='Net asset value per share $19.77 $19.24'))
    assert not nav_observation_candidate(dict(C,quote='The following chart illustrates hypothetical net asset value per share of $20.00.'))
    assert not nav_observation_candidate(dict(C,quote='The fund calculates net asset value per share daily.'))
    assert nav_observation_candidate(dict(C,eligible=True,quote='19.77'))


def test_trailing_return_contract_does_not_require_current_quarter_end():
    packet=build_packet(run(),dict(RESULT,metric='return_1y'))
    assert 'trailing 1-year return' in packet['measurement_request']
    assert 'later three-month return is a different metric' in packet['measurement_request']


def test_bare_xbrl_number_is_not_attached_to_arbitrary_table(tmp_path):
    c=dict(C,quote='12.50')
    assert expand_candidate(c,tmp_path) is c


def test_incentive_fee_cannot_be_labeled_as_hurdle():
    from test_judgment import decision,packet
    from apex_benchmark.judgment import validate_decision,JudgmentError
    p=packet();p['metric']='incentive_fee'
    d=decision();d['basis']='contractual:quarterly_hurdle_rate'
    with pytest.raises(JudgmentError,match='Incentive fee cannot'):
        validate_decision(d,p)


def test_quarterly_rate_is_visible_in_comparison_cell():
    from apex_benchmark.report import display
    from apex_benchmark.word_report import value
    r=dict(RESULT,value=1.75,unit='%',basis='quarterly hurdle')
    assert '/ quarter' in display(r) and '/ quarter' in value(r)


def test_annualized_quarterly_input_is_not_displayed_as_quarterly():
    from apex_benchmark.report import display
    from apex_benchmark.word_report import value
    r=dict(RESULT,value=8,unit='%',basis='annualized:quarterly_net_assets_hurdle')
    assert '/ quarter' not in display(r) and '/ quarter' not in value(r)
