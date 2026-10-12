"""Build the technical handoff as a plain 12-point Times New Roman Word document."""
from pathlib import Path
import shutil
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT

ROOT = Path(__file__).resolve().parents[1]
WIDTH = 451.28

def para(text, style='body'): return ('paragraph', text, style)
def section(title, text): return ('section', title, text)
def grid(headers, rows, widths): return ('table', headers, rows, widths)
def Spacer(width, height): return ('space',)
def PageBreak(): return ('break',)

def content():
    return [
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

def font(run, bold=False):
    run.font.name = 'Times New Roman'
    run.font.size = Pt(12)
    run.font.bold = bold
    run.font.italic = False
    run.font.color.rgb = RGBColor(0, 0, 0)
    fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    for kind in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
        fonts.set(qn('w:' + kind), 'Times New Roman')


def text_runs(paragraph, text, bold=False):
    root = ET.fromstring('<root>' + text.replace('&', '&amp;') + '</root>')
    if root.text: font(paragraph.add_run(root.text), bold)
    for child in root:
        if child.tag == 'link':
            link = OxmlElement('w:hyperlink')
            link.set(qn('r:id'), paragraph.part.relate_to(child.attrib['href'], RT.HYPERLINK, is_external=True))
            run = paragraph.add_run(''.join(child.itertext()));font(run, bold)
            run.font.underline = True
            link.append(run._element);paragraph._p.append(link)
        else: font(paragraph.add_run(''.join(child.itertext())), bold)
        if child.tail: font(paragraph.add_run(child.tail), bold)


def build_docx(path=ROOT/'docs/technical-approach.docx'):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Inches(8.2677);sec.page_height = Inches(11.6929)
    sec.top_margin = sec.bottom_margin = sec.left_margin = sec.right_margin = Inches(1)
    sec.footer_distance = Inches(.5)
    for style in doc.styles:
        for node in list(style.element.iter()):
            if node.tag == qn('w:pBdr') or (node.tag == qn('w:spacing') and node.getparent().tag == qn('w:rPr')):
                node.getparent().remove(node)
    for name in ('Normal', 'Title', 'Subtitle', 'Heading 1', 'Heading 2'):
        style = doc.styles[name]
        style.font.name = 'Times New Roman';style.font.size = Pt(12)
        style.font.color.rgb = RGBColor(0,0,0)
        style.font.bold = name in ('Title','Heading 1','Heading 2')
        style.font.italic = False
        style.paragraph_format.line_spacing = 1
        style.paragraph_format.space_before = Pt(0)
        style.paragraph_format.space_after = Pt(6)
    doc.styles['Heading 2'].paragraph_format.space_before = Pt(5)
    doc.styles['Heading 2'].paragraph_format.keep_with_next = True
    for item in content():
        if item[0] == 'break': doc.add_page_break()
        elif item[0] == 'space': continue
        elif item[0] == 'section':
            text_runs(doc.add_paragraph(style='Heading 2'), item[1], True)
            text_runs(doc.add_paragraph(), item[2])
        elif item[0] == 'paragraph':
            kind = item[2]
            style = {'title':'Title','heading':'Heading 2','sub':'Subtitle'}.get(kind,'Normal')
            p = doc.add_paragraph(style=style)
            text_runs(p,item[1],kind in ('title','heading'))
        elif item[0] == 'table':
            headers, rows, widths = item[1:]
            t = doc.add_table(rows=1, cols=len(headers));t.alignment = WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
            for col,w in zip(t.columns,widths):col.width=Pt(w)
            for ri, values in enumerate([headers]+rows):
                cells = t.rows[0].cells if ri==0 else t.add_row().cells
                for ci,(cell, txt) in enumerate(zip(cells,values)):
                    cell.width = Pt(widths[ci]);cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    p=cell.paragraphs[0];p.paragraph_format.space_after=Pt(0)
                    if ci==1:p.alignment=WD_ALIGN_PARAGRAPH.CENTER
                    text_runs(p,txt,ri==0)
                    tcpr=cell._tc.get_or_add_tcPr()
                    borders=OxmlElement('w:tcBorders')
                    for edge in ('top','left','bottom','right'):
                        b=OxmlElement('w:'+edge);b.set(qn('w:val'),'single');b.set(qn('w:sz'),'4');b.set(qn('w:color'),'D9D9D9');borders.append(b)
                    tcpr.append(borders)
                    margin=OxmlElement('w:tcMar')
                    for side in ('top','left','bottom','right'):
                        m=OxmlElement('w:'+side);m.set(qn('w:w'),'75');m.set(qn('w:type'),'dxa');margin.append(m)
                    tcpr.append(margin)
                    if ri==0:
                        shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'F2F2F2');tcpr.append(shade)
                rowpr=t.rows[ri]._tr.get_or_add_trPr();rowpr.append(OxmlElement('w:cantSplit'))
                if ri==0:rowpr.append(OxmlElement('w:tblHeader'))
            doc.add_paragraph().paragraph_format.space_after=Pt(0)
    p=sec.footer.paragraphs[0];p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=p.add_run('1');font(r)
    f=OxmlElement('w:fldSimple');f.set(qn('w:instr'),'PAGE');f.append(r._r);p._p.append(f)
    doc.core_properties.title='Apex Ridge Capital Technical Approach'
    doc.core_properties.author=''
    doc.save(path)
    return Path(path)


def build_technical(path=ROOT/'docs/technical-approach.pdf'):
    """Regenerate editable Word and its matching PDF; requires LibreOffice."""
    path=Path(path);docx=build_docx(path.with_suffix('.docx'))
    bundled=Path(sys.executable).parents[2]/'bin/override/soffice'
    soffice=str(bundled) if bundled.exists() else shutil.which('soffice')
    if not soffice:raise RuntimeError('Word saved. Install LibreOffice to export the matching PDF.')
    with tempfile.TemporaryDirectory() as directory:
        tmp=Path(directory)
        env=os.environ.copy()
        if bundled.exists() and Path('/System/Library/Fonts/Supplemental/Times New Roman.ttf').exists():
            config=tmp/'fonts.conf'
            config.write_text('<fontconfig><dir>/System/Library/Fonts/Supplemental</dir><cachedir>'+str(tmp/'font-cache')+'</cachedir></fontconfig>')
            env['FONTCONFIG_FILE']=str(config)
        subprocess.run([soffice,'-env:UserInstallation='+ (tmp/'profile').as_uri(), '--headless', '--convert-to', 'pdf', '--outdir', str(tmp), str(docx.resolve())],check=True,capture_output=True,env=env)
        shutil.copy2(tmp/(docx.stem+'.pdf'),path)


if __name__ == '__main__':
    if '--word-only' in sys.argv: build_docx()
    else: build_technical()
    print('Wrote technical approach')
