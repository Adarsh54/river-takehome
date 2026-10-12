"""Transport fixtures are tests only; no fabricated LLM judgments in competitor reports."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from apex_benchmark.judgment import OpenAIJudge, JudgmentError, validate_decision, build_packet, adjudicate_run
from apex_benchmark.evidence import annotate_result, migrate_evidence_contract

BODY=b'The contractual management fee is 1.25% of net assets as of December 31, 2024.'
HASH=hashlib.sha256(BODY).hexdigest()
C={'id':'source1','ticker':'TEST','metric':'management_fee','value':1.25,'unit':'%',
   'period':'2024-12-31','basis':'contractual:net_assets','share_class':'Common',
   'filing_date':'2025-02-01','form':'10-K','accession':'acc','source_url':'https://www.sec.gov/example.htm',
   'source_sha256':HASH,'locator':'HTML block 2','quote':BODY.decode(),'method':'narrative_rule',
   'eligible':False,'reasons':['Interpretation required']}
FUND={'ticker':'TEST','share_class':'Common','structure':'bdc','return_basis':'shareholder'}
CONFIG={'funds':[FUND],'target_period':'2024-12-31','filing_cutoff':'2025-02-28'}
RESULT={'ticker':'TEST','metric':'management_fee','label':'Management fee','value':None,
        'period':'','sources':[],'unit':'%','basis':'','reason':'Needs interpretation','status':'needs_review'}


def run():
    return {'config':copy.deepcopy(CONFIG),'filings':[],'candidates':[copy.deepcopy(C)],
        'results':[copy.deepcopy(RESULT)],'nav_history':[],'errors':[],
        'apex':{'values':{},'status':'withheld'},'nport_reports':[]}


def decision():
    return {'decision':'publish','selected_candidate_id':'source1','value':1.25,'period':'2024-12-31',
            'unit':'%','basis':'contractual:net_assets','share_class':'Common','directly_reported':True,
            'rationale':'The passage states a contractual fee on net assets, with the matching reporting date.',
            'comparability':'Compare the fee basis as well as the percentage.','unresolved_issues':[],
            'citations':[{'candidate_id':'source1','quote':BODY.decode()}],
            'assessments':[{'candidate_id':'source1','reason':'Explicit contractual rate and basis.'}]}


def packet():
    return build_packet(run(),RESULT)


def test_llm_can_interpret_ineligible_parser_passage(tmp_path):
    (tmp_path/HASH).write_bytes(BODY)
    class Judge:
        offline=False
        def judge(self,p):return decision(),{'model':'test-double'}
    r=adjudicate_run(run(),Judge(),tmp_path,progress=lambda *a,**k:None)
    x=r['results'][0]
    assert x['value']==1.25 and x['has_verifiable_evidence'] and x['directly_reported']
    assert x['decision_author']=='llm' and 'confidence' not in x
    assert r['llm_judgments'][0]['evidence_considered'][0]['quote']==BODY.decode()
    assert r['rule_results'][0]['value'] is None


@pytest.mark.parametrize('mutate',[
    lambda d:d.update(value=9.99),
    lambda d:d['citations'][0].update(quote='Invented quote'),
    lambda d:d['citations'][0].update(candidate_id='invented'),
    lambda d:d.update(period='2025-01-01'),
    lambda d:d.update(unit='USD'),
    lambda d:d.update(basis='effective:waived'),
    lambda d:d.update(assessments=[]),
    lambda d:d.update(unresolved_issues=['Gross or net is uncertain']),
    lambda d:d.update(directly_reported=False),
    lambda d:d.update(value=float('nan')),
])
def test_invalid_model_choices_cannot_publish(mutate):
    d=decision(); mutate(d)
    with pytest.raises(JudgmentError):validate_decision(d,packet())


def test_real_conflict_requires_considering_both_sources():
    r=run();r['candidates'].append(dict(C,id='other',value=2.5,quote='The effective fee is 2.5%.'))
    p=build_packet(r,RESULT)
    with pytest.raises(JudgmentError,match='every supplied'):
        validate_decision(decision(),p)
    d=decision();d['assessments'].append({'candidate_id':'other','reason':'Effective fee has a different basis; contractual fee is requested.'})
    assert validate_decision(d,p)


def test_unknown_class_and_ocr_not_resolved_by_model_assertion():
    p=packet();p['evidence'][0]['method']='ocr_evidence'
    with pytest.raises(JudgmentError,match='visual'):
        validate_decision(decision(),p)
    p=packet();p['evidence'][0]['metric']='return_1y';p['fund']['return_basis']='shareholder'
    d=decision();d.update(basis='net_nav')
    with pytest.raises(JudgmentError,match='incompatible'):
        validate_decision(d,p)


def test_calculated_value_retains_formula_and_cannot_claim_direct():
    p=packet();p['evidence'][0].update(eligible=True,value=5,calculation={'expression':'quarterly_rate * 4','inputs':{'quarterly_rate':1.25},'output':5})
    d=decision();d.update(value=5,directly_reported=False)
    assert validate_decision(d,p)
    d['directly_reported']=True
    with pytest.raises(JudgmentError,match='calculated'):
        validate_decision(d,p)


def test_truncated_packet_withholds_and_missing_source_never_calls_model(tmp_path):
    p=packet();p['packet_complete']=False
    with pytest.raises(JudgmentError,match='truncated'):
        validate_decision(decision(),p)
    class Judge:
        offline=False
        def judge(self,p):raise AssertionError('Must verify source first')
    r=adjudicate_run(run(),Judge(),tmp_path,progress=lambda *a,**k:None)
    assert r['results'][0]['value'] is None and not r['results'][0]['has_verifiable_evidence']
    assert 'hash mismatch' in r['results'][0]['reason']


def test_withholding_keeps_rationale_and_no_fake_answer():
    d=decision();d.update(decision='withhold',selected_candidate_id=None,value=None,directly_reported=False,
                         unresolved_issues=['Rate period unclear'])
    assert validate_decision(d,packet())
    d['value']=1.25
    with pytest.raises(JudgmentError,match='Withheld'):
        validate_decision(d,packet())


class Session:
    def __init__(self,status='completed',content_type='output_text'):
        self.calls=[];self.status=status;self.content_type=content_type
    def post(self,url,**kwargs):
        self.calls.append((url,kwargs))
        owner=self
        class Response:
            status_code=200
            def json(self):return {'id':'response-test','model':'model-test','status':owner.status,
                'output':[{'type':'message','content':[{'type':owner.content_type,'text':json.dumps(decision())}]}]}
        return Response()


def test_responses_api_contract_cache_and_no_secret_or_client_data(tmp_path):
    s=Session();j=OpenAIJudge('test-secret','model-test',tmp_path,session=s)
    d,p=j.judge(packet())
    assert d==decision() and not p['cache_hit']
    _,args=s.calls[0]
    assert args['json']['store'] is False and args['json']['text']['format']['strict']
    assert 'apex' not in json.loads(args['json']['input'])
    assert 'test-secret' not in next(tmp_path.glob('*.json')).read_text()
    j=OpenAIJudge(None,'model-test',tmp_path,offline=True,session=s)
    assert j.judge(packet())[1]['cache_hit'] and len(s.calls)==1
    with pytest.raises(JudgmentError,match='cached'):
        OpenAIJudge(None,'different-model',tmp_path,offline=True,session=s).judge(packet())
    assert len(s.calls)==1


@pytest.mark.parametrize('status,content',[('incomplete','output_text'),('completed','refusal')])
def test_refusal_and_truncated_responses_not_accepted(tmp_path,status,content):
    with pytest.raises(JudgmentError):
        OpenAIJudge('test','model-test',tmp_path,session=Session(status,content)).judge(packet())
    assert not list(tmp_path.glob('*.json'))


def test_no_key_fails_before_request(tmp_path):
    with pytest.raises(JudgmentError,match='OPENAI_API_KEY'):
        OpenAIJudge(None,'model-test',tmp_path)


def test_no_ordinal_confidence_in_exports_and_calculation_not_direct():
    x=annotate_result(dict(RESULT,value=1.25,sources=[C],confidence='medium',calculation={'output':1.25}))
    assert x['has_verifiable_evidence'] and not x['directly_reported'] and 'confidence' not in x


def test_context_offsets_are_verbatim_and_future_filings_excluded():
    r=run();r['candidates']=[dict(C,quote='irrelevant '*1600+BODY.decode()+' irrelevant'*1600)]
    p=build_packet(r,RESULT)
    assert all(c['quote'] in r['candidates'][0]['quote'] for c in p['evidence'])
    assert p['evidence'][0]['parent_candidate_id']=='source1'
    r['candidates'][0]['filing_date']='2025-03-01'
    assert not build_packet(r,RESULT)['evidence']


def test_provider_failure_stops_repeated_requests_for_remaining_cells(tmp_path):
    from apex_benchmark.judgment import ProviderError
    (tmp_path/HASH).write_bytes(BODY)
    r=run();r['results'].append(copy.deepcopy(RESULT))
    class Judge:
        offline=False;calls=0
        def judge(self,p):
            self.calls+=1
            raise ProviderError('LLM API HTTP 401')
    j=Judge();adjudicate_run(r,j,tmp_path,progress=lambda *a,**k:None)
    assert j.calls==1
    assert all(x['value'] is None for x in r['results'])


def test_export_migration_removes_grades_but_keeps_ocr_recognition_scores():
    r=run();r['results'][0]['confidence']='medium'
    r['nport_reports']=[{'confidence_definition':'Old tiers','fields':{'netAssets':{'value':100,'locator':'XML path','confidence':'medium'}},
                        'monthly_returns':[{'confidence':'low','class_id':None}],
                        'holdings':[{'valUSD':50,'locator':'position','confidence':'medium'}]}]
    r['candidates'][0]['extraction_meta']={'mean_word_confidence':92.1}
    migrate_evidence_contract(r)
    assert 'confidence' not in r['results'][0]
    assert r['nport_reports'][0]['fields']['netAssets']['has_verifiable_evidence']
    assert 'confidence' not in r['nport_reports'][0]['monthly_returns'][0]
    assert r['candidates'][0]['extraction_meta']['mean_word_confidence']==92.1


def test_retry_temporary_limits_but_not_billing(tmp_path,monkeypatch):
    sleeps=[]
    monkeypatch.setattr('apex_benchmark.judgment.time.sleep',sleeps.append)
    class Limited(Session):
        def __init__(self,code):super().__init__();self.code=code;self.attempts=0
        def post(self,*args,**kwargs):
            self.attempts+=1
            if self.attempts>1:return super().post(*args,**kwargs)
            code=self.code
            class Response:
                status_code=429;headers={'retry-after':'2'}
                def json(self):return {'error':{'code':code}}
            return Response()
    s=Limited('rate_limit_exceeded')
    OpenAIJudge('secret','test',tmp_path/'retry',session=s).judge(packet())
    assert s.attempts==2 and len(sleeps)==1 and sleeps[0]>=2
    s=Limited('credit_balance_exhausted')
    with pytest.raises(JudgmentError,match='credit_balance_exhausted'):
        OpenAIJudge('secret','test',tmp_path/'billing',session=s).judge(packet())
    assert s.attempts==1


def test_corrected_response_has_separate_cache_and_is_revalidated(tmp_path):
    (tmp_path/HASH).write_bytes(BODY)
    class CorrectionSession(Session):
        def post(self,url,**kwargs):
            response=super().post(url,**kwargs)
            body=response.json()
            d=decision()
            if 'correction' not in json.loads(kwargs['json']['input']):
                d['citations'][0]['quote']='"'+BODY.decode()+'"'
            body['output'][0]['content'][0]['text']=json.dumps(d)
            response.json=lambda:body
            return response
    s=CorrectionSession();j=OpenAIJudge('secret','test',tmp_path/'judgments',session=s)
    r=adjudicate_run(run(),j,tmp_path,progress=lambda *a,**k:None)
    assert r['results'][0]['value']==1.25 and len(s.calls)==2
    assert 'initial_attempt' in r['llm_judgments'][0]
    assert len(list((tmp_path/'judgments').glob('*.json')))==2
    j=OpenAIJudge(None,'test',tmp_path/'judgments',offline=True,session=s)
    replay=adjudicate_run(run(),j,tmp_path,progress=lambda *a,**k:None)
    assert replay['results'][0]['value']==1.25 and len(s.calls)==2


def test_failed_correction_never_publishes(tmp_path):
    (tmp_path/HASH).write_bytes(BODY)
    class InvalidSession(Session):
        def post(self,url,**kwargs):
            response=super().post(url,**kwargs);body=response.json();d=decision()
            d['value']=99
            body['output'][0]['content'][0]['text']=json.dumps(d)
            response.json=lambda:body
            return response
    s=InvalidSession()
    r=adjudicate_run(run(),OpenAIJudge('secret','test',tmp_path/'cache',session=s),tmp_path,progress=lambda *a,**k:None)
    assert len(s.calls)==2 and r['results'][0]['value'] is None
    assert r['llm_judgments'][0]['validation']=='not_accepted'
    assert 'initial_attempt' in r['llm_judgments'][0]
