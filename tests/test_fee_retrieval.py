import hashlib
import json
from apex_benchmark.fee_retrieval import retrieve_fee_passages
from apex_benchmark.passages import VERSION
from test_judgment import C


def indexed(tmp_path, texts, accession='a'):
    body=' '.join(texts).encode();digest=hashlib.sha256(body).hexdigest()
    (tmp_path/digest).write_bytes(body)
    folder=tmp_path/'passages'/VERSION;folder.mkdir(parents=True,exist_ok=True)
    ps=[{'id':digest+':'+str(i),'text':t,'kind':'paragraph_or_footnote',
         'locator':f'paragraph {i}','section_headings':['Fees']} for i,t in enumerate(texts)]
    (folder/(digest+'.json')).write_text(json.dumps(ps))
    return dict(C,id=digest[:20],source_sha256=digest,source_url='https://sec.gov/'+accession,
                accession=accession,quote=texts[0],metric='effective_fee',eligible=False),ps,folder/(digest+'.json')


def test_fee_retrieval_uses_index_and_preserves_conflict_and_context(tmp_path,monkeypatch):
    c,_,_=indexed(tmp_path,['Year ended December 31, 2024','Management fee 1.50%.',
        'Temporary fee waiver expires December 31, 2025.','Effective management fee 1.25%.',
        'Fees based on average net assets.']+['Other unrelated information.']*6+['Jury trial waiver.'])
    monkeypatch.setattr('apex_benchmark.passages.parse_passages',lambda *a: (_ for _ in ()).throw(AssertionError('reparsed')))
    out,audit=retrieve_fee_passages([c,c],tmp_path)
    text=' '.join(x['quote'] for x in out)
    assert all(t in text for t in ['1.50%','1.25%','December 31, 2025','average net assets','December 31, 2024'])
    assert 'Jury trial waiver' not in text
    assert audit['documents_searched']==1
    assert out[0]['section_headings']==['Fees']


def test_fee_tables_keep_headers_geometry_and_long_footnote_list(tmp_path):
    c,ps,path=indexed(tmp_path,['Year ended 2024 2023 Base management fee 2.1% 2.4%']+
        [f'({i}) fee condition {i}' for i in range(1,7)])
    ps[0].update(kind='table',rows=[[{'text':x,'colspan':'1','rowspan':'1'} for x in ['Year','2024','2023']],
                                   [{'text':x,'colspan':'1','rowspan':'1'} for x in ['Base management fee','2.1%','2.4%']]])
    path.write_text(json.dumps(ps))
    out,_=retrieve_fee_passages([c],tmp_path)
    table=next(x for x in out if x['table_rows'])
    assert table['table_rows'][0][1][1]=='2024'
    assert '(6) fee condition 6' in ' '.join(x['quote'] for x in out)


def test_different_filings_are_not_deduplicated(tmp_path):
    a,_,_=indexed(tmp_path,['Management fee 1.50%.'],'a')
    b,_,_=indexed(tmp_path,['Management fee 1.25%.'],'b')
    out,_=retrieve_fee_passages([a,b],tmp_path)
    assert {x['accession'] for x in out}=={'a','b'}


def test_missing_index_preserves_candidates_without_reparse(tmp_path,monkeypatch):
    monkeypatch.setattr('apex_benchmark.passages.parse_passages',lambda *a: (_ for _ in ()).throw(AssertionError('reparsed')))
    out,audit=retrieve_fee_passages([dict(C)],tmp_path)
    assert out==[C]
    assert audit['index_unavailable']==[C['source_url']]
