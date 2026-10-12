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
            'The comparison is for Q4 2024, using filings published by February 28, 2025. Each number keeps its actual reporting date, even when it is older than the target quarter. Competitor NAV history covers eight quarter-end observations; other metrics use the latest supported values. Apex Ridge\'s supplied figures remain withheld because Dana disputed their provenance.'),
        section('1. Find the filings',
            'The Python service connects to SEC EDGAR, lists filings by fund identifier (CIK), and downloads eligible reports, supplements and exhibits. It uses a declared contact, rate limiting and bounded retries. The fund browser lets a user search for another fund and specify its structure and share class before adding it.'),
        section('2. Parse once and save the source',
            'HTML tables, narrative text, footnotes and PDF text become a reusable passage index. I save the original documents, their SHA-256 fingerprints and source locations alongside it. PDF citations use page numbers; HTML citations use table or text locations. N-PORT XML has dedicated field mappings and balance checks. Scanned PDF pages can use local OCR, but their numbers require visual confirmation.'),
        section('3. Retrieve evidence for one question',
            'A metric definition identifies relevant passages from the saved index. The retrieval step preserves table headings and nearby footnotes. For effective fees, it removes repeated context and excludes unrelated legal waiver language. Custom metrics use a user-written definition, units, scope and search phrases; they currently support reported values, not arbitrary formulas.'),
        section('4. Let the LLM interpret; let code check',
            'GPT-6.1 Sol receives the evidence and comparison rules for one result. It selects a value or explains why it cannot, with numbered source references. Code then checks those references and the proposed dates, units and calculations. The next page describes that division of work.'),
        section('5. Save the decision, then produce the report',
            'The dashboard and formatted Word package read saved decisions. Each result retains its source, date, financial definition and rationale. CSV, PDF and JSON exports are also available. Opening a report or downloading Word does not call the model or repeat extraction.'),
        PageBreak(),
        para('Selecting and checking values', 'title'),
        para('The model makes the interpretation visible. It does not approve the board package.', 'sub'),
        section('What the LLM is responsible for',
            'Sol interprets the disclosures, compares competing figures and explains its choice. It uses OpenAI\'s Responses API with structured JSON output and store=false. Only public SEC evidence enters requests. Each affected result gets one initial review; there is no routine second LLM verifier. A failed code check permits one correction attempt, with both attempts retained.'),
        section('What the code verifies',
            'The model selects numbered passages; code restores their exact saved text. It checks source fingerprints, filing dates, values, periods, units and share classes. Calculations must use implemented formulas with cited inputs. These checks catch invalid references and unsupported calculations, but cannot prove every financial interpretation is right.'),
        section('How confidence appears in the output',
            'I use evidence status and a written rationale, not high/medium/low grades. A supported value has source links. A blank distinguishes no retrieved evidence, unfinished or failed review, and a reviewed but unestablished value. A failed search is not labeled "not disclosed."'),
        para('A concrete example: Golub management fees', 'heading'),
        grid(['Disclosure', 'Figure', 'How it is treated'], [
            ['Contractual management fee', '1.00%', 'Kept as the primary contractual rate, on average adjusted gross assets.'],
            ['Annual management-fee expense ratio', '1.56%', 'Separate effective-fee observation for September 30, 2024, on period-end net assets attributable to common stock.'],
            ['Older expense table in a prospectus', '2.75%', 'Not selected: its footnote refers to March 2022 and excludes a one-time waiver.'],
        ], [145, 53, WIDTH-198]),
        Spacer(1, 8),
        para('Sol selected 1.56% with the older date and different denominator; GPT-5.4 had withheld it. That is an improvement in one case, not a general accuracy claim.'),
        para('Sources: Golub\'s <link href="https://www.sec.gov/Archives/edgar/data/1476765/000147676524000132/gbdc-20240930.htm" color="#22675D">2024 annual report, Fees and Expenses, footnote 4</link>, and <link href="https://www.sec.gov/Archives/edgar/data/1476765/000110465924123193/gbdc-20241125xn2.htm" color="#22675D">November 2024 prospectus, fee-table footnote 4</link>. Full passages and the trial result are retained in the audit.', 'small'),
        section('When two figures really conflict',
            'Different periods or fee bases may explain a difference. Temporary waivers retain their stated expiration. For the same measure, period and class, the model needs an explicit correction or explanation; a newer filing alone is not enough. Unresolved conflicts show both figures and citations for PM review, with no accepted value.'),
        PageBreak(),
        para('Validation and remaining work', 'title'),
        para('Measured behavior, current limits, and the steps I would take before production.', 'sub'),
        section('Small changes should stay small',
            'Changing a custom metric searches saved passages and reviews only that metric. Adding a fund processes that fund; an SEC refresh compares filing inventories before ingesting changes. Independent reviews run with a limit of three concurrent requests by default. Decisions are checkpointed for reuse. Changing the default model does not silently rerun existing decisions; those keep their original model provenance.'),
        para('Measured runs', 'heading'),
        grid(['Operation', 'Time', 'Work performed'], [
            ['Unchanged SEC refresh', '4.8 sec', '267 unchanged filings reused; no parsing or AI calls.'],
            ['Spread-only metric update', '17.6 sec', '3 model calls; no parsing; 100 other results unchanged.'],
            ['GBDC effective-fee trial with Sol', '18.9 sec', '1 model call; no parsing; 104 other results unchanged.'],
        ], [166, 62, WIDTH-228]),
        Spacer(1, 8),
        para('These are measured updates to already indexed funds, not a guarantee that a new fund can be ingested in five minutes. The Sol trial cost an estimated $0.44. GPT-5.4 took 12.6 seconds on the fee case, so Sol improved that interpretation but was not faster.', 'small'),
        section('How I tested without an answer key',
            'The 143 passing tests cover source validation, dates, classes, tables, numeric punctuation, calculations, conflicts and reuse. I checked real disclosures and corrected errors, including a hurdle rate mistaken for an incentive fee. N-PORT checks reconcile assets less liabilities to net assets. The main report has 41/65 current values and 32/40 historical observations with evidence; the separate Sol trial adds one current value. Coverage is not accuracy. A full Sol rerun remains outstanding.'),
        section('Limits that still matter',
            'Search phrases and unfamiliar layouts can leave relevant evidence undiscovered; a complete selected packet does not mean the model read every filing. OCR still needs human review. Fee, leverage and distribution definitions are not always comparable across funds. Listed vehicles use shareholder returns, interval funds use net NAV returns, and KREF is a mortgage REIT. Custom XML mappings and arbitrary custom calculations are not implemented. SEC or model failures remain visible review items.'),
        section('What I would do before production',
            'Resolve Apex Ridge\'s data with Dana, then run a quarter alongside the analyst with Sol. Have the PM and compliance check sampled values and material exceptions to measure accuracy and review effort. Before routine use, add authenticated approvals, versioned source storage and failure alerts. Today, review decisions are recorded locally.'),
        para('Reproduce the runs using README.md. Timing and validation records: docs/incremental-validation.json, docs/gap-repair-validation.json and docs/sol61-model-trial.json.', 'small'),
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
