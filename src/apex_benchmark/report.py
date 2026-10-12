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


def esc(value):
    return html.escape(str(value))


def display(result):
    if result is None or result.get('value') is None:
        return 'Not available'
    return f"{result['value']:,.2f}{'%' if result.get('unit') == '%' else 'x' if result.get('unit') == 'x' else ''}"


def export(run, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'audit.json').write_text(json.dumps(run, indent=2, allow_nan=False))
    with (output / 'benchmark.csv').open('w', newline='') as file:
        fields = ['ticker', 'metric', 'value', 'unit', 'period', 'basis', 'status', 'confidence', 'reason', 'comparability', 'sources']
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for result in run['results'] + run['nav_history']:
            record = {k: result.get(k, '') for k in fields}
            record['sources'] = json.dumps([{'url': c['source_url'], 'locator': c['locator'], 'quote': c['quote'],
                'filing_date': c['filing_date'], 'sha256': c['source_sha256']} for c in result['sources']])
            # Prevent spreadsheet formula execution for text fields from external filings.
            for key, value in record.items():
                if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
                    record[key] = "'" + value
            writer.writerow(record)
    (output / 'index.html').write_text(html_report(run))
    pdf_report(run, output / 'benchmark.pdf')


def html_report(run):
    cfg = run['config']
    tickers = [f['ticker'] for f in cfg['funds']]
    lookup = {(r['ticker'], r['metric']): r for r in run['results']}
    rows = []
    for metric, label in METRICS.items():
        internal = run['apex']['values'].get(metric)
        cells = [f'<th>{esc(label)}</th>', f'<td>{esc(internal["value"]) if internal else "Withheld / unavailable"}</td>']
        for ticker in tickers:
            r = lookup[ticker, metric]
            cells.append(f'<td class="{esc(r["status"])}"><a href="#{ticker}-{metric}">{display(r)}</a>'
                         f'<small>{esc(r["status"].replace("_", " "))} · {esc(r["confidence"])}</small>'
                         f'<small>{esc(r["period"] or "Period unconfirmed")}</small></td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    evidence = []
    for r in run['results']:
        snippets = []
        for c in r['sources']:
            snippets.append(source_html(c))
        evidence.append(f'<section class="metric" id="{r["ticker"]}-{r["metric"]}"><h3>{r["ticker"]} · {esc(r["label"])}</h3>'
            f'<p><strong>{display(r)}</strong> · {esc(r["status"])} · confidence: {esc(r["confidence"])}</p>'
            f'<p>{esc(r["reason"])} {esc(r["comparability"])}</p><p>Basis: {esc(r["basis"] or "Unconfirmed")}</p>' + ''.join(snippets) + '</section>')
    candidates = []
    for c in run['candidates']:
        candidates.append(f'<details class="candidate" data-search="{esc(c["ticker"] + " " + c["metric"])}">'
            f'<summary>{esc(c["ticker"])} · {esc(c["metric"])} · candidate {esc(c["value"])} · {esc(c["id"])}</summary>'
            f'<p>Candidate only; not a board-approved number. {esc("; ".join(c["reasons"]))}</p>' + source_html(c) + '</details>')
    history = []
    for ticker in tickers:
        items = [r for r in run['nav_history'] if r['ticker'] == ticker]
        history.append('<tr><th>' + ticker + '</th>' + ''.join(f'<td>{display(r)}<small>{esc(r["status"])}</small></td>' for r in items) + '</tr>')
    errors = ''.join(f'<li><strong>{esc(e["ticker"])}</strong>: {esc(e["error"])}</li>' for e in run['errors'])
    inventory = ''.join(f'<tr><td>{esc(f["ticker"])}</td><td>{esc(f["form"])}</td><td>{esc(f["filingDate"])}</td><td>{esc(f.get("reportDate", ""))}</td><td>{esc(f["accessionNumber"])}</td></tr>' for f in run['filings'])
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apex Ridge | Q4 2024 review</title><style>
:root{{font-family:system-ui,sans-serif;color:#18313d;background:#f4f6f5}}body{{margin:0}}main{{max-width:1400px;margin:auto;padding:40px}}h1{{font-size:38px;margin:12px 0}}h2{{margin-top:36px}}.eyebrow{{text-transform:uppercase;letter-spacing:2px;font-size:12px;color:#46766c}}.banner{{padding:20px;background:#fff3db;border-left:4px solid #bd791f;margin:20px 0}}.downloads a{{display:inline-block;background:#183f3a;color:white;padding:10px 16px;margin:4px;text-decoration:none;border-radius:5px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;background:white;font-size:13px}}th,td{{padding:12px;border-bottom:1px solid #dce5e2;text-align:left;vertical-align:top;min-width:110px}}th{{background:#e6eeeb}}small{{display:block;font-size:11px;color:#586c72;margin-top:6px}}a{{color:#166957}}.metric,details{{background:white;padding:20px;margin:12px 0;border:1px solid #dce5e2;border-radius:6px}}blockquote{{border-left:3px solid #9ab5ae;padding:12px;background:#f4f7f6;white-space:pre-wrap;overflow-wrap:anywhere}}.meta{{font-size:12px;overflow-wrap:anywhere}}summary{{cursor:pointer}}input{{padding:12px;width:min(500px,90%);font:inherit}}.supported,.reviewed{{background:#edf6f0}}.conflict,.retrieval_incomplete{{background:#fff6e7}}@media print{{.downloads,input{{display:none}}main{{padding:0}}details{{break-inside:avoid}}}}
</style><main><div class="eyebrow">Apex Ridge Capital · Research review</div><h1>Competitor benchmarking</h1>
<p>Q4 2024 board cycle · filings through {cfg['filing_cutoff']} · target period {cfg['target_period']}</p>
<div class="banner"><strong>REVIEW DRAFT — PM and compliance approval required.</strong><br>
Apex Ridge data: {esc(run['apex']['status'])}. {esc(run['apex']['reason'])}<br>
Blank values are explicit gaps. Retrieval errors do not mean a fund failed to disclose a metric. No synthetic competitor figures.</div>
<nav class="downloads"><a href="benchmark.pdf">Download PDF</a><a href="benchmark.csv">Download CSV</a><a href="audit.json">Full evidence JSON</a></nav>
<h2>Comparison</h2><p>Listed funds use shareholder returns; interval funds use net NAV returns. KREF book value, leverage and yield are not automatically comparable with the other funds.</p>
<div class="scroll"><table><thead><tr><th>Metric</th><th>Apex Ridge</th>{''.join('<th>'+t+'</th>' for t in tickers)}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>NAV history</h2><p>Eight competitor quarter-ends; no interpolation or carry-forward. KREF uses book value per common share. Apex history starts Q1 2024 and is withheld pending approval.</p>
<div class="scroll"><table><tr><th>Fund</th>{''.join('<th>'+d+'</th>' for d in run['quarters'])}</tr>{''.join(history)}</table></div>
<h2>Retrieval and coverage</h2><ul>{errors or '<li>No retrieval errors recorded.</li>'}</ul><p>{len(run['filings'])} eligible filings inventoried; {len(run['documents'])} source documents parsed; {len(run['candidates'])} evidence candidates. Cache mode: {esc(run['mode'])}.</p>
<details><summary>Filing inventory</summary><div class="scroll"><table><tr><th>Fund</th><th>Form</th><th>Filed</th><th>Report period</th><th>Accession</th></tr>{inventory}</table></div></details>
<h2>Values and selection explanations</h2>{''.join(evidence)}
<h2>Extraction review queue</h2><p>These passages are evidence candidates, not accepted values. Reviewer decisions are recorded in a separate JSON file and validated on rerun.</p>
<input id="filter" aria-label="Filter evidence" placeholder="Filter by ticker or metric"><div id="queue">{''.join(candidates) or '<p>No source passages retrieved.</p>'}</div>
<p class="meta">Run {esc(run['run_id'])} · generated {esc(run['generated_at'])}. Confidence is an evidence status, not a statistical probability.</p>
</main><script>document.getElementById('filter').addEventListener('input',e=>{{for(const d of document.querySelectorAll('.candidate'))d.hidden=!d.dataset.search.toLowerCase().includes(e.target.value.toLowerCase());}});</script></html>'''


def source_html(c):
    return f'<p class="meta"><a target="_blank" rel="noopener" href="{esc(c["source_url"])}">Original SEC filing</a> · {esc(c["form"])} · filed {esc(c["filing_date"])} · period {esc(c["period"])}<br>{esc(c["locator"])}<br>Source SHA-256: {esc(c["source_sha256"])}</p><blockquote>{esc(c["quote"])}</blockquote>'


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
        p(f"Q4 2024 board cycle | Filings through {run['config']['filing_cutoff']} | REVIEW DRAFT", 'Heading2'),
        p('Apex Ridge figures withheld pending provenance approval.' if run['apex']['status'] == 'withheld' else run['apex']['reason']),
        p('Listed vehicles: shareholder returns. Interval funds: net NAV returns. KREF is a mortgage REIT; book value, leverage and yield require separate interpretation.'), Spacer(1, 12)]
    tickers = [f['ticker'] for f in run['config']['funds']]
    lookup = {(r['ticker'], r['metric']): r for r in run['results']}
    table = [[p(t, 'Cell') for t in ['Metric', 'Apex Ridge'] + tickers]]
    for metric, label in METRICS.items():
        internal = run['apex']['values'].get(metric)
        row = [p(label, 'Cell'), p(str(internal['value']) if internal else 'Withheld / unavailable', 'Cell')]
        for ticker in tickers:
            r = lookup[ticker, metric]
            row.append(p(f"{display(r)} | {r['status']} | {r['confidence']} | {r['period'] or 'period unconfirmed'}", 'Cell'))
        table.append(row)
    tbl = Table(table, colWidths=[155, 91, 132, 132, 132, 132], repeatRows=1, hAlign='LEFT')
    tbl.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dce9e3')), ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f3f6f5')]),('BOTTOMPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),8)]))
    story.extend([tbl, Spacer(1,10), p('Unavailable means unresolved or not retrieved, not necessarily undisclosed. Confidence labels express evidence checks; they are not probabilities.', 'SmallNote'), PageBreak(), p('NAV history and coverage', 'Title')])
    hist = [[p(t, 'Cell') for t in ['Fund'] + run['quarters']]]
    for ticker in tickers:
        hist.append([p(ticker, 'Cell')] + [p(display(r) + ' | ' + r['status'], 'Cell') for r in run['nav_history'] if r['ticker'] == ticker])
    t = Table(hist, colWidths=[70]+[88]*8, repeatRows=1)
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dce9e3')),('BOTTOMPADDING',(0,0),(-1,-1),12)]))
    story.extend([t, Spacer(1,12), p('No interpolation or carry-forward. Apex history starts Q1 2024; only approved rows through Q4 2024 can be used.')])
    for error in run['errors']:
        story.append(p(error['ticker'] + ': ' + error['error'], 'SmallNote'))
    story.append(p(f"Eligible filings: {len(run['filings'])}. Parsed documents: {len(run['documents'])}. Evidence candidates: {len(run['candidates'])}. Full inventory, review queue and source hashes are in audit.json.", 'SmallNote'))
    story.extend([PageBreak(), p('Evidence and review decisions', 'Title')])
    for r in run['results']:
        story.append(p(f"{r['ticker']} | {r['label']} | {display(r)}", 'Heading3'))
        story.append(p(f"{r['status']} / {r['confidence']}. {r['reason']} Basis: {r['basis'] or 'unconfirmed'}. {r['comparability']}", 'SmallNote'))
        for c in r['sources']:
            story.append(p(f"Filed {c['filing_date']} | period {c['period']} | {c['locator']}", 'SmallNote'))
            story.append(Paragraph(f'<link href="{esc(c["source_url"])}" color="#166957">Original SEC source: {esc(c["accession"])}</link>', styles['SmallNote']))
            # Paragraphs split safely across pages; keep the full quoted evidence.
            story.append(p(c['quote'], 'SmallNote'))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
