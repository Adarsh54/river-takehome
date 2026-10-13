import copy
import pytest
from apex_benchmark.validation import validate_run, recalculate
from apex_benchmark.judgment import validate_decision, JudgmentError
from test_judgment import run, decision, packet, BODY, HASH


def saved(tmp_path):
    r=run();d=decision();c=r['candidates'][0]
    (tmp_path/HASH).write_bytes(BODY)
    r['results'][0].update({k:d[k] for k in ('value','unit','period','basis')})
    r['results'][0].update(sources=[c],judgment={'decision':d,'packet_complete':True,'evidence_considered':[c]})
    return r


def test_replay_checks_published_values_and_gaps_separately(tmp_path):
    r=saved(tmp_path)
    assert validate_run(r,tmp_path)['summary']=={'pass':1}
    r['results'][0].update(value=None,judgment={},sources=[])
    assert validate_run(r,tmp_path)['summary']=={'gap':1}


@pytest.mark.parametrize('mutation',['source','value','quote','cutoff','truncated','conflict'])
def test_replay_rejects_corrupted_evidence(tmp_path,mutation):
    r=saved(tmp_path);x=r['results'][0]
    if mutation=='source':(tmp_path/HASH).write_bytes(b'altered document')
    if mutation=='value':x['value']=99
    if mutation=='quote':x['judgment']['decision']['citations'][0]['quote']='invented quote'
    if mutation=='cutoff':r['config']['filing_cutoff']='2020-01-01'
    if mutation=='truncated':x['judgment']['packet_complete']=False
    if mutation=='conflict':x['unresolved_conflict']=True
    assert validate_run(r,tmp_path)['summary']=={'fail':1}


def test_arithmetic_and_balance_reconciliation(tmp_path):
    assert recalculate({'expression':'quarterly_hurdle_pct * 4','inputs':{'quarterly_hurdle_pct':2}})==8
    with pytest.raises(ValueError):recalculate({'expression':'unknown','inputs':{}})
    r=saved(tmp_path)
    r['nport_reports']=[{'fields':{k:{'raw':v} for k,v in [('totAssets','100'),('totLiabs','40'),('netAssets','55')]}}]
    assert validate_run(r,tmp_path)['nport_reconciliations'][0]['status']=='fail'


def test_incentive_fee_basis_may_describe_hurdle_but_not_be_hurdle():
    p=packet();p['metric']='incentive_fee'
    c=p['evidence'][0];c['metric']='incentive_fee'
    c['quote']='Incentive fee is 15% of income above the 6% hurdle as of December 31, 2024.'
    d=decision();d.update(value=15,basis='income:after_hurdle_and_catchup')
    d['citations'][0]['quote']=c['quote']
    validate_decision(d,p)
    d.update(value=6,basis='hurdle:net_assets')
    with pytest.raises(JudgmentError,match='cannot use a hurdle'):validate_decision(d,p)
