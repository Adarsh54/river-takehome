"""Portable committee package with per-value decisions and SEC citations."""
from __future__ import annotations
from docx import Document
from .evidence import evidence_label
from docx.shared import Inches,Pt,RGBColor
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT


def link(paragraph,label,url):
    if not url.startswith('https://www.sec.gov/') and not url.startswith('https://data.sec.gov/'):
        paragraph.add_run(label+' [source URL unavailable]');return
    node=OxmlElement('w:hyperlink');node.set(qn('r:id'),paragraph.part.relate_to(url,RT.HYPERLINK,is_external=True))
    run=OxmlElement('w:r');props=OxmlElement('w:rPr');color=OxmlElement('w:color');color.set(qn('w:val'),'166957');props.append(color);run.append(props)
    text=OxmlElement('w:t');text.text=label;run.append(text);node.append(run);paragraph._p.append(node)


def value(result):
    if result.get('value') is None:return evidence_label(result).replace('Reviewed — value not established','Not established')
    v=result['value'];unit=result.get('unit','')
    return f'{v:,.2f}'+('%' if unit=='%' else 'x' if unit=='x' else ' '+unit)+(' / quarter' if 'quarter' in result.get('basis','').lower() and 'annual' not in result.get('basis','').lower() else '')


def conflict_note(doc,result):
    if not result.get('unresolved_conflict'):return
    doc.add_paragraph('Unresolved conflict — PM review required',style='Heading 2')
    doc.add_paragraph(result['reason'])
    for x in result.get('conflict_candidates',[]):
        c=x['source']
        doc.add_paragraph(f"Candidate {x['value']} {x['unit']} | {x['period']} | {x['basis']} | {x['share_class']}. {x['explanation']}")
        p=doc.add_paragraph();link(p,f"SEC {c['form']} filed {c['filing_date']} | {c['accession']}",c['source_url'])
        p.add_run(' | '+c['locator'])
        doc.add_paragraph(short_excerpt(c['quote'],dict(result,value=x['value'])))
    doc.add_paragraph('Neither candidate is an accepted comparison value.')


def table(doc,headers,rows,widths):
    t=doc.add_table(rows=1, cols=len(headers));t.autofit=False;t.style='Light Shading Accent 1'
    for col,width in zip(t.columns,widths):col.width=Inches(width)
    for c,text,width in zip(t.rows[0].cells,headers,widths):c.text=str(text);c.width=Inches(width)
    repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
    for row in rows:
        cells=t.add_row().cells
        for c,text,width in zip(cells,row,widths):c.text=str(text);c.width=Inches(width)
    for row in t.rows:
        for c in row.cells:
            for p in c.paragraphs:
                p.paragraph_format.space_after=Pt(4);p.paragraph_format.space_before=Pt(3)
                for r in p.runs:r.font.size=Pt(9)
    return t


def short_excerpt(text,result):
    """Keep date headers and the value's neighborhood; mark every omitted span."""
    import re
    if len(text)<=480:return text
    label=result['label'].split(' (')[0]
    hit=re.search(re.escape(label),text,re.I)
    if not hit and result.get('value') is not None:
        number=format(result['value'],'g')
        hit=re.search(r'(?<![\d.])'+re.escape(number)+r'(?:\.0+)?(?![\d.])',text)
    center=hit.start() if hit else 160
    start=max(160,center-100);end=min(len(text),start+320)
    return text[:160]+(' [passage omitted] ' if start>160 else '')+text[start:end]+(' [excerpt ends; full passage in companion audit]' if end<len(text) else '')


