import copy
import json
import pytest
from test_judgment import run,packet,decision,C,RESULT
from apex_benchmark.judgment import validate_decision,JudgmentError,NumberedJudge,OpenAIJudge
from apex_benchmark.incremental import prepare
from apex_benchmark.policy import snapshot,policy_for
from apex_benchmark.evidence import evidence_label


def conflict_fixture():
    p=packet();other=dict(C,id='source2',value=1.5,quote=C['quote'].replace('1.25','1.50'),filing_date='2025-02-20',accession='acc2')
    p['evidence'].append(other)
    d=decision();d.update(decision='withhold',selected_candidate_id=None,value=None,directly_reported=False,
        unresolved_conflict=True,conflict_candidates=[],rationale='Same fee, date and class; neither disclosure explains the difference.',unresolved_issues=['PM must resolve this discrepancy'])
    d['assessments'].append({'candidate_id':'source2','reason':'Newer filing gives a different figure without reconciliation.'})
    d['citations'].append({'candidate_id':'source2','quote':other['quote']})
    for c in p['evidence']:
        d['conflict_candidates'].append({k:c[k] for k in ['value','unit','period','basis','share_class']}|{'candidate_id':c['id'],'explanation':'Unreconciled contractual figure.'})
    return p,d


def test_unresolved_conflict_keeps_both_verified_sources():
    p,d=conflict_fixture();sources=validate_decision(d,p)
    assert len(sources)==2
    assert evidence_label(dict(RESULT,unresolved_conflict=True))=='Unresolved conflict — PM review required'
    assert 'newer filing alone' in policy_for({},'management_fee')['base']['instructions']


@pytest.mark.parametrize('mutation', ['publish','one','invented','different_class','different_basis','uncited','wrong_date'])
def test_conflict_cannot_accept_a_value_or_unverified_alternative(mutation):
    p,d=conflict_fixture()
    if mutation=='publish':d['decision']='publish'
    if mutation=='one':d['conflict_candidates'].pop()
    if mutation=='invented':d['conflict_candidates'][1]['value']=99
    if mutation=='different_class':d['conflict_candidates'][1]['share_class']='Class A'
    if mutation=='different_basis':d['conflict_candidates'][1]['basis']='effective:net_assets'
    if mutation=='uncited':d['citations'].pop()
    if mutation=='wrong_date':
        for x in d['conflict_candidates']:x['period']='2024-11-30'
    with pytest.raises(JudgmentError):validate_decision(d,p)


def test_numbered_conflict_figures_restore_source_ids(tmp_path,monkeypatch):
    p,d=conflict_fixture();raw=copy.deepcopy(d);raw.pop('selected_candidate_id');raw['selected_passage']=None
    raw['citations']=[1,2];raw['assessments']=[{'passage_number':i,'reason':'Conflict'} for i in [1,2]]
    for i,x in enumerate(raw['conflict_candidates'],1):x.pop('candidate_id');x['passage_number']=i
    monkeypatch.setattr(OpenAIJudge,'judge',lambda *a:(raw,{}))
    restored,_=NumberedJudge('fixture','fixture',tmp_path).judge(p)
    assert len(validate_decision(restored,p))==2


def test_fee_policy_changes_only_fee_without_retrieval(tmp_path,monkeypatch):
    r=run();r['results']+=[dict(RESULT,metric='return_1y')];r['nav_history']=[dict(RESULT,metric='nav',period='2024-09-30')]
    r['comparison_policy_snapshot']=snapshot(r['config'])
    others=copy.deepcopy([r['results'][1],r['nav_history'][0]])
    cfg=copy.deepcopy(r['config']);cfg['comparison_policies']={'management_fee':{'version':'2','instructions':'Preserve waiver expiration.'}}
    monkeypatch.setattr('apex_benchmark.incremental.augment_custom',lambda *a,**k:None)
    affected=prepare(r,cfg,tmp_path,pull_funds=lambda *a:pytest.fail('Fetched sources'))
    assert affected=={('TEST','management_fee',None)}
    assert [next(x for x in r['results'] if x['metric']=='return_1y'),r['nav_history'][0]]==others
    assert next(x for x in r['results'] if x['metric']=='management_fee')['value'] is None
    r['comparison_policy_snapshot']=snapshot(cfg)
    assert prepare(r,cfg,tmp_path)==set()


def test_stored_rule_version_change_is_detected(tmp_path,monkeypatch):
    r=run();r['comparison_policy_snapshot']=snapshot(r['config'])
    r['comparison_policy_snapshot']['management_fee']['base']['version']='old'
    monkeypatch.setattr('apex_benchmark.incremental.augment_custom',lambda *a,**k:None)
    assert prepare(r,r['config'],tmp_path)=={('TEST','management_fee',None)}


