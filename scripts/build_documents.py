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
('Apex Ridge | Solution brief', '1 / What changes for the quarterly workflow', [
('The business need', 'Analysts currently read lengthy competitor filings and retype figures into a comparison. A PM checks plausibility; compliance must locate every board figure in its original filing. The error risk sits between source interpretation and the populated table. The proposed system makes that step visible and reviewable, while retaining both human approval gates.'),
('What the prototype provides', 'A local tool discovers SEC filings and gathers supporting passages. An AI reviewer interprets disclosures and explains which figures it selected or withheld; source checks constrain what can enter the comparison. The review screen links each supported value to its source. A formatted Word document travels with the quarterly package. PMs can search SEC registrants, add peers and define new metrics without code. PDF and CSV remain available. A machine-readable audit record preserves decisions, structured portfolio data and scanned-page evidence. The first cycle is Q4 2024 using filings available by February 28, 2025.'),
('What a reviewer sees', 'A figure appears with its reporting date and evidence status. Unclear or conflicting figures appear as visible review items, not confident guesses. The reviewer sees whether the number has locatable evidence, why the AI selected it and what remains unresolved, then can inspect the original source and record an interpretation. Missing access is distinguished from missing disclosure. The portable report keeps the same qualifications as the review screen; exporting does not erase the caveats.'),
('Choices that improve consistency', 'Contractual fees are shown separately from disclosed effective fees and temporary waivers. Golub and KREF use investor shareholder returns, while interval funds use the applicable net fund return. KREF remains in the peer group because clients benchmark against it, but its real-estate structure is explicit. Different borrowing and distribution definitions are not presented as automatically equivalent.'),
('Source verification and approval', 'Every reported figure must be traceable to the original filing. If a value cannot be located or verified, it stays blank with an explanation. An unsuccessful search is not enough to conclude "not disclosed": that requires confirmation against the report, including the relevant tables and footnotes. Unresolved cases remain flagged for review. The package still requires PM and compliance approval before it is used in board or investor communications.')]),
('Apex Ridge | Solution brief', '2 / Rollout, tradeoffs and decisions', [
('First operational run', 'Review the downloaded filings and check the extracted passages against originals, including fee waivers and differences between investor returns and underlying asset returns. Apex Ridge internal figures remain withheld until Dana confirms the authoritative source. Then present a populated example to the PM and compliance team; check the Word package and agree what needs attention in review.'),
('Quarterly process', 'An operator runs the tool for the agreed preparation date. The analyst reviews highlighted exceptions and records interpretations instead of silently retyping figures. The PM reviews the comparison and material differences. Compliance follows the original filing references. Only after those approvals does the package enter board or investor communications. The tool supports this workflow; it does not replace professional judgment.'),
('History and scope', 'The requested competitor history is eight quarter-end per-share observations. The current approved scope for Apex history would start in Q1 2024 and end in Q4 2024 once source approval is obtained; it will not be padded. Other measures are latest supported values for the cycle. Older competitor periods stay labeled so the board can see reporting lags.'),
('Tradeoffs', 'The prototype prioritizes defensible evidence and explicit gaps over filling every cell. Complex tables and narrative terms may still require manual confirmation, and updates to indexed funds target five minutes, with source, AI and export timings recorded separately; cold ingestion and provider delays remain variable. A local tool keeps operation simple but requires an operator; it is not yet a hosted, scheduled or authenticated multi-user service. The requested Word output is implemented. Custom metrics require precise definitions and disclosed values; new peers may expose unfamiliar layouts and need more review. No arbitrary custom calculations are promised.'),
('Path to production', 'Use a complete quarterly cycle to measure source coverage, extraction accuracy and time spent reviewing exceptions. Add rules for recurring fund-specific layouts, then automate scheduling and alerts. Introduce controlled access, signed approvals and retained evidence packages before routine publication. Production readiness requires reliable live retrieval, approved internal data, demonstrated financial accuracy and agreement from the PM and compliance owners.')])]


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