def export_evidence_word(run,path):
    doc=Document();sec=doc.sections[0];sec.orientation=WD_ORIENT.LANDSCAPE;sec.page_width=Inches(11.7);sec.page_height=Inches(8.3)
    sec.top_margin=sec.bottom_margin=Inches(.65);sec.left_margin=sec.right_margin=Inches(.65)
    normal=doc.styles['Normal'];normal.font.name='Calibri';normal.font.size=Pt(10);normal.paragraph_format.space_after=Pt(6)
    for name,size in [('Title',24),('Heading 1',17),('Heading 2',12)]:
        doc.styles[name].font.name='Calibri';doc.styles[name].font.size=Pt(size);doc.styles[name].font.color.rgb=RGBColor.from_string('172E2B')
    doc.styles['Title'].font.color.rgb=RGBColor(0,0,0)
    cfg=run['config'];funds=cfg['funds'];labels={r['metric']:r['label'] for r in run['results']}
    doc.add_paragraph('Apex Ridge competitor benchmarking',style='Title')
    doc.add_paragraph(f"Quarter ended {cfg['target_period']}  |  Public filings through {cfg['filing_cutoff']}")
    doc.add_paragraph('Committee review package',style='Heading 1')
    count=sum(r.get('value') is not None for r in run['results'])
    doc.add_paragraph(f"{count} of {len(run['results'])} current comparison values have linked evidence. Values without established support remain blank in the comparison. Review the definitions, reporting dates and explanations before drawing conclusions across funds. This package requires PM and compliance approval before board use.")
    doc.add_paragraph(run['apex']['reason'] if run['apex']['status']!='withheld' else 'Apex Ridge internal figures remain withheld pending resolution of the supplied data provenance. No internal values have been substituted.')
    doc.add_paragraph('Evidence linked means that the value has a traceable source. It does not establish financial correctness or approval. Calculations and differences between shareholder returns, net NAV returns, and REIT book value are explained in the evidence notes.')
    mode={'rules_only':'Parser evidence; not reviewed by AI','llm':'OpenAI evidence review','llm_cached':'Previously saved OpenAI judgments'}.get(run.get('judgment_mode'),run.get('judgment_mode','Parser evidence'))
    doc.add_paragraph(f"Review method: {mode}. Run reference: {run['run_id']}.")
    lookup={(r['ticker'],r['metric']):r for r in run['results']}
    for start in range(0,len(funds),4):
        doc.add_page_break();group=funds[start:start+4];doc.add_paragraph('Current comparison',style='Heading 1')
        rows=[]
        for metric,label in labels.items():
            internal=run['apex']['values'].get(metric)
            row=[label,str(internal['value']) if internal else 'Withheld or unavailable']
            for fund in group:
                r=lookup[fund['ticker'],metric]
                row.append(value(r)+ (' *' if r.get('calculation') else '')+'\n'+(r.get('period') or 'Period unresolved'))
            rows.append(row)
        table(doc,['Metric','Apex Ridge']+[f['ticker'] for f in group],rows,[2.2,1.4]+[6.8/len(group)]*len(group))
        doc.add_paragraph('* Calculated from reported inputs. Empty values are unresolved, not necessarily undisclosed. Each value and gap has a corresponding evidence note. Fee bases and leverage definitions can differ materially.')
    doc.add_page_break();doc.add_paragraph('Per share value history',style='Heading 1')
    doc.add_paragraph('NAV for funds and book value per common share for mortgage REITs. No interpolation or carry-forward. The periods shown are the actual observation dates.')
    for start in range(0,len(run['quarters']),8):
        quarters=run['quarters'][start:start+8];rows=[]
        for f in funds:
            obs={r['period']:r for r in run['nav_history'] if r['ticker']==f['ticker']}
            rows.append([f['ticker']]+[value(obs[q]) if q in obs else 'Not established' for q in quarters])
        table(doc,['Fund']+quarters,rows,[1.0]+[9.4/len(quarters)]*len(quarters))
    doc.add_paragraph('Definitions and comparison set',style='Heading 1')
    for f in funds:doc.add_paragraph(f"{f['ticker']}: {f['name']}. CIK {f['cik']}; structure {f['structure'].replace('_',' ')}; share class {f['share_class']}; return basis {f['return_basis'].replace('_',' ')}.")
    for m in cfg.get('custom_metrics',[]):doc.add_paragraph(f"{m['label']} ({m['unit']}): {m['definition']} Measurement period: {m['period_basis'].replace('_',' ')}; scope: {m['scope'].replace('_',' ')}. Reported values only.")
    for error in run.get('errors',[]):doc.add_paragraph('Retrieval or extraction issue: '+error['ticker']+' '+error['error'])
    doc.add_page_break();doc.add_paragraph('Evidence and review notes',style='Heading 1')
    doc.add_paragraph('Each note states the selection rationale or unresolved issue. SEC links identify the original filing; locators identify tables, text blocks, XML paths or PDF pages. Quotations below are short exact excerpts; the companion audit contains complete retained passages and every model attempt. Unresolved entries retain source links and locators without repeating their full passages.')
    for r in run['results']+run['nav_history']:
        doc.add_paragraph(f"{r['ticker']}  {r['label']}  {r.get('requested_period') or r.get('period') or 'Current'}",style='Heading 2')
        supported=r.get('value') is not None
        doc.add_paragraph(value(r)+(' | Evidence linked | '+('Calculated' if r.get('calculation') else 'Directly reported') if supported else ' | '+evidence_label(r)))
        doc.add_paragraph(r['reason'])
        conflict_note(doc,r)
        if r.get('basis'):doc.add_paragraph('Definition: '+(r['label'] if r['basis'].startswith('custom:') else r['basis'].replace('_',' '))+'. '+r.get('comparability',''))
        if r.get('calculation'):
            import json
            doc.add_paragraph('Calculation: '+json.dumps(r['calculation'],ensure_ascii=False))
        citations=(r.get('judgment') or {}).get('decision',{}).get('citations',[])
        for c in {source['id']:source for source in r.get('sources',[])}.values():
            p=doc.add_paragraph();link(p,f"SEC {c['form']} filed {c['filing_date']} | {c['accession']}",c['source_url'])
            p.add_run(f" | Source period {c['period'] or 'unresolved'} | {c['locator']}")
            if not supported:
                continue  # Gap rationales and locators remain portable; full passages are in the audit.
            # Only validated, exact model excerpts go into the portable appendix.
            excerpts=[x['quote'] for x in citations if x['candidate_id']==c['id'] and x['quote'] in c['quote']]
            if excerpts:
                for excerpt in dict.fromkeys(excerpts):doc.add_paragraph(short_excerpt(excerpt,r))
            else:
                # Parser-only exports preserve the full source, never a fabricated model quote.
                doc.add_paragraph(short_excerpt(c['quote'],r))
    if run['apex']['status']!='withheld':
        doc.add_paragraph('Apex Ridge approved source references',style='Heading 1')
        for metric,item in run['apex']['values'].items():
            doc.add_paragraph(labels.get(metric,metric)+': '+str(item['value']),style='Heading 2')
            doc.add_paragraph(f"Source {item['source']}; row {item['row']}; column {item['column']}; period {item['period']}. SHA-256 {item['sha256']}. Approval: {item['approval']}.")
        for item in run['apex'].get('nav_history',[]):
            doc.add_paragraph(f"Historical NAV {item['period']}: {item['value']}; source {item.get('source','client CSV')}; row {item['row']}; SHA-256 {item.get('sha256','see current source reference')}.")
    footer=sec.footer.paragraphs[0];footer.text='APEX RIDGE  |  PM and compliance review required  |  '
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    doc.core_properties.title='Apex Ridge competitor benchmarking';doc.core_properties.author='Apex Ridge benchmarking prototype'
    doc.save(path)


