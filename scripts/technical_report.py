"""Readable, three-page technical handoff. Build without network or model calls."""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
INK = colors.HexColor('#172C3A')
MUTED = colors.HexColor('#526572')
ACCENT = colors.HexColor('#22675D')
LINE = colors.HexColor('#D8E1E4')
WIDTH = A4[0] - 108
S = {
    'title': ParagraphStyle('ReportTitle', fontName='Helvetica-Bold', fontSize=25, leading=29, textColor=INK, spaceAfter=10),
    'sub': ParagraphStyle('ReportSubtitle', fontName='Helvetica', fontSize=10, leading=14, textColor=MUTED, spaceAfter=16),
    'heading': ParagraphStyle('ReportHeading', fontName='Helvetica-Bold', fontSize=11.5, leading=15, textColor=INK, spaceBefore=12, spaceAfter=5),
    'body': ParagraphStyle('ReportBody', fontName='Helvetica', fontSize=10.5, leading=15, textColor=INK, spaceAfter=8),
    'small': ParagraphStyle('ReportSmall', fontName='Helvetica', fontSize=8.5, leading=12, textColor=MUTED, spaceAfter=7),
    'cell': ParagraphStyle('ReportCell', fontName='Helvetica', fontSize=9.5, leading=13, textColor=INK),
    'headcell': ParagraphStyle('ReportHeadCell', fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=INK),
}


def para(text, style='body'):
    return Paragraph(text, S[style])


def section(title, text):
    return KeepTogether([para(title, 'heading'), para(text)])


def grid(headers, rows, widths):
    table = Table([[para(x, 'headcell') for x in headers]] + [[para(x, 'cell') for x in row] for row in rows], colWidths=widths, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EDF2F3')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('LINEBELOW', (0, 0), (-1, -1), .5, LINE),
    ]))
    return table


