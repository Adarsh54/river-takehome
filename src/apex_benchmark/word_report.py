"""Portable committee package with per-value decisions and SEC citations."""
from __future__ import annotations
from docx import Document
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
    if result.get('value') is None:return 'Not established'
    v=result['value'];unit=result.get('unit','')
    return f'{v:,.2f}'+('%' if unit=='%' else 'x' if unit=='x' else ' '+unit)


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


def export_word(run,path):
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
    doc.add_paragraph(f"Judgment mode: {run.get('judgment_mode','rules_only')}. Run reference: {run['run_id']}.")
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
    for f in funds:doc.add_paragraph(f"{f['ticker']}: {f['name']}. CIK {f['cik']}; structure {f['structure']}; share class {f['share_class']}; return basis {f['return_basis']}.")
    for m in cfg.get('custom_metrics',[]):doc.add_paragraph(f"{m['label']} ({m['unit']}): {m['definition']} Measurement period: {m['period_basis']}; scope: {m['scope']}. Reported values only.")
    for error in run.get('errors',[]):doc.add_paragraph('Retrieval or extraction issue: '+error['ticker']+' '+error['error'])
    doc.add_page_break();doc.add_paragraph('Evidence and review notes',style='Heading 1')
    doc.add_paragraph('Each note states the selection rationale or unresolved issue. SEC links identify the original filing; locators identify tables, text blocks, XML paths or PDF pages. Quotations below are short exact excerpts; the companion audit contains complete retained passages and every model attempt. Unresolved entries retain source links and locators without repeating their full passages.')
    for r in run['results']+run['nav_history']:
        doc.add_paragraph(f"{r['ticker']}  {r['label']}  {r.get('requested_period') or r.get('period') or 'Current'}",style='Heading 2')
        supported=r.get('value') is not None
        doc.add_paragraph(value(r)+(' | Evidence linked | '+('Calculated' if r.get('calculation') else 'Directly reported') if supported else ' | Evidence not established'))
        doc.add_paragraph(r['reason'])
        if r.get('basis'):doc.add_paragraph('Definition: '+r['basis']+'. '+r.get('comparability',''))
        if r.get('calculation'):
            import json
            doc.add_paragraph('Calculation: '+json.dumps(r['calculation'],ensure_ascii=False))
        citations=(r.get('judgment') or {}).get('decision',{}).get('citations',[])
        for c in r.get('sources',[]):
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