def test_conflict_survives_review_and_both_report_formats(tmp_path):
    from apex_benchmark.judgment import adjudicate_run
    from apex_benchmark.report import html_report
    from apex_benchmark.word_report import export_word
    from docx import Document
    import hashlib
    p,d=conflict_fixture();r=run();r['candidates']=copy.deepcopy(p['evidence'])
    for c in r['candidates']:
        c['ticker']='TEST';c.pop('review',None)
        body=c['quote'].encode();c['source_sha256']=hashlib.sha256(body).hexdigest();(tmp_path/c['source_sha256']).write_bytes(body)
    class Judge:
        offline=False
        calls=0
        def judge(self,p):self.calls+=1;return d,{}
    judge=Judge();adjudicate_run(r,judge,tmp_path,affected={('TEST','management_fee',None)})
    result=r['results'][0]
    assert result['status']=='conflict' and result['value'] is None and len(result['conflict_candidates'])==2
    assert judge.calls==1
    r['config']['funds'][0].update(name='TEST FIXTURE',cik='0000000000')
    r['apex']['nav_history']=[];r['quarters']=[];r['generated_at']='fixture';r['mode']='test';r['run_id']='test'
    from apex_benchmark.metrics import metric_labels
    for metric,label in metric_labels(r['config']).items():
        if metric!='management_fee':r['results'].append(dict(RESULT,metric=metric,label=label,comparability=''))
    r['apex']['reason']='TEST FIXTURE ONLY';r['documents']=[]
    page=html_report(r)
    assert 'Competing figures — neither accepted' in page and '1.25' in page and '1.5' in page and '2025-02-20' in page
    path=tmp_path/'conflict.docx';export_word(r,path)
    text='\n'.join(p.text for p in Document(path).paragraphs)
    assert 'Candidate 1.25 %' in text and 'Candidate 1.5 %' in text and 'Neither candidate is an accepted' in text
    assert 'word/_rels/document.xml.rels' in __import__('zipfile').ZipFile(path).namelist()


def test_effective_and_contractual_are_separate_not_a_conflict():
    p,d=conflict_fixture();d.update(decision='publish',selected_candidate_id='source1',value=1.25,directly_reported=True,
        unresolved_conflict=False,conflict_candidates=[],unresolved_issues=[],rationale='Contractual primary; effective waiver separately reported.')
    assert len(validate_decision(d,p))==2


def test_policy_snapshot_does_not_mutate_with_config():
    cfg={'comparison_policies':{'management_fee':{'version':'1','instructions':'First rule'}}}
    old=snapshot(cfg);cfg['comparison_policies']['management_fee']['version']='2'
    assert old['management_fee']['metric']['version']=='1'


def test_policy_only_refresh_does_not_rederive_documents(tmp_path,monkeypatch):
    from test_repair_refresh import refresh_fixture,FILING
    from apex_benchmark.refresh import refresh_saved
    from types import SimpleNamespace
    r=refresh_fixture();r['comparison_policy_snapshot']=snapshot(r['config'])
    cfg=copy.deepcopy(r['config']);cfg['comparison_policies']={'management_fee':{'version':'2','instructions':'Show waiver expiry.'}}
    monkeypatch.setattr('apex_benchmark.refresh.discover',lambda *a:[FILING])
    monkeypatch.setattr('apex_benchmark.refresh.derive_report_metrics',lambda *a:pytest.fail('Reparsed documents'))
    affected=refresh_saved(r,cfg,SimpleNamespace(cache=tmp_path,refresh=False),None,lambda *a:pytest.fail('Pulled filing'),progress=lambda *a,**k:None)
    assert affected=={('TEST','management_fee',None)} and r['incremental']['documents_parsed']==0


def test_nav_rule_changes_current_and_history_only(tmp_path,monkeypatch):
    r=run();r['results'].append(dict(RESULT,metric='nav'));r['nav_history']=[dict(RESULT,metric='nav',period='2024-09-30')]
    r['comparison_policy_snapshot']=snapshot(r['config'])
    cfg=copy.deepcopy(r['config']);cfg['comparison_policies']={'nav':{'version':'2','instructions':'Preserve share-class labels.'}}
    monkeypatch.setattr('apex_benchmark.incremental.augment_custom',lambda *a,**k:None)
    assert prepare(r,cfg,tmp_path)=={('TEST','nav',None),('TEST','nav','2024-09-30')}


def test_invalid_policy_cannot_be_silently_ignored():
    from apex_benchmark.policy import validate_policies
    with pytest.raises(ValueError):validate_policies({'comparison_policies':{'made_up':{'version':'1','instructions':'Rule'}}})
    with pytest.raises(ValueError):validate_policies({'comparison_policies':{'management_fee':{'instructions':'Rule'}}})


def test_fee_packet_keeps_older_prospectus_and_same_period_original():
    from apex_benchmark.judgment import build_packet
    r=run()
    r['filings']=[{'ticker':'TEST','form':form,'reportDate':'2024-12-31','filingDate':date,'accessionNumber':acc}
        for form,date,acc in [('10-K','2025-02-01','original'),('10-K/A','2025-02-20','amended')]]
    r['candidates']=[dict(C,id=acc,accession=acc,form=form,filing_date=date)
        for form,date,acc in [('10-K','2025-02-01','original'),('10-K/A','2025-02-20','amended'),('497','2024-07-01','prospectus')]]
    for c in r['candidates']:c['quote']+=' '+c['accession']
    p=build_packet(r,RESULT)
    assert {c['accession'] for c in p['evidence']}=={'original','amended','prospectus'}
