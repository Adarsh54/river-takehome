"""Synthetic regression fixtures; OCR integration uses the real local engine."""
import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from apex_benchmark.extract import parse_document
from apex_benchmark.nport import BORROWINGS, parse_nport
from apex_benchmark.pdf_extract import pdf_candidates, parse_tsv, ocr_environment
from apex_benchmark.normalize import qualify_disclosures
from apex_benchmark.resolve import apply_decisions
from apex_benchmark.report import export_nport

FUND = {'ticker': 'TEST', 'cik': '0001234567', 'structure': 'interval', 'share_class': 'Class I'}
FILING = {'form': 'NPORT-P', 'filingDate': '2025-02-20', 'reportDate': '2024-12-31', 'accessionNumber': 'test-only'}
SOURCE = {'url': 'https://www.sec.gov/Archives/test/primary_doc.xml', 'sha256': 'synthetic-test-only'}


def xml(**changes):
    fields = {'totAssets': '120', 'totLiabs': '20', 'netAssets': '100',
              **{b: '0' for b in BORROWINGS}, 'amtPayAftOneYrBanksBorr': '10'}
    fields.update(changes)
    items = ''.join(f'<{k}>{v}</{k}>' for k,v in fields.items() if v is not None)
    return f'''<XML>
<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/nport"><formData>
<genInfo><regCik>0001234567</regCik><seriesId>S001</seriesId><seriesName>Test</seriesName>
<repPdEnd>2025-03-31</repPdEnd><repPdDate>2024-12-31</repPdDate></genInfo>
<fundInfo>{items}<returnInfo><monthlyTotReturns>
<monthlyTotReturn rtn1="-1.2" rtn2="0" rtn3="0.8" classId="C001"/>
<monthlyTotReturn rtn1="2" rtn2="3" rtn3="4"/>
</monthlyTotReturns></returnInfo></fundInfo>
<invstOrSecs><invstOrSec><name>=FORMULA</name><title>Loan</title><balance>100</balance>
<valUSD>110</valUSD><pctVal>110</pctVal><curCd>USD</curCd><assetCat>LON</assetCat>
<debtSec><annualizedRt>9.5</annualizedRt><maturityDt>2029-01-01</maturityDt></debtSec>
</invstOrSec></invstOrSecs></formData></edgarSubmission></XML>'''.encode()


def test_nport_exact_fields_dates_units_and_review_only_ratio():
    r, cs = parse_nport(xml(), FUND, FILING, SOURCE)
    assert r['period'] == '2024-12-31' and r['fiscal_year_end'] == '2025-03-31'
    assert r['fields']['netAssets']['value'] == 100
    assert r['fields']['netAssets']['unit'] == 'USD'
    assert r['checks'][0]['status'] == 'pass'
    assert r['monthly_returns'][0]['values_pct']['rtn1'] == -1.2
    assert r['monthly_returns'][1]['status'] == 'class_unconfirmed'
    assert r['holdings'][0]['debt_security']['annualizedRt'] == '9.5'
    assert r['holdings'][0]['valUSD'] == 110 and '[1]' in r['holdings'][0]['locator']
    assert len(cs) == 1 and cs[0].value == 0.1 and not cs[0].eligible
    assert 'amtPayAftOneYrBanksBorr' in cs[0].quote
    assert cs[0].extraction_meta['calculation']['inputs']['netAssets'] == 100
    assert all(c.metric != 'nav' and not c.metric.startswith('return_') for c in cs)


@pytest.mark.parametrize('changes', [{'netAssets':'NaN'}, {'netAssets':'0'},
    {'amtPayOneYrBanksBorr':None}, {'amtPayOneYrBanksBorr':'-1'}])
def test_missing_invalid_or_nonpositive_denominator_never_guessed(changes):
    r, cs = parse_nport(xml(**changes), FUND, FILING, SOURCE)
    assert not cs


def test_balance_mismatch_exposed_and_identity_checked():
    r,_ = parse_nport(xml(totLiabs='30'), FUND, FILING, SOURCE)
    assert r['checks'][0]['status'] == 'fail'
    for fund, filing in [(dict(FUND,cik='999'),FILING), (dict(FUND,series_id='S002'),FILING),
                         (FUND,dict(FILING,reportDate='2024-09-30'))]:
        with pytest.raises(ValueError):
            parse_nport(xml(),fund,filing,SOURCE)


