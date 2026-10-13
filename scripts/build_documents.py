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
('What has been delivered', 'The requested benchmarking capabilities are in place: retrieval of public SEC filings, a comparison of returns, fees, per-share value, borrowing and distributions, and source references with an explanation of the evidence behind each reported figure. PMs can search for additional funds and define new metrics as their questions change. The comparison is available on screen and as a formatted Word document for the quarterly package. The first cycle covers Q4 2024 using filings available by February 28, 2025.'),
('What a reviewer sees', 'A figure appears with its reporting date and evidence status. Figures without verifiable sources are excluded from the comparison and board package. The review screen retains the explanation for the gap. The reviewer sees whether the number has locatable evidence, why the AI selected it and what remains unresolved, then can inspect the original source and record an interpretation. Missing access is distinguished from missing disclosure. The portable report keeps the same qualifications as the review screen; exporting does not erase the caveats.'),
('Choices that improve consistency', 'Contractual fees are shown separately from disclosed effective fees and temporary waivers. Golub and KREF use investor shareholder returns, while interval funds use the applicable net fund return. KREF remains in the peer group because clients benchmark against it, but its real-estate structure is explicit. Different borrowing and distribution definitions are not presented as automatically equivalent.'),
('Source verification and approval', 'Every reported figure must be traceable to the original filing. If a figure cannot be located in its original filing, it is dropped from the comparison and all published outputs. Only an explanation of the exclusion remains; the unverified number is not carried forward. An unsuccessful search is not enough to conclude "not disclosed": that requires confirmation against the report, including the relevant tables and footnotes. Publication is blocked until both the PM and compliance approve the exact report version. Any change to the report invalidates those approvals and requires a new review.')]),
('Apex Ridge | Solution brief', '2 / Using the comparison in the quarterly cycle', [
('Set the comparison', 'The analyst selects the peer group and the date through which public filings may be used, then runs the comparison. To include another fund, search for it in the fund browser and add it to the group. To answer a new question, define the metric and the basis for comparison. For example, a spread comparison should specify the reference interest rate and whether fees are deducted. Those choices determine whether the figures can be compared fairly.'),
('Read the results', 'Start with the side-by-side comparison for current figures, then use the per-share value history to see how each fund has changed over time. Check the reporting dates: funds publish on different schedules, so the latest available figures may cover different periods. Read the labels and accompanying explanations before drawing conclusions. A contractual fee and a fee actually charged, for example, answer different questions even when both are correct.'),
('Review the evidence and exceptions', 'Each reported value carries a source reference and an explanation of its support. Follow the reference to check the original filing. A blank is not zero: its explanation identifies what could not be established or verified. Where disclosures disagree, review the competing figures and the reason for the selection, or the unresolved issue. The PM decides which gaps need further investigation. Compliance confirms every included figure against its original source; any figure that cannot be located is removed before approval.'),
('Use the Word package', 'After both approvals are recorded, download the formatted Word report for the quarterly board materials and investor reporting. It carries the comparison, reporting dates, source references and qualifications into a document that can travel with the package. Keep those labels and qualifications with any figures copied into a board deck or investor letter. Downloading a report uses the saved comparison; it does not commission another review. Word, PDF and CSV package downloads remain locked until both approvals are recorded for that version.'),
('Put it into the quarterly process', 'Begin with one quarterly cycle alongside the existing analyst review, and agree that the evidence and presentation meet PM and compliance needs before making it routine. The main change is where the team spends its time: reviewing the comparison and investigating exceptions instead of repeatedly finding and retyping numbers. The initial delivery keeps that review with the existing team; a wider rollout must add authenticated reviewer accounts and shared access.')])]



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
