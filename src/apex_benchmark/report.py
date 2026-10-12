"""Portable output with the same qualification and evidence in every format."""
from __future__ import annotations
import csv
import html
import json
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from .extract import METRICS
from .metrics import metric_labels
from .evidence import evidence_label, migrate_evidence_contract, gap_kind, GAP_LABELS


def esc(value):
    return html.escape(str(value))


def display(result):
    if result is None or result.get('value') is None:
        return evidence_label(result) if result else 'Not available'
    return f"{result['value']:,.2f}{'%' if result.get('unit') == '%' else 'x' if result.get('unit') == 'x' else ''}"+(' / quarter' if 'quarter' in result.get('basis','').lower() and 'annual' not in result.get('basis','').lower() else '')


def export(run, output):
    migrate_evidence_contract(run)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'audit.json').write_text(json.dumps(run, indent=2, allow_nan=False))
    export_nport(run.get('nport_reports', []), output)
    with (output / 'benchmark.csv').open('w', newline='') as file:
        fields = ['ticker', 'metric', 'value', 'unit', 'period', 'basis', 'status', 'has_verifiable_evidence', 'directly_reported', 'decision_author', 'evidence_rationale', 'reason', 'comparability', 'conflict_candidates', 'sources']
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for result in run['results'] + run['nav_history']:
            record = {k: result.get(k, '') for k in fields}
            record['conflict_candidates']=json.dumps(result.get('conflict_candidates',[]))
            record['sources'] = json.dumps([{'url': c['source_url'], 'locator': c['locator'], 'quote': c['quote'],
                'filing_date': c['filing_date'], 'sha256': c['source_sha256'], 'calculation': c.get('calculation'),
                'selection_notes': c.get('reasons', []), 'extraction_meta': c.get('extraction_meta', {})} for c in result['sources']])
            # Prevent spreadsheet formula execution for text fields from external filings.
            for key, value in record.items():
                if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
                    record[key] = "'" + value
            writer.writerow(record)
        for metric, value in run['apex']['values'].items():
            writer.writerow({'ticker': 'APEX', 'metric': metric, 'value': value['value'],
                'unit': 'USD/share' if metric == 'nav' else 'x' if metric == 'leverage' else '%',
                'period': value['period'], 'status': 'client_approved', 'evidence_rationale': value['evidence_rationale'],
                'basis': 'Client supplied; confirm definitions', 'sources': json.dumps(value)})
    (output / 'index.html').write_text(html_report(run))
    (output / 'candidates.html').write_text(candidate_report(run))
    (output / 'judgments.json').write_text(json.dumps(run.get('llm_judgments', []), indent=2, allow_nan=False))
    pdf_report(run, output / 'benchmark.pdf')
    from .word_report import export_word, export_evidence_word
    export_word(run, output / 'benchmark.docx')
    export_evidence_word(run, output / 'benchmark-evidence.docx')