def test_xml_namespace_variants_and_external_entities_fail_closed():
    text=xml().decode().removeprefix('<XML>\n').removesuffix('</XML>')
    # A default namespace and an explicit prefix are equivalent.
    from lxml import etree
    root=etree.fromstring(text.encode())
    etree.cleanup_namespaces(root, top_nsmap={'n':'http://www.sec.gov/edgar/nport'})
    assert parse_nport(etree.tostring(root),FUND,FILING,SOURCE)[0]['period']=='2024-12-31'
    evil=text.replace('<edgarSubmission', '<!DOCTYPE edgarSubmission [<!ENTITY external SYSTEM "file:///etc/passwd">]><edgarSubmission',1)
    with pytest.raises(ValueError,match='DTD'):
        parse_nport(evil.encode(),FUND,FILING,SOURCE)
    with pytest.raises(ValueError,match='namespace'):
        parse_nport(text.replace('http://www.sec.gov/edgar/nport','urn:wrong').encode(),FUND,FILING,SOURCE)
    with pytest.raises(ValueError,match='Duplicate'):
        parse_nport(xml().replace(b'<netAssets>',b'<netAssets>100</netAssets><netAssets>'),FUND,FILING,SOURCE)


def test_dispatch_exports_structured_evidence_and_csv_safe(tmp_path):
    structured=[]
    cs=parse_document(xml(),FUND,FILING,SOURCE,structured=structured)
    assert cs and len(structured)==1
    export_nport(structured,tmp_path)
    rows=list(csv.DictReader((tmp_path/'nport-holdings.csv').open()))
    assert rows[0]['name']=="'=FORMULA" and rows[0]['source_sha256']==SOURCE['sha256']
    assert json.loads((tmp_path/'nport.json').read_text())[0]['fields']['netAssets']['locator'].endswith('/n:netAssets')


def pdf_bytes(scanned=False, mixed=False):
    from reportlab.pdfgen.canvas import Canvas
    out=io.BytesIO(); c=Canvas(out,pagesize=(612,792))
    if scanned:
        from PIL import Image, ImageDraw, ImageFont
        from reportlab.lib.utils import ImageReader
        # The fixture is an image-only page, with no embedded text layer.
        image=Image.new('RGB',(1800,900),'white')
        draw=ImageDraw.Draw(image)
        font=ImageFont.truetype('DejaVuSans.ttf',42) if Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf').exists() else ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',42)
        draw.text((80,100),'Management fee is 1.25% of net assets.',font=font,fill='black')
        draw.text((80,190),'Net asset value per share is $12.34.',font=font,fill='black')
        draw.text((80,280),'As of December 31, 2024. Test fixture only.',font=font,fill='black')
        c.drawImage(ImageReader(image),30,400,width=552,height=276)
        if mixed:
            c.showPage()
    if not scanned or mixed:
        c.drawString(40,700,'Management fee is 2.50% of net assets. ' + 'Native text evidence. '*10)
    c.save();return out.getvalue()


def test_tsv_retains_negative_low_confidence_words_and_boxes():
    tsv='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    tsv+='5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t55\t-1.25%\n'
    data=parse_tsv(tsv)
    assert data['text']=='-1.25%' and data['low_confidence_words']==1
    assert data['words'][0]['box_px']==[10,20,30,40]


@pytest.mark.parametrize('mode,status',[('off','disabled'),('auto','unavailable')])
def test_ocr_missing_or_disabled_is_explicit(mode,status):
    diagnostics=[]
    pdf_candidates(pdf_bytes(True),FUND,FILING,SOURCE,diagnostics,mode,
                   {'tesseract':None,'renderer':None})
    assert diagnostics[0]['status']==status and diagnostics[0]['error']


def test_ocr_timeout_is_reported_and_native_next_page_continues(monkeypatch):
    def fail(*args):
        raise subprocess.TimeoutExpired('tesseract',90)
    monkeypatch.setattr('apex_benchmark.pdf_extract.ocr_page',fail)
    diagnostics=[]
    cs=pdf_candidates(pdf_bytes(True,True),FUND,FILING,SOURCE,diagnostics,'auto',
                      {'tesseract':'fake-test','renderer':'test','engine_version':'test'})
    assert diagnostics[0]['status']=='failed'
    assert any(c.value==2.5 for c in cs)


