import copy
import hashlib
import json
import threading
import time
from pathlib import Path
import pytest
from apex_benchmark.passages import document_passages
from apex_benchmark.incremental import prepare
from apex_benchmark.judgment import NumberedJudge, JudgmentError, adjudicate_run, validate_decision
from test_judgment import run, decision, packet, BODY, HASH, RESULT, C
from test_scope import M, F, FILING, SOURCE, CONFIG


def test_index_is_metric_independent_and_does_not_reparse(tmp_path,monkeypatch):
    (tmp_path/HASH).write_bytes(BODY)
    first=document_passages(tmp_path,HASH)
    monkeypatch.setattr('apex_benchmark.passages.parse_passages',lambda b:pytest.fail('reparsed'))
    stats={}
    assert document_passages(tmp_path,HASH,stats)==first
    assert stats=={'document_index_hits':1}


def test_changed_metric_leaves_other_results_and_history_identical(tmp_path,monkeypatch):
    r=run();r['config']['custom_metrics']=[copy.deepcopy(M)]
    r.update(documents=[],run_id='old')
    unrelated=copy.deepcopy(r['results'])
    r['nav_history']=[dict(RESULT,metric='nav',period='2024-09-30')]
    history=copy.deepcopy(r['nav_history'])
    cfg=copy.deepcopy(r['config']);cfg['custom_metrics'][0]['definition']+=' New restriction.'
    affected=prepare(r,cfg,tmp_path)
    assert affected=={('TEST',M['id'],None)}
    assert r['results'][0]==unrelated[0] and r['nav_history']==history
    assert r['incremental']['documents_parsed']==0
    # Reordering definitions or pressing Run again invalidates nothing.
    assert prepare(r,copy.deepcopy(cfg),tmp_path)==set()


def test_bounded_concurrency_and_checkpoint_reuse(tmp_path):
    (tmp_path/HASH).write_bytes(BODY)
    r=run()
    r['results']=[dict(RESULT,ticker=f'T{i}') for i in range(6)]
    r['config']['funds']=[dict(r['config']['funds'][0],ticker=f'T{i}') for i in range(6)]
    r['candidates']=[dict(C,ticker=f'T{i}') for i in range(6)]
    class Judge:
        offline=False
        def __init__(self):self.active=0;self.peak=0;self.calls=0;self.lock=threading.Lock()
        def judge(self,p):
            with self.lock:self.active+=1;self.peak=max(self.peak,self.active);self.calls+=1
            time.sleep(.03)
            with self.lock:self.active-=1
            return decision(),{'cache_hit':False}
    j=Judge();adjudicate_run(r,j,tmp_path,concurrency=2,progress=lambda *a,**k:None)
    assert j.peak==2 and j.calls==6
    adjudicate_run(r,j,tmp_path,concurrency=2,progress=lambda *a,**k:None)
    assert j.calls==6 and r['incremental']['decision_checkpoint_hits']==6
    assert r['incremental']['model_network_responses']==0
    before=copy.deepcopy(r['results']);adjudicate_run(r,j,tmp_path,affected=set(),progress=lambda *a,**k:None)
    assert r['results']==before and j.calls==6


def numbered():
    d=decision();d.pop('selected_candidate_id');d.update(selected_passage=1,citations=[1],assessments=[{'passage_number':1,'reason':'Explicit stated fee.'}]);return d


def test_numbered_citations_are_restored_and_verified(tmp_path):
    class Session:
        def post(self,url,**kwargs):
            wire=json.loads(kwargs['json']['input'])
            assert wire['evidence'][0]['passage_number']==1 and 'id' not in wire['evidence'][0]
            class Response:
                status_code=200
                def json(self):return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(numbered())}]}]}
            return Response()
    judge=NumberedJudge('fixture','fixture',tmp_path,session=Session())
    d,_=judge.judge(packet())
    assert d['citations']==decision()['citations']
    assert validate_decision(d,packet())
    d['value']=88
    with pytest.raises(JudgmentError,match='absent'):validate_decision(d,packet())


def test_unknown_passage_is_never_accepted(tmp_path,monkeypatch):
    from apex_benchmark.judgment import OpenAIJudge
    d=numbered();d['citations']=[999]
    monkeypatch.setattr(OpenAIJudge,'judge',lambda *a:(d,{}))
    with pytest.raises(JudgmentError,match='Unknown numbered'):
        NumberedJudge('fixture','fixture',tmp_path).judge(packet())


def test_new_fund_only_pulls_new_fund(tmp_path):
    r=run();r.update(documents=[],llm_judgments=[])
    cfg=copy.deepcopy(r['config']);cfg['funds'].append(dict(cfg['funds'][0],ticker='NEW'))
    seen=[]
    def pull(funds):
        seen.extend(f['ticker'] for f in funds)
        return {'results':[dict(RESULT,ticker='NEW')],'nav_history':[dict(RESULT,ticker='NEW',metric='nav',period='2024-09-30')]}
    original=copy.deepcopy(r['results'][0]);affected=prepare(r,cfg,tmp_path,pull_funds=pull)
    assert seen==['NEW'] and r['results'][0]==original
    assert affected=={('NEW','management_fee',None),('NEW','nav','2024-09-30')}


def test_render_only_never_initializes_source_or_model(tmp_path,monkeypatch):
    from apex_benchmark import cli
    saved=tmp_path/'audit.json';saved.write_text(json.dumps(run()));exports=[]
    monkeypatch.setattr(cli,'export',lambda r,p:exports.append(r))
    monkeypatch.setattr(cli,'SecClient',lambda *a,**k:pytest.fail('source fetch'))
    monkeypatch.setattr('apex_benchmark.judgment.NumberedJudge',lambda *a,**k:pytest.fail('AI call'))
    assert cli.main(['--render-audit',str(saved),'--output',str(tmp_path/'rendered')])==0
    assert len(exports)==1
