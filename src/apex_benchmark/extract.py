"""Conservative deterministic extraction with reproducible source locators."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from decimal import Decimal, InvalidOperation
from io import BytesIO
import hashlib
import re
from bs4 import BeautifulSoup
from pypdf import PdfReader

METRICS = {
    'return_1y': 'Return, trailing 1 year (%)',
    'return_3y': 'Return, trailing 3 years, annualized (%)',
    'return_5y': 'Return, trailing 5 years, annualized (%)',
    'management_fee': 'Management fee, contractual (%)',
    'effective_fee': 'Management fee, effective (%)',
    'incentive_fee': 'Incentive fee (%)',
    'hurdle': 'Incentive hurdle (%)',
    'nav': 'NAV / book value per common share (USD)',
    'leverage': 'Debt / equity (x), stated basis',
    'distribution_yield': 'Distribution rate / yield (%)',
}
KEYWORDS = {
    'return_1y': r'total (?:shareholder )?returns?|average annual',
    'return_3y': r'total (?:shareholder )?returns?|average annual',
    'return_5y': r'total (?:shareholder )?returns?|average annual',
    'management_fee': r'(?:base )?management fee|advisory fee',
    'effective_fee': r'waiv|waiver|reimburse|expense limit',
    'incentive_fee': r'incentive fee|carried interest',
    'hurdle': r'hurdle|preferred return',
    'nav': r'net asset value|book value per (?:common )?share',
    'leverage': r'debt.to.equity|leverage ratio',
    'distribution_yield': r'distribution (?:rate|yield)|dividend yield',
}


def clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def number(text):
    text = clean(text).replace(',', '').replace('$', '').replace('%', '').replace('\u2212', '-')
    if text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1]
    try:
        value = Decimal(text)
        return float(value) if value.is_finite() else None
    except InvalidOperation:
        return None


@dataclass
class Candidate:
    ticker: str
    metric: str
    value: float | None
    unit: str
    period: str
    basis: str
    share_class: str
    filing_date: str
    form: str
    accession: str
    source_url: str
    source_sha256: str
    locator: str
    quote: str
    method: str
    eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    id: str = ''

    def __post_init__(self):
        if not self.id:
            identity = '|'.join(map(str, [self.ticker, self.metric, self.value, self.period,
                self.accession, self.filing_date, self.source_url,
                self.source_sha256, self.locator, self.method]))
            self.id = hashlib.sha256(identity.encode()).hexdigest()[:20]

    def dict(self):
        return asdict(self)


def candidate(fund, filing, source, metric, value, locator, quote, method, **kwargs):
    return Candidate(ticker=fund['ticker'], metric=metric, value=value,
        unit='USD/share' if metric == 'nav' else 'x' if metric == 'leverage' else '%',
        period=kwargs.pop('period', filing.get('reportDate', '')),
        basis=kwargs.pop('basis', 'unconfirmed'), share_class=kwargs.pop('share_class', 'unconfirmed'),
        filing_date=filing['filingDate'], form=filing['form'], accession=filing['accessionNumber'],
        source_url=source['url'], source_sha256=source['sha256'], locator=locator,
        quote=quote, method=method, **kwargs)


def documents_from_submission(body: bytes, primary_url: str):
    """Split complete EDGAR submission, retaining the real URL of each exhibit."""
    text = body.decode('utf-8', errors='replace')
    parts = re.findall(r'<DOCUMENT>(.*?)</DOCUMENT>', text, re.S | re.I)
    if not parts:
        return [(primary_url, body)]
    result = []
    for part in parts:
        name = re.search(r'<FILENAME>([^\r\n]+)', part, re.I)
        content = re.search(r'<TEXT>(.*?)</TEXT>', part, re.S | re.I)
        if not name or not content:
            continue
        filename = name.group(1).strip()
        if filename.lower().endswith(('.htm', '.html', '.xml', '.txt')):
            result.append((primary_url.rsplit('/', 1)[0] + '/' + filename,
                           content.group(1).encode()))
    return result


def parse_document(body, fund, filing, source):
    if body.startswith(b'%PDF'):
        snippets = [(f'PDF page {i+1}', clean(p.extract_text() or ''))
                    for i, p in enumerate(PdfReader(BytesIO(body)).pages)]
        return narrative(snippets, fund, filing, source)
    if source['url'].lower().endswith('.xml'):
        # XML financial instances/label dictionaries are not prose. The accompanying
        # inline-XBRL HTML is parsed separately. N-PORT needs a dedicated schema mapping.
        return []
    soup = BeautifulSoup(body, 'lxml')
    results = inline_facts(soup, fund, filing, source)
    results.extend(dated_per_share_tables(soup, fund, filing, source))
    # Give every source block a reproducible sequential locator; no invented PDF page numbers.
    blocks = soup.find_all(['p', 'tr', 'div'])
    snippets = []
    for i, block in enumerate(blocks):
        if block.name == 'tr' and block.find('table'):
            continue
        if block.name == 'div' and block.find(['p', 'tr', 'div']):
            continue
        text = clean(block.get_text(' ', strip=True))
        if len(text) >= 15:
            anchor = block.get('id') or block.get('name')
            locator = f'HTML block {i+1}' + (f'; anchor #{anchor}' if anchor else '')
            snippets.append((locator, text))
    if not snippets:
        snippets = [('Document text', clean(soup.get_text(' ', strip=True)))]
    results.extend(narrative(snippets, fund, filing, source))
    results.extend(return_tables(soup, fund, filing, source))
    return list({c.id: c for c in results}.values())


def dated_per_share_tables(soup, fund, filing, source):
    """Map exact date-header column spans, never guess first/last numeric column."""
    if fund['structure'] != 'mortgage_reit' or filing['form'].removesuffix('/A') not in {'10-K', '10-Q'}:
        return []
    from datetime import datetime
    results = []
    for table_number, table in enumerate(soup.find_all('table'), 1):
        if table.find('table'):
            continue
        text = clean(table.get_text(' ', strip=True))
        if 'book value per share' not in text.lower() or 'common stock' not in text.lower() or len(text) > 30000:
            continue
        headers = []
        for row_number, row in enumerate(table.find_all('tr'), 1):
            col = 0
            cells = []
            for cell in row.find_all(['td', 'th'], recursive=False):
                width = int(cell.get('colspan', 1))
                label = clean(cell.get_text(' ', strip=True))
                cells.append((col, col + width, label))
                if re.fullmatch(r'[A-Z][a-z]+ \d{1,2}, \d{4}', label):
                    period = datetime.strptime(label, '%B %d, %Y').date().isoformat()
                    headers.append((col, col + width, period))
                col += width
            if not cells or cells[0][2].lower() != 'book value per share':
                continue
            if '$' not in clean(row.get_text(' ', strip=True)):
                continue
            for start, end, label in cells[1:]:
                value = number(label)
                dates = {period for a, b, period in headers if a <= start and end <= b}
                if value is not None and value > 0 and len(dates) == 1:
                    results.append(candidate(fund, filing, source, 'nav', value,
                        f'HTML table {table_number}; row {row_number}; column {start+1}', text,
                        'dated_per_share_table', period=dates.pop(), basis='book_value',
                        share_class='Common', eligible=True))
    return results


def inline_facts(soup, fund, filing, source):
    results = []
    contexts = {}
    for ctx in soup.find_all(lambda t: t.name and t.name.split(':')[-1].lower() == 'context'):
        instant = ctx.find(lambda t: t.name and t.name.split(':')[-1].lower() == 'instant')
        members = ctx.find_all(lambda t: t.name and t.name.split(':')[-1].lower() in {'explicitmember', 'typedmember'})
        contexts[ctx.get('id')] = (instant.get_text(strip=True) if instant else '', [m.get_text(strip=True) for m in members])
    units = {}
    for unit in soup.find_all(lambda t: t.name and t.name.split(':')[-1].lower() == 'unit'):
        units[unit.get('id')] = clean(unit.get_text(' ', strip=True))
    for fact in soup.find_all(lambda t: t.name and t.name.lower().endswith('nonfraction')):
        tag = fact.get('name', '').split(':')[-1]
        if tag not in {'NetAssetValuePerShare', 'NetAssetValuePerShareOfCommonStock', 'BookValuePerShare', 'BookValuePerCommonShare'}:
            continue
        value = number(fact.get_text())
        if value is None:
            continue
        try:
            value *= 10 ** int(fact.get('scale', '0'))
        except ValueError:
            continue
        if fact.get('sign') == '-':
            value = -abs(value)
        period, members = contexts.get(fact.get('contextref'), ('', []))
        unit = units.get(fact.get('unitref'), '')
        is_book = tag.startswith('Book')
        reasons = []
        if not period:
            reasons.append('Instant reporting date not resolved')
        if not ('USD' in unit and 'shares' in unit.lower()):
            reasons.append('USD per share unit not verified')
        if fund['structure'] == 'interval':
            reasons.append('Institutional share-class context needs confirmation')
        elif members:
            reasons.append('Dimensional context requires review: ' + ', '.join(members))
        if is_book and fund['structure'] != 'mortgage_reit':
            reasons.append('Book value is not automatically NAV')
        if value <= 0:
            reasons.append('Non-positive per-share value needs review')
        parent = fact.find_parent('tr') or fact.parent
        quote = clean(parent.get_text(' ', strip=True))
        locator = f"iXBRL {fact.get('name')} context={fact.get('contextref')} unit={fact.get('unitref')}"
        if fact.get('id'):
            locator += '; anchor #' + fact['id']
        results.append(candidate(fund, filing, source, 'nav', value, locator, quote, 'inline_xbrl',
            period=period, basis='book_value' if is_book else 'nav', share_class=fund['share_class'] if not reasons else 'unconfirmed',
            eligible=not reasons, reasons=reasons))
    return results


# Narrow rules attach the number to a named measure. They generate review candidates:
# contractual bases, footnotes, dates and classes still require confirmation.
PATTERNS = {
    'management_fee': r'(?:base management|management|advisory) fee[^.;]{0,180}?(\d+(?:\.\d+)?)\s*%',
    'effective_fee': r'(?:effective|after (?:fee )?waivers?)[^.;]{0,100}?(\d+(?:\.\d+)?)\s*%',
    'incentive_fee': r'(?:incentive fee|carried interest)[^.;]{0,180}?(\d+(?:\.\d+)?)\s*%',
    'hurdle': r'(?:hurdle|preferred return)[^.;]{0,100}?(\d+(?:\.\d+)?)\s*%',
    'leverage': r'(?:debt.to.equity|leverage) ratio[^.;]{0,80}?(\d+(?:\.\d+)?)\s*(?:to\s*1|:\s*1|x|times)',
    'distribution_yield': r'(?:distribution (?:rate|yield)|dividend yield)[^.;]{0,100}?(\d+(?:\.\d+)?)\s*%',
    'nav': r'(?:net asset value|book value) per (?:common )?share[^.;]{0,60}?\$\s*(\d+(?:\.\d+)?)',
}


def narrative(snippets, fund, filing, source):
    results = []
    for locator, text in snippets:
        for metric, keyword in KEYWORDS.items():
            if not re.search(keyword, text, re.I):
                continue
            # Keep the whole relevant paragraph/row so waiver dates and conflicts are not lost.
            # Huge PDF pages remain searchable evidence, not automatically accepted values.
            pattern = PATTERNS.get(metric)
            matches = list(re.finditer(pattern, text, re.I)) if pattern else []
            if matches:
                for m in matches:
                    results.append(candidate(fund, filing, source, metric, number(m.group(1)), locator,
                        text, 'narrative_rule', reasons=['Confirm rate basis, period, share class and surrounding footnotes']))
            else:
                results.append(candidate(fund, filing, source, metric, None, locator, text,
                    'evidence_passage', reasons=['Relevant passage found; value and definition require review']))
    return results


def return_tables(soup, fund, filing, source):
    results = []
    for i, table in enumerate(soup.find_all('table')):
        if table.find('table'):
            continue
        text = clean(table.get_text(' ', strip=True))
        if len(text) > 30000:
            continue  # Large investment schedules are not compact return tables.
        if not re.search(r'(?:1|one)\s*year', text, re.I):
            continue
        if not re.search(r'(?:3|three|5|five)\s*years?', text, re.I):
            continue
        for metric in ['return_1y', 'return_3y', 'return_5y']:
            results.append(candidate(fund, filing, source, metric, None, f'HTML table {i+1}', text,
                'return_table', reasons=['Confirm row/class, column period, reinvestment and annualization; no positional guessing']))
        # Only simple, explicitly labeled tables qualify for deterministic column mapping.
        # Complex merged cells stay in the review queue above.
        trs = table.find_all('tr')
        header = None
        columns = {}
        for row in trs:
            cells = row.find_all(['td', 'th'], recursive=False)
            if any(c.get('colspan', '1') != '1' or c.get('rowspan', '1') != '1' for c in cells):
                continue
            labels = [clean(c.get_text(' ', strip=True)).lower() for c in cells]
            mapped = {}
            for index, label in enumerate(labels):
                for years, word in [(1, 'one'), (3, 'three'), (5, 'five')]:
                    if re.fullmatch(rf'(?:{years}|{word})[ -]*years?', label):
                        mapped[f'return_{years}y'] = index
            if len(mapped) >= 2:
                header, columns = labels, mapped
                continue
            if header is None or len(cells) != len(header):
                continue
            row_text = ' '.join(labels)
            desired_class = fund['share_class'].lower()
            if fund['structure'] == 'interval':
                class_matches = bool(re.search(r'\b' + re.escape(desired_class) + r'\b', row_text))
                basis_matches = 'net' in row_text and ('nav' in row_text or 'net asset value' in text.lower())
            else:
                class_matches = 'common' in row_text
                basis_matches = 'shareholder' in row_text or 'market price' in row_text
            annualized = 'average annual' in text.lower() or 'annualized' in text.lower()
            reinvested = bool(re.search(r'reinvest', text, re.I))
            # Require the table itself to state its end date, not just the surrounding filing.
            period = filing.get('reportDate', '')
            from datetime import date
            try:
                dt = date.fromisoformat(period)
                dated = period in text or dt.strftime('%B %d, %Y').replace(' 0', ' ') in text
            except ValueError:
                dated = False
            if not (class_matches and basis_matches):
                continue
            for metric, col in columns.items():
                value = number(labels[col])
                if value is None:
                    continue
                reasons = [] if annualized and reinvested and dated else ['Annualization, reinvestment or exact table period not explicit']
                results.append(candidate(fund, filing, source, metric, value, f'HTML table {i+1}; column {col+1}',
                    text, 'labeled_return_table', basis=fund['return_basis'], share_class=fund['share_class'],
                    eligible=not reasons, reasons=reasons))
    return results