def committee_summary(run):
    """No relative-performance claim without approved, comparable internal data."""
    if run['apex']['status'] == 'withheld' or not run['apex'].get('values'):
        opening = "Apex Ridge's position relative to the competitor set cannot yet be assessed because its internal figures remain withheld pending source approval."
    else:
        opening = "Apex Ridge's approved internal figures are shown alongside competitors; relative positioning still requires PM confirmation of matching dates and metric definitions."
    priority = [f['ticker'] for f in run['config']['funds']]
    coverage = []
    for ticker in priority:
        rows = [r for r in run['results'] if r['ticker'] == ticker]
        coverage.append(f"{ticker} {sum(r.get('value') is not None for r in rows)} of {len(rows)}")
    middle = ("Current figures with linked evidence are " + "; ".join(coverage) + "; unresolved figures remain explicitly marked."
              if coverage else "Only figures with linked evidence are reported; unresolved figures remain explicitly marked.")
    return opening + ' ' + middle + ' Differences in reporting periods, share classes and calculation methods must be resolved or disclosed before the PM approves comparative language for the LP letter.'


def export_word(run, path):
    """Concise attachment; the separate evidence document retains the full audit."""
    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Inches(11.7), Inches(8.3)
    sec.top_margin = sec.bottom_margin = Inches(.65)
    sec.left_margin = sec.right_margin = Inches(.65)
    normal = doc.styles['Normal']
    normal.font.name, normal.font.size = 'Calibri', Pt(10)
    normal.paragraph_format.space_after = Pt(6)
    for name, size in [('Title', 24), ('Heading 1', 17), ('Heading 2', 12)]:
        doc.styles[name].font.name = 'Calibri'
        doc.styles[name].font.size = Pt(size)
        doc.styles[name].font.color.rgb = RGBColor(0, 0, 0)
    cfg = run['config']
    funds = cfg['funds']
    labels = {r['metric']: r['label'] for r in run['results']}
    lookup = {(r['ticker'], r['metric']): r for r in run['results']}
    supported = [r for r in run['results'] if r.get('value') is not None]
    refs = {(r['ticker'], r['metric']): n for n, r in enumerate(supported, 1)}
    doc.add_paragraph('Apex Ridge committee comparison', style='Title')
    doc.add_paragraph(f"Quarter ended {cfg['target_period']} | Public filings through {cfg['filing_cutoff']}")
    doc.add_paragraph('Summary for committee review', style='Heading 1')
    doc.add_paragraph(committee_summary(run))
    if run['apex']['status'] == 'withheld':
        doc.add_paragraph('Apex Ridge internal figures remain withheld pending resolution of the supplied data provenance.')
    doc.add_paragraph('Read the comparison', style='Heading 1')
    doc.add_paragraph('Each reported competitor figure has a numbered source note in this attachment. Evidence linked means traceable, not approved. Not established means support is unresolved; it does not mean zero or necessarily not disclosed. An asterisk marks a calculation from reported inputs.')
    doc.add_paragraph('Institutional share classes are the client default where available. The class selected for this run is shown above each comparison column; that selection is an assumption until the filing confirms it. Do not substitute another class when its fees or per-share values differ.')
    doc.add_paragraph('The separate evidence document includes full selection rationales, unresolved issues, conflicting figures, calculation inputs and NAV history. PM and compliance review remain required before board or LP use.')
    for f in funds:
        doc.add_paragraph(f"{f['ticker']}: {f['name']}; {f['structure'].replace('_', ' ')}; selected class {f['share_class']}; return basis {f['return_basis'].replace('_', ' ')}.")
    for start in range(0, len(funds), 4):
        doc.add_page_break()
        group = funds[start:start+4]
        doc.add_paragraph('Current comparison', style='Heading 1')
        rows = []
        for metric, label in labels.items():
            internal = run['apex']['values'].get(metric)
            row = [label, (str(internal['value']) + '\n' + internal['period']) if internal else 'Withheld or unavailable']
            for f in group:
                r = lookup[f['ticker'], metric]
                ref = refs.get((f['ticker'], metric))
                row.append(value(r) + (f' [{ref}]' if ref else '') + (' *' if r.get('calculation') else '') + ('\n'+r['period'] if r.get('period') else ''))
            rows.append(row)
        table(doc, ['Metric', 'Apex Ridge'] + [f["ticker"] + '\n' + f['share_class'] for f in group], rows, [2.2, 1.4] + [6.8/len(group)]*len(group))
    doc.add_page_break()
    conflicts=[r for r in run['results']+run['nav_history'] if r.get('unresolved_conflict')]
    if conflicts:
        doc.add_paragraph('Unresolved conflicts',style='Heading 1')
        for r in conflicts:
            doc.add_paragraph(r['ticker']+' | '+r['label']+' | '+(r.get('requested_period') or 'Current'))
            conflict_note(doc,r)
    doc.add_paragraph('Definitions and source notes', style='Heading 1')
    doc.add_paragraph('Fees distinguish contractual rates from effective rates and waivers. Shareholder returns and net NAV returns measure different outcomes. REIT leverage and book value require their own definitions; matching units alone do not establish comparability. The notes below retain the interpretation recorded for each reported value and require PM review.')
    for m in cfg.get('custom_metrics', []):
        doc.add_paragraph(f"{m['label']} ({m['unit']}): {m['definition']} Period: {m['period_basis'].replace('_', ' ')}; scope: {m['scope'].replace('_', ' ')}. Reported values only.")
    for n, r in enumerate(supported, 1):
        doc.add_paragraph(f"{n}  {r['ticker']}  {r['label']}  {value(r)}", style='Heading 2')
        basis = r['label'] if r.get('basis', '').startswith('custom:') else r.get('basis', '').replace('_', ' ')
        doc.add_paragraph(f"Period {r.get('period') or 'unresolved'}. Definition: {basis}. " + r.get('comparability', ''))
        if r.get('calculation'):
            doc.add_paragraph('Calculated from the linked filing inputs; the detailed evidence document gives the formula and reconciliation.')
        for c in {s['id']: s for s in r.get('sources', [])}.values():
            p = doc.add_paragraph()
            link(p, f"SEC {c['form']} filed {c['filing_date']} | {c['accession']}", c['source_url'])
            p.add_run(f" | Source period {c['period'] or 'unresolved'} | {c['locator']}")
    if run['apex']['status'] != 'withheld':
        doc.add_paragraph('Apex Ridge approved source references', style='Heading 1')
        for metric, item in run['apex']['values'].items():
            doc.add_paragraph(f"{labels.get(metric, metric)}: {item['value']}; period {item['period']}; source {item['source']}; row {item['row']}; column {item['column']}; SHA-256 {item['sha256']}; approval {item['approval']}.")
    for error in run.get('errors', []):
        doc.add_paragraph('Retrieval or extraction issue: ' + error['ticker'] + ' ' + error['error'])
    footer = sec.footer.paragraphs[0]
    footer.text = 'APEX RIDGE | PM and compliance review required | '
    field = OxmlElement('w:fldSimple'); field.set(qn('w:instr'), 'PAGE'); footer._p.append(field)
    doc.core_properties.title = 'Apex Ridge committee comparison'
    doc.core_properties.author = 'Apex Ridge benchmarking prototype'
    # Remove inherited template decorations and make table styling explicit.
    for style in doc.styles:
        for border in list(style.element.iter(qn('w:pBdr'))):
            border.getparent().remove(border)
    for t in doc.tables:
        borders = OxmlElement('w:tblBorders')
        for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
            node = OxmlElement('w:' + edge)
            for k, v in {'val':'single', 'sz':'4', 'color':'D9D9D9'}.items(): node.set(qn('w:' + k), v)
            borders.append(node)
        t._tbl.tblPr.append(borders)
        for i, row in enumerate(t.rows):
            for cell in row.cells:
                shading = OxmlElement('w:shd'); shading.set(qn('w:fill'), 'E9ECEF' if i == 0 else 'F5F6F7' if i % 2 else 'FFFFFF')
                cell._tc.get_or_add_tcPr().append(shading)
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs: run.font.color.rgb = RGBColor(0, 0, 0)
    doc.save(path)