def build_technical(path=ROOT/'docs/technical-approach.pdf'):
    story = [
        para('Technical approach', 'title'),
        para('Apex Ridge Capital  |  Prototype handoff  |  Updated October 12, 2026', 'sub'),
        para('I built a local application that turns SEC filings into a reviewable fund comparison. It automates finding and interpreting disclosures; the PM still decides whether the comparison is ready, and compliance can follow each accepted number back to its source.'),
        section('The scope I used',
            'The comparison is for Q4 2024, using filings published by February 28, 2025. Each number keeps its actual reporting date, even when it is older than the target quarter. Competitor NAV history covers eight quarter-end observations; other metrics use the latest supported values. The project owner authorized the supplied Apex Ridge CSV for this prototype: Q4 2024 metrics and Q1-Q4 2024 NAV history are included; 2025 rows are excluded.'),
        section('1. Find the filings',
            'The Python service connects to SEC EDGAR, lists filings by fund identifier (CIK), and downloads eligible reports, supplements and exhibits. It uses a declared contact, rate limiting and bounded retries. The fund browser lets a user search for another fund and specify its structure and share class before adding it.'),
        section('2. Parse once and save the source',
            'HTML tables, narrative text, footnotes and PDF text become a reusable passage index. I save the original documents, their SHA-256 fingerprints and source locations alongside it. PDF citations use page numbers; HTML citations use table or text locations. N-PORT XML has dedicated field mappings and balance checks. Scanned PDF pages can use local OCR, but their numbers require visual confirmation.'),
        section('3. Retrieve evidence for one question',
            'A metric definition identifies relevant passages from the saved index. The retrieval step preserves table headings and nearby footnotes. For effective fees, it removes repeated context and excludes unrelated legal waiver language. Custom metrics use a user-written definition, units, scope and search phrases; they currently support reported values, not arbitrary formulas.'),
        section('4. Let the LLM interpret; let code check',
            'GPT-6.1 Sol receives the evidence and comparison rules for one result. It selects a value or explains why it cannot, with numbered source references. Code then checks those references and the proposed dates, units and calculations. The next page describes that division of work.'),
        section('5. Save the decision, then produce the report',
            'The board Word copy shows comparisons, observation dates and PM-authored commentary. The separate compliance copy and dashboard retain sources, definitions and rationales. Both read saved decisions. CSV, PDF and JSON exports are also available. Opening a report or downloading Word does not call the model or repeat extraction.'),
        PageBreak(),
        para('Validation strategy and confidence', 'title'),
        para('Without an answer key, confidence comes from evidence, reconciliation and explicit review.', 'sub'),
        section('What the LLM is responsible for',
            'Sol interprets public SEC disclosures and explains its choice through structured responses. I do not treat its self-assessed confidence as proof. Each selected figure must survive source, period, definition and arithmetic checks; competing disclosures remain visible. One initial model review is followed by code checks, with one correction attempt if needed. Both attempts are retained.'),
        section('What the code verifies',
            'The model selects numbered passages; code restores their exact saved text. It checks source fingerprints, filing dates, values, periods, units and share classes. Calculations must use implemented formulas with cited inputs. Reconciliations check N-PORT assets minus liabilities against net assets, compound annual return chains, and distinguish rounding differences from conflicting figures. These checks do not prove every interpretation is right.'),
        section('How confidence appears in the output',
            'I use evidence status and a written rationale, not high/medium/low grades. A supported value has source links. A blank distinguishes no retrieved evidence, unfinished or failed review, and a reviewed but unestablished value. A failed search is not labeled "not disclosed."'),
        para('A concrete example: Golub management fees', 'heading'),
        grid(['Disclosure', 'Figure', 'How it is treated'], [
            ['Contractual management fee', '1.00%', 'Kept as the primary contractual rate, on average adjusted gross assets.'],
            ['Annual management-fee expense ratio', '1.56%', 'Separate effective-fee observation for September 30, 2024, on period-end net assets attributable to common stock.'],
            ['Older expense table in a prospectus', '2.75%', 'Not selected: its footnote refers to March 2022 and excludes a one-time waiver.'],
        ], [145, 53, WIDTH-198]),
        Spacer(1, 8),
        para('Sol selected 1.56% with the older date and different denominator. This single-case trial does not establish overall financial accuracy.'),
        para('Sources: Golub\'s <link href="https://www.sec.gov/Archives/edgar/data/1476765/000147676524000132/gbdc-20240930.htm" color="#22675D">2024 annual report, Fees and Expenses, footnote 4</link>, and <link href="https://www.sec.gov/Archives/edgar/data/1476765/000110465924123193/gbdc-20241125xn2.htm" color="#22675D">November 2024 prospectus, fee-table footnote 4</link>. Full passages and the trial result are retained in the audit.', 'small'),
        section('When two figures really conflict',
            'Different periods or fee bases may explain a difference. Temporary waivers retain their stated expiration. For the same measure, period and class, the model needs an explicit correction or explanation; a newer filing alone is not enough. Unresolved conflicts show both figures and citations for PM review, with no accepted value.'),
        PageBreak(),
        para('Storage and production design', 'title'),
        para('Current file layout, the core records, and a path to a shared service.', 'sub'),
        section('Current storage and schema',
            'The current implementation uses files, not a database. Original filings live in .cache/sec/, named by content hash, with JSON metadata mapping URLs to files. Separate folders hold passages and model decisions. Each report\'s audit.json captures its configuration, results, history, evidence and errors. Its logical schema is:'),
        grid(['Record', 'Key fields and relationships'], [
            ['Filing and document', 'Fund CIK, accession, form, filing/reporting dates, URL and content hash. A filing has one or more documents.'],
            ['Passage', 'ID tied to document hash and parser version; text, table rows, headings and source locator.'],
            ['Decision', 'Fund, metric, period, value, unit, basis, class, evidence IDs, rationale, validation status and model provenance.'],
        ], [116, WIDTH-116]),
        Spacer(1, 8),
        para('Cache keys include evidence, comparison rules and model. Metric edits reuse parsed documents and review only affected results, with three concurrent workers by default. Exports read saved decisions.'),
        section('Proposed production storage',
            'I would use PostgreSQL for funds, filings, versioned metric definitions, decisions and approvals. Citation records would link decisions to passages and documents; versioned object storage would hold original filings and exports. Decisions would be appended, preserving approved history, and reports would reference specific decision versions. This production design is proposed, not implemented.'),
        para('Validation and remaining work', 'heading'),
        section('What has been checked',
            'The saved-run validator replayed checks for 73 displayed competitor values, verified 48 original source hashes, and independently recomputed nine calculations and 28 N-PORT balance reconciliations. All passed. It retained 32 gaps without claiming non-disclosure. Regression tests reject altered files, invented citations, wrong dates, changed values, truncated evidence and published conflicts. The replay also exposed an overbroad hurdle rule, now corrected and tested.'),
        section('Before production',
            'Confirm the internal source with the client for production, complete a full Sol run and compare a quarterly package with the analyst\'s work. These replay checks are not independent proof of financial accuracy or retrieval completeness. A human-checked set of present, absent, conflicting and unreadable disclosures is still needed to measure missed figures and interpretation accuracy. Unfamiliar layouts and OCR still require review; arbitrary custom calculations are not supported. Add authenticated approvals, backups and alerts for failed retrieval or model calls before routine use.'),
        para('Implementation: src/apex_benchmark/. Measured runs and validation records: docs/.', 'small'),
    ]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=54, rightMargin=54, topMargin=55, bottomMargin=48)
    def frame(canvas, doc):
        canvas.setStrokeColor(ACCENT); canvas.setLineWidth(2)
        canvas.line(54, A4[1]-34, A4[0]-54, A4[1]-34)
        canvas.setStrokeColor(LINE); canvas.setLineWidth(.5)
        canvas.line(54, 35, A4[0]-54, 35)
        canvas.setFont('Helvetica', 8); canvas.setFillColor(MUTED)
        canvas.drawString(54, 22, 'APEX RIDGE CAPITAL  /  TECHNICAL APPROACH')
        canvas.drawRightString(A4[0]-54, 22, f'{doc.page} / 3')
    doc.build(story, onFirstPage=frame, onLaterPages=frame)


if __name__ == '__main__':
    build_technical()
    print('Wrote docs/technical-approach.pdf')
