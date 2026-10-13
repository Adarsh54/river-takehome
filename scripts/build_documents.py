"""Build fixed-length client documents. No network or competitor data fabrication."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from html import escape as esc

ROOT = Path(__file__).resolve().parents[1]
from technical_report import build_technical

BUSINESS = [
('Apex Ridge | Solution brief', '1 / A reviewable quarterly comparison', [
('The outcome', 'We built a benchmarking prototype that brings Apex Ridge and its competitors into a single comparison, supported by the original disclosures. It replaces much of the repeated filing search and manual transcription with a prepared comparison for analyst review. The intended benefit is less time assembling numbers and a clearer basis for checking them before they reach the board. The PM retains responsibility for interpreting the comparison; compliance retains responsibility for verifying the figures used in publication.'),
('What has been delivered', 'The prototype retrieves real SEC filings and extracts returns, fees, NAV per share, leverage and distributions. It records the evidence and explanation behind each selected value, accounts for differences in reporting periods and definitions, and compares the results with Apex Ridge internal figures. The expanded scope is also delivered: a searchable SEC fund browser, user-defined metrics and formatted Word output. New questions can be investigated without rebuilding the existing comparison from scratch.'),
('What the board receives', 'The current peer group fits in a one-page Word comparison, with Apex Ridge alongside the competitors. It shows trailing net returns against Cliffwater and Carlyle, fees, per-share values and their history, leverage and distribution rates. Apex Ridge figures are labeled as internal. Each current figure carries its observation date in the table, so a reporting lag is visible. The PM supplies two or three sentences on relative performance and matters for discussion. Sources, filing dates, methodology and detailed qualifications stay in the separate compliance copy and working file.'),
('What changes each quarter', 'The analyst sets the comparison period and peer group, then reviews the prepared results and investigates gaps or conflicting disclosures. The PM reviews the comparison and writes the board narrative. Compliance follows the retained references to the original sources. This shifts the work from finding and retyping every number toward reviewing the evidence and resolving exceptions. Existing source material and decisions are reused when relevant, so a new metric does not force a complete restart.'),
('The first comparison', 'The initial cycle is Q4 2024, using competitor filings available through February 28, 2025. The supplied Apex Ridge file provides Q4 2024 metrics and four quarters of 2024 NAV history; later rows are excluded. Competitor history covers up to eight quarter-ends, with gaps left visible. The different history lengths and observation dates are preserved rather than filled with assumed values.')]),
('Apex Ridge | Solution brief', '2 / Business choices and the path to routine use', [
('Evidence before completeness', 'A figure that cannot be located in its source is excluded from the comparison and publication outputs. The working file keeps the reason for the exclusion. An unsuccessful search alone does not establish that a report omitted a metric; incomplete searches and unresolved interpretations remain review work. The prototype blocks package downloads until both PM and compliance approvals are recorded for the exact version. Changing the report requires renewed approval.'),
('Consistency without false equivalence', 'Contractual management fees are the primary comparison; disclosed effective fees and temporary waivers are retained separately for review. Net fund returns are compared with the interval funds, while listed-vehicle shareholder returns remain available in the working comparison. KREF stays in the peer group because it matters to Apex Ridge investors, with its book-value measure identified. Differences in fee bases, borrowing definitions and distributions remain matters for PM review. A common table does not make unlike measures interchangeable.'),
('Tradeoffs made for this delivery', 'We prioritized a usable comparison, traceable evidence and a portable board document over a hosted service. AI helps interpret disclosures, but its decisions still require review; unfamiliar tables, scanned pages and ambiguous definitions can leave gaps. Custom metrics support disclosed figures with a defined comparison basis, rather than any formula a user might request. Updates reuse prior work, but first-time fund research can take longer. We have not yet established the total time saved or the rate at which the system misses disclosed figures through a full quarterly comparison with the analyst.'),
('Production rollout', 'Start with one quarterly cycle alongside the existing analyst process. Use independently checked examples to test correct figures, difficult disclosures and genuinely absent information; measure missed figures, citation accuracy and review effort. The PM and compliance leads should agree acceptance criteria before routine use. Then move to a shared service with authenticated reviewer roles, controlled access to documents, retained approval records, backups and alerts for failed runs. The local prototype records named attestations and locks website downloads; production must also control access to the underlying files.'),
('The decision after the pilot', 'Adopt the workflow once the team can demonstrate that the comparison is accurate enough for its intended use, exclusions are handled consistently, and review takes less effort than the current process. Expand the fund and metric set as those checks hold. The business case is a repeatable quarterly process with fewer opportunities for unnoticed transcription errors and evidence ready for compliance, while investment conclusions remain with the PMs.')])]



def build(pages, path):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('Deck', fontName='Helvetica', fontSize=10.5, leading=14.5, spaceAfter=10))
    styles['Heading2'].textColor = colors.HexColor('#18574b')
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=46, rightMargin=46, topMargin=40, bottomMargin=44)
    story = []
    for i, (title, subtitle, sections) in enumerate(pages):
        if i:
            story.append(PageBreak())
        story += [Paragraph(esc(title), styles['Title']), Paragraph(esc(subtitle), styles['Heading2']), Spacer(1,8)]
        for heading, text in sections:
            story += [Paragraph(esc(heading), styles['Heading3']), Paragraph(esc(text), styles['Deck'])]
    def footer(canvas, doc):
        canvas.setFont('Helvetica',8)
        canvas.setFillColor(colors.HexColor('#647570'))
        canvas.drawString(46, 24, 'APEX RIDGE | Prototype handoff | Financial validation in progress')
        canvas.drawRightString(A4[0]-46, 24, str(doc.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == '__main__':
    build_technical(ROOT/'docs/technical-approach.pdf')
    build(BUSINESS, ROOT/'docs/solution-brief.pdf')
    print('Wrote technical approach and solution brief')