def html_report(run):
    cfg = run['config']
    tickers = [f['ticker'] for f in cfg['funds']]
    lookup = {(r['ticker'], r['metric']): r for r in run['results']}
    from collections import Counter
    coverage=[]
    for label,items in [('Current comparison',run['results']),('Historical per-share values',run['nav_history'])]:
        counts=Counter(gap_kind(r) for r in items)
        summary=' · '.join(f'{counts[k]} {GAP_LABELS[k].lower()}' for k in GAP_LABELS if counts[k])
        coverage.append('<p><strong>'+label+'</strong>: '+esc(summary)+'</p>')
    coverage_html='<section class=metric><h2>Coverage and unresolved work</h2>'+''.join(coverage)+'<p>Evidence not found is a search gap, not proof that the fund did not disclose the metric. Failed or pending AI reviews are system work still to complete. Reviewed gaps retain the model rationale and source passages for human review.</p></section>'
    rows = []
    for metric, label in metric_labels(run['config']).items():
        internal = run['apex']['values'].get(metric)
        cells = [f'<th>{esc(label)}</th>', f'<td>{esc(internal["value"]) if internal else "Withheld / unavailable"}</td>']
        for ticker in tickers:
            r = lookup[ticker, metric]
            cells.append(f'<td class="{esc(r["status"])}"><a href="#{ticker}-{metric}">{display(r)}{"*" if r.get("calculation") else ""}</a>'
                         f'<small>{evidence_label(r)}</small>'
                         f'<small>{esc(r["period"] or "Period unconfirmed")}</small></td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    evidence = []
    for r, is_history in [(r, False) for r in run['results']] + [(r, True) for r in run['nav_history']]:
        snippets = []
        for c in r['sources']:
            snippets.append(source_html(c))
        issues = '<ul>' + ''.join('<li>'+esc(x)+'</li>' for x in r.get('unresolved_issues', [])) + '</ul>' if r.get('unresolved_issues') else ''
        assessments = r.get('judgment', {}).get('decision', {}).get('assessments', [])
        alternatives = '<details><summary>Model assessment of candidate figures</summary><ul>' + ''.join('<li>'+esc(a['reason'])+'</li>' for a in assessments) + '</ul></details>' if assessments else ''
        conflict = '<h4>Competing figures — neither accepted</h4><ul>' + ''.join(
            f'<li><strong>{esc(x["value"])} {esc(x["unit"])}</strong> · {esc(x["period"])} · {esc(x["basis"])} · {esc(x["share_class"])} — {esc(x["explanation"])} '
            f'<a href="{esc(x["source"]["source_url"])}">SEC {esc(x["source"]["form"])} filed {esc(x["source"]["filing_date"])}</a> · {esc(x["source"]["locator"])}</li>'
            for x in r.get('conflict_candidates',[]))+'</ul>' if r.get('unresolved_conflict') else ''
        ident = f'{r["ticker"]}-{r["metric"]}' + (f'-{r["period"]}' if is_history else '')
        evidence.append(f'<section class="metric" id="{ident}"><h3>{r["ticker"]} · {esc(r["label"])} · {esc(r["period"])}</h3>'
            f'<p><strong>{display(r)}</strong> · {evidence_label(r)} · {"Directly reported" if r.get("directly_reported") else "Calculated from cited inputs" if r.get("calculation") else "No supported value"}</p>'
            f'<p>{esc(r["reason"])} {esc(r["comparability"])}</p><p>Basis: {esc(r["basis"] or "Unconfirmed")}</p>' + conflict + issues + alternatives + ''.join(snippets) + '</section>')
    history = []
    for ticker in tickers:
        items = [r for r in run['nav_history'] if r['ticker'] == ticker]
        history.append('<tr><th>' + ticker + '</th>' + ''.join(f'<td><a href="#{ticker}-nav-{r["period"]}">{display(r)}</a><small>{evidence_label(r)}</small></td>' for r in items) + '</tr>')
    apex_history = ''
    if run['apex']['nav_history']:
        apex_history = '<h3>Apex Ridge approved history · starts Q1 2024</h3><p>' + ' · '.join(
            f'{esc(r["period"])}: ${r["value"]:,.2f} (input row {r["row"]})' for r in run['apex']['nav_history']) + '</p>'
    errors = ''.join(f'<li><strong>{esc(e["ticker"])}</strong>: {esc(e["error"])}</li>' for e in run['errors'])
    nport_rows = ''.join(f'<tr><td>{esc(r["ticker"])}</td><td>{esc(r["period"])}</td>'
        f'<td>{r["holdings_summary"]["count"]}</td><td>{esc(r["checks"][0]["status"])}</td>'
        f'<td><a href="{esc(r["source_url"])}">XML source</a></td></tr>' for r in run.get('nport_reports', []))
    ocr_pages = [d for d in run.get('extraction_diagnostics', []) if d['stage'] == 'ocr']
    definitions = ''.join('<p><strong>'+esc(m['label'])+'</strong> ('+esc(m['unit'])+'): '+esc(m['definition'])+' Measurement period: '+esc(m['period_basis'].replace('_',' '))+'; scope: '+esc(m['scope'].replace('_',' '))+'. Reported values only.</p>' for m in cfg.get('custom_metrics',[]))
    inventory = ''.join(f'<tr><td>{esc(f["ticker"])}</td><td>{esc(f["form"])}</td><td>{esc(f["filingDate"])}</td><td>{esc(f.get("reportDate", ""))}</td><td>{esc(f["accessionNumber"])}</td></tr>' for f in run['filings'])
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apex Ridge | {cfg['target_period']} review</title><style>
:root{{font-family:system-ui,sans-serif;color:#18313d;background:#f4f6f5}}body{{margin:0}}main{{max-width:1400px;margin:auto;padding:40px}}h1{{font-size:38px;margin:12px 0}}h2{{margin-top:36px}}.eyebrow{{text-transform:uppercase;letter-spacing:2px;font-size:12px;color:#46766c}}.banner{{padding:20px;background:#fff3db;border-left:4px solid #bd791f;margin:20px 0}}.downloads a{{display:inline-block;background:#183f3a;color:white;padding:10px 16px;margin:4px;text-decoration:none;border-radius:5px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;background:white;font-size:13px}}th,td{{padding:12px;border-bottom:1px solid #dce5e2;text-align:left;vertical-align:top;min-width:110px}}th{{background:#e6eeeb}}small{{display:block;font-size:11px;color:#586c72;margin-top:6px}}a{{color:#166957}}.metric,details{{background:white;padding:20px;margin:12px 0;border:1px solid #dce5e2;border-radius:6px}}blockquote{{border-left:3px solid #9ab5ae;padding:12px;background:#f4f7f6;white-space:pre-wrap;overflow-wrap:anywhere}}.meta{{font-size:12px;overflow-wrap:anywhere}}summary{{cursor:pointer}}input{{padding:12px;width:min(500px,90%);font:inherit}}.supported,.reviewed{{background:#edf6f0}}.conflict,.retrieval_incomplete,.extraction_incomplete{{background:#fff6e7}}@media print{{.downloads,input{{display:none}}main{{padding:0}}details{{break-inside:avoid}}}}
</style><main><div class="eyebrow">Apex Ridge Capital · Research review</div><h1>Competitor benchmarking</h1>
<p>Quarter ended {cfg['target_period']} · filings through {cfg['filing_cutoff']} · target period {cfg['target_period']}</p>
{coverage_html}
<div class="banner"><strong>REVIEW DRAFT — PM and compliance approval required.</strong><br>
Judgment mode: {esc(run.get("judgment_mode", "rules_only"))}. A rules-only report has not been assessed by an LLM.<br>
Apex Ridge data: {esc(run['apex']['status'])}. {esc(run['apex']['reason'])}<br>
Blank values distinguish evidence not found, pending/failed AI review, and reviewed but unestablished values. None is proof of non-disclosure. No synthetic competitor figures.</div>
<nav class="downloads"><a href="benchmark.docx">Committee Word</a><a href="benchmark-evidence.docx">Detailed evidence Word</a><a href="benchmark.pdf">Download PDF</a><a href="benchmark.csv">Download CSV</a><a href="audit.json">Full evidence JSON</a><a href="judgments.json">Model decision records</a></nav>
{('<details><summary>Custom metric definitions for this run</summary>'+definitions+'</details>') if definitions else ''}
<h2>Comparison</h2><p>Listed funds use shareholder returns; interval funds use net NAV returns. KREF book value, leverage and yield are not automatically comparable with the other funds. Fee bases differ; KREF's annualized percentage retains a quarterly dollar minimum. * Calculated from filing values; open the evidence for inputs and formula.</p>
<div class="scroll"><table><thead><tr><th>Metric</th><th>Apex Ridge</th>{''.join('<th>'+t+'</th>' for t in tickers)}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>NAV history</h2><p>Eight competitor quarter-ends; no interpolation or carry-forward. KREF uses book value per common share. Apex history starts Q1 2024 and is withheld pending approval.</p>
<div class="scroll"><table><tr><th>Fund</th>{''.join('<th>'+d+'</th>' for d in run['quarters'])}</tr>{''.join(history)}</table></div>
{apex_history}
<h2>Retrieval and extraction coverage</h2><ul>{errors or '<li>No retrieval or extraction errors recorded.</li>'}</ul><p>{len(run['filings'])} eligible filings inventoried; {len(run['documents'])} source documents parsed; {len(run['candidates'])} evidence candidates. Cache mode: {esc(run['mode'])}.</p>
<details><summary>Filing inventory</summary><div class="scroll"><table><tr><th>Fund</th><th>Form</th><th>Filed</th><th>Report period</th><th>Accession</th></tr>{inventory}</table></div></details>
<details><summary>N-PORT structured evidence and OCR coverage</summary>
<p><a href="nport.json">N-PORT fields, checks and monthly returns (JSON)</a> · <a href="nport-holdings.csv">Holdings CSV</a></p>
<p>Fund-level net assets are not NAV per share. Borrowing ratios require review before debt/equity comparison. Monthly return classes may be unidentified. XML locators use the namespace recorded in nport.json.</p>
<table><tr><th>Fund</th><th>Observation date</th><th>Holdings</th><th>Balance check</th><th>Evidence</th></tr>{nport_rows}</table>
<p>{len(ocr_pages)} pages attempted or flagged for OCR; {sum(d['status']=='processed' for d in ocr_pages)} processed. Page-level details and word coordinates are in audit.json. OCR values require visual verification.</p></details>
<h2>Values and selection explanations</h2>{''.join(evidence)}
<h2>Extraction review queue</h2><p>These passages are evidence candidates, not accepted values. Reviewer decisions are recorded in a separate JSON file and validated on rerun.</p>
<p><a href="candidates.html">Open full extraction review queue</a> · <a href="audit.json">Download the complete evidence audit</a>. All candidate passages are retained in the separate review queue so the comparison page can open quickly.</p>
<p class="meta">Run {esc(run['run_id'])} · generated {esc(run['generated_at'])}. Evidence support is explained per value. Model judgment is separate from PM and compliance approval.</p>
</main></html>'''


def candidate_report(run):
    entries=[]
    for c in run['candidates']:
        entries.append(f'<details class="candidate" data-search="{esc(c["ticker"]+" "+c["metric"])}">'
            f'<summary>{esc(c["ticker"])} · {esc(c["metric"])} · candidate {esc(c["value"])} · {esc(c["id"])}</summary>'
            f'<p>Candidate only; not a board-approved number. {esc("; ".join(c["reasons"]))}</p>'+source_html(c)+'</details>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Extraction review queue</title>'
        '<style>body{font:15px/1.5 system-ui;margin:32px;color:#172e2b}details{padding:16px;border:1px solid #d6dfdb;margin:12px 0}blockquote{white-space:pre-wrap;overflow-wrap:anywhere}.meta{overflow-wrap:anywhere}input{padding:12px;width:400px}summary{cursor:pointer}</style>'
        '<h1>Extraction review queue</h1><p><a href="index.html">Back to comparison</a> · <a href="audit.json">Full evidence audit</a></p>'
        '<p>All extracted candidates are retained here. These are not accepted results.</p>'
        '<input id="filter" aria-label="Filter evidence" placeholder="Filter by ticker or metric">'+''.join(entries)+
        "<script>document.getElementById('filter').addEventListener('input',e=>{for(const d of document.querySelectorAll('.candidate'))d.hidden=!d.dataset.search.toLowerCase().includes(e.target.value.toLowerCase());});</script></html>")


def source_html(c):
    calc = f'<p>Calculation: {esc(json.dumps(c["calculation"]))}</p>' if c.get('calculation') else ''
    meta = c.get('extraction_meta', {})
    if meta:
        visible = {k: v for k, v in meta.items() if k not in {'text', 'words'}}
        calc += f'<p>Extraction details: {esc(json.dumps(visible))}. Full word boxes, if applicable, are in audit.json.</p>'
    return f'<p class="meta"><a target="_blank" rel="noopener" href="{esc(c["source_url"])}">Original SEC filing</a> · {esc(c["form"])} · filed {esc(c["filing_date"])} · period {esc(c["period"])}<br>{esc(c["locator"])}<br>Source SHA-256: {esc(c["source_sha256"])}</p>{calc}<blockquote>{esc(c["quote"])}</blockquote>'


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#61716f'))
    canvas.drawString(doc.leftMargin, 22, 'APEX RIDGE  |  REVIEW DRAFT  |  PM + compliance approval required')
    canvas.drawRightString(doc.pagesize[0]-doc.rightMargin, 22, str(doc.page))
    canvas.restoreState()


def pdf_report(run, path):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('Cell', fontName='Helvetica', fontSize=7, leading=10, spaceAfter=0))
    styles.add(ParagraphStyle('SmallNote', fontSize=8, leading=11, spaceAfter=6))
    p = lambda text, style='BodyText': Paragraph(esc(text), styles[style])
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=32, rightMargin=32, topMargin=32, bottomMargin=40)
    story = [p('Apex Ridge | Competitor benchmarking', 'Title'),
        p(f"Quarter ended {run['config']['target_period']} | Filings through {run['config']['filing_cutoff']} | REVIEW DRAFT", 'Heading2'),
        p('Judgment mode: ' + run.get('judgment_mode', 'rules_only') + '. Evidence linked means traceable support; interpretation still requires PM/compliance review.', 'SmallNote'),
        p('Apex Ridge figures withheld pending provenance approval.' if run['apex']['status'] == 'withheld' else run['apex']['reason']),
        p('Listed vehicles: shareholder returns. Interval funds: net NAV returns. KREF is a mortgage REIT; book value, leverage and yield require separate interpretation.'), Spacer(1, 12)]
    tickers = [f['ticker'] for f in run['config']['funds']]
    lookup = {(r['ticker'], r['metric']): r for r in run['results']}
    for start in range(0,len(tickers),4):
        group=tickers[start:start+4]
        if start:story.append(PageBreak())
        table = [[p(t, 'Cell') for t in ['Metric', 'Apex Ridge'] + group]]
        for metric, label in metric_labels(run['config']).items():
            internal = run['apex']['values'].get(metric)
            row = [p(label, 'Cell'), p(str(internal['value']) if internal else 'Withheld / unavailable', 'Cell')]
            for ticker in group:
                r = lookup[ticker, metric]
                row.append(p(f"{display(r)}{'*' if r.get('calculation') else ''} | {evidence_label(r)} | {r['period'] or 'period unconfirmed'}", 'Cell'))
            table.append(row)
        tbl = Table(table, colWidths=[155, 91]+[(doc.width-246)/len(group)]*len(group), repeatRows=1, hAlign='LEFT')
        tbl.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dce9e3')), ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f3f6f5')]),('BOTTOMPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6)]))
        story.extend([tbl, Spacer(1,10), p('Unavailable means unresolved or not retrieved, not necessarily undisclosed. * Calculated: see evidence for inputs and formula. Fee bases differ; KREF retains a quarterly dollar minimum. Source support and selection rationales are explained per value.', 'SmallNote')])
    story.extend([PageBreak(), p('NAV history and coverage', 'Title')])
    hist = [[p(t, 'Cell') for t in ['Fund'] + run['quarters']]]
    for ticker in tickers:
        hist.append([p(ticker, 'Cell')] + [p(display(r) + ' | ' + evidence_label(r), 'Cell') for r in run['nav_history'] if r['ticker'] == ticker])
    t = Table(hist, colWidths=[70]+[(doc.width-70)/len(run['quarters'])]*len(run['quarters']), repeatRows=1)
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dce9e3')),('BOTTOMPADDING',(0,0),(-1,-1),12)]))
    story.extend([t, Spacer(1,12), p(f"No interpolation or carry-forward. Apex history starts {run['config'].get('apex_history_start','2024-03-31')}; only approved rows through {run['config']['target_period']} can be used.")])
    if run['apex']['nav_history']:
        story.append(p('Apex Ridge approved history: ' + ' | '.join(f'{r["period"]}: ${r["value"]:,.2f} (input row {r["row"]})' for r in run['apex']['nav_history']), 'SmallNote'))
    for error in run['errors']:
        story.append(p(error['ticker'] + ': ' + error['error'], 'SmallNote'))
    story.append(p(f"Eligible filings: {len(run['filings'])}. Parsed documents: {len(run['documents'])}. Evidence candidates: {len(run['candidates'])}. Full inventory, review queue and source hashes are in audit.json.", 'SmallNote'))
    story.extend([PageBreak(), p('Evidence and review decisions', 'Title')])
    for r in run['results'] + [r for r in run['nav_history'] if r['sources']]:
        story.append(p(f"{r['ticker']} | {r['label']} | {r['period']} | {display(r)}", 'Heading3'))
        story.append(p(f"{evidence_label(r)}. {r['reason']} Basis: {r['basis'] or 'unconfirmed'}. {r['comparability']}", 'SmallNote'))
        for c in r['sources']:
            story.append(p(f"Filed {c['filing_date']} | period {c['period']} | {c['locator']}", 'SmallNote'))
            story.append(Paragraph(f'<link href="{esc(c["source_url"])}" color="#166957">Original SEC source: {esc(c["accession"])}</link>', styles['SmallNote']))
            # Paragraphs split safely across pages; keep the full quoted evidence.
            story.append(p(c['quote'], 'SmallNote'))
            if c.get('calculation'):
                story.append(p('Calculation: ' + json.dumps(c['calculation']), 'SmallNote'))
    for metric, value in run['apex']['values'].items():
        story.append(p(f'Apex Ridge | {METRICS[metric]} | {value["value"]}', 'Heading3'))
        story.append(p(f'Client-approved source: {value["source"]}, row {value["row"]}, column {value["column"]}. SHA-256: {value["sha256"]}. Approval: {value["approval"]}', 'SmallNote'))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def export_nport(reports, output):
    (output / 'nport.json').write_text(json.dumps(reports, indent=2, allow_nan=False))
    fields = ['ticker', 'period', 'filing_date', 'accession', 'source_url', 'source_sha256',
              'locator', 'name', 'title', 'cusip', 'curCd', 'units', 'assetCat', 'issuerCat',
              'payoffProfile', 'fairValLevel', 'balance', 'valUSD', 'pctVal', 'has_verifiable_evidence']
    with (output / 'nport-holdings.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for report in reports:
            for holding in report['holdings']:
                record = {k: holding.get(k, report.get(k, '')) for k in fields}
                for key, value in record.items():
                    if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
                        record[key] = "'" + value
                writer.writerow(record)