def test_real_ocr_image_only_and_mixed_pdf():
    if not shutil.which('tesseract'):
        pytest.skip('Install Tesseract to run OCR integration; CI installs it')
    pytest.importorskip('pypdfium2')
    diagnostics=[]
    cs=pdf_candidates(pdf_bytes(True,True),FUND,FILING,SOURCE,diagnostics)
    c=next(c for c in cs if c.value==1.25)
    assert c.method=='ocr_evidence' and not c.eligible
    assert c.extraction_meta['page']==1 and c.extraction_meta['words']
    assert c.extraction_meta['mean_word_confidence'] > 50
    assert 'PDF page 1' in c.locator
    assert any(c.value==12.34 for c in cs)
    assert any(c.value==2.5 and 'page 2' in c.locator for c in cs)
    assert diagnostics[0]['status']=='processed'
    decision={'candidate_id':c.id,'action':'accept','value':1.25,'period':'2024-12-31',
              'basis':'contractual:net_assets','share_class':'Class I','unit':'%',
              'evidence_text':'1.25%','reviewer':'Test reviewer','reason':'Checked original page'}
    with pytest.raises(ValueError,match='visual_verified'):
        apply_decisions([c.dict()],[decision],'2025-02-28')
    assert apply_decisions([c.dict()],[dict(decision,visual_verified=True)],'2025-02-28')


def test_ocr_does_not_bypass_review_via_qualifier():
    source={'ticker':'CCLFX','accession':'one','method':'ocr_evidence',
            'quote':'Investment Management Fee equal to 1.0% accrued daily, on an annualized basis of the Fund’s Net Assets'}
    filings=[{'ticker':'CCLFX','form':'N-CSR','reportDate':'2024-12-31','filingDate':'2025-02-01','accessionNumber':'one'}]
    assert qualify_disclosures([source],filings,{'funds':[{'ticker':'CCLFX'}],'target_period':'2024-12-31'})==[]


def test_broken_pdf_becomes_explicit_extraction_error():
    diagnostics=[]
    assert pdf_candidates(b'%PDF-broken',FUND,FILING,SOURCE,diagnostics,'off',{'tesseract':None,'renderer':None})==[]
    assert diagnostics[0]['stage']=='parse' and diagnostics[0]['error']


def test_ocr_coverage_failure_is_distinct_from_sec_failure():
    from apex_benchmark.resolve import resolve_metric
    result=resolve_metric([],FUND,'nav',{'filing_cutoff':'2025-02-28','target_period':'2024-12-31'},
                          retrieval_errors=[{'stage':'ocr','error':'Engine unavailable'}])
    assert result['status']=='extraction_incomplete' and result['value'] is None


def test_derived_nport_ratio_cannot_be_approved_as_quoted_zero():
    _,cs=parse_nport(xml(**{b:'0' for b in BORROWINGS}),FUND,FILING,SOURCE)
    decision={'candidate_id':cs[0].id,'action':'accept','reviewer':'Test','reason':'Test',
              'value':0,'period':'2024-12-31','basis':'debt_to_equity:test','share_class':'Fund-level',
              'evidence_text':'0','unit':'x'}
    with pytest.raises(ValueError,match='implemented benchmark rule'):
        apply_decisions([cs[0].dict()],[decision],'2025-02-28')


def test_pipeline_roundtrip_retains_structured_data_and_invalidates_ocr_mode(tmp_path,monkeypatch):
    import apex_benchmark.cli as cli
    filing=dict(FILING,primaryDocument='primary_doc.xml')
    monkeypatch.setattr(cli,'discover',lambda *args:[filing])
    monkeypatch.setattr('apex_benchmark.pdf_extract.ocr_environment',lambda:{'tesseract':None,'renderer':None})
    calls=[]; original=cli.parse_document
    def parse(*args,**kwargs):
        calls.append(kwargs['ocr_mode']);return original(*args,**kwargs)
    monkeypatch.setattr(cli,'parse_document',parse)
    class Client:
        offline=True;refresh=False;cache=tmp_path
        def get(self,url):
            return xml(),{'sha256':'test-only','retrieved_at':'2025-02-28T00:00:00Z'}
    config={'funds':[dict(FUND,return_basis='net_nav')], 'target_period':'2024-12-31',
            'filing_cutoff':'2025-02-28','history_quarters':8,'apex_data_approved':False}
    first=cli.run_pipeline(config,Client(),Path(__file__).resolve().parents[1]/'data/apex_ridge_fund_data.csv',progress=lambda *a,**k:None)
    second=cli.run_pipeline(config,Client(),Path(__file__).resolve().parents[1]/'data/apex_ridge_fund_data.csv',progress=lambda *a,**k:None)
    assert len(first['nport_reports'])==1 and first['nport_reports']==second['nport_reports']
    assert not first['errors'] and calls==['auto']
    cli.run_pipeline(config,Client(),Path(__file__).resolve().parents[1]/'data/apex_ridge_fund_data.csv',progress=lambda *a,**k:None,ocr_mode='off')
    assert calls==['auto','off']
