"""Explicit N-PORT fields; no inference from XML element order or fund totals to NAV/share."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from lxml import etree

NS = 'http://www.sec.gov/edgar/nport'
TOTALS = ('totAssets', 'totLiabs', 'netAssets')
BORROWINGS = tuple('amtPay' + term + lender for term in ('OneYr', 'AftOneYr')
                   for lender in ('BanksBorr', 'CtrldComp', 'OthAffil', 'Other'))
AMOUNTS = TOTALS + BORROWINGS + ('delayDeliv', 'standByCommit', 'liquidPref', 'cshNotRptdInCorD')


def decimal_value(text):
    try:
        value = Decimal(text)
        return value if value.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def parse_nport(body, fund, filing, source):
    """Return a structured report and review candidates. XML paths are namespace-qualified."""
    from .extract import candidate
    body = body.strip().removeprefix(b'<XML>').removesuffix(b'</XML>').strip()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(body, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f'Invalid N-PORT XML: {exc}') from exc
    if root.getroottree().docinfo.doctype:
        raise ValueError('N-PORT DTD/entity declarations are not supported')
    if root.tag != f'{{{NS}}}edgarSubmission':
        raise ValueError('Unrecognized N-PORT XML root or namespace')
    ns = {'n': NS}
    gen = root.find('n:formData/n:genInfo', ns)
    info = root.find('n:formData/n:fundInfo', ns)
    if gen is None or info is None:
        raise ValueError('N-PORT requires formData/genInfo and fundInfo')

    def text(node, field):
        values = node.findall('n:' + field, ns)
        if len(values) > 1:
            raise ValueError(f'Duplicate N-PORT field: {field}')
        return (values[0].text or '').strip() if values else ''

    period = text(gen, 'repPdDate')  # repPdEnd is fiscal year end, not observation date.
    date.fromisoformat(period)
    cik = text(gen, 'regCik')
    if not cik.isdigit() or int(cik) != int(fund['cik']):
        raise ValueError('N-PORT registrant CIK does not match requested fund')
    series = text(gen, 'seriesId')
    if fund.get('series_id') and series != fund['series_id']:
        raise ValueError('N-PORT series does not match configured series_id')
    if filing.get('reportDate') and period != filing['reportDate']:
        raise ValueError('N-PORT observation date disagrees with filing inventory')

    def evidence(node):
        # Prefix n always denotes the documented N-PORT namespace.
        ancestors = list(reversed(list(node.iterancestors()))) + [node]
        pieces = []
        for e in ancestors:
            local = etree.QName(e).localname
            parent = e.getparent()
            siblings = [] if parent is None else [s for s in parent if s.tag == e.tag]
            suffix = f'[{siblings.index(e)+1}]' if len(siblings) > 1 else ''
            pieces.append('n:' + local + suffix)
        return {'locator': 'XML /' + '/'.join(pieces),
                'quote': etree.tostring(node, encoding='unicode', with_tail=False)}

    report = {'ticker': fund['ticker'], 'accession': filing['accessionNumber'],
              'filing_date': filing['filingDate'], 'period': period,
              'fiscal_year_end': text(gen, 'repPdEnd'), 'cik': cik,
              'series_id': series, 'series_name': text(gen, 'seriesName'),
              'source_url': source['url'], 'source_sha256': source['sha256'], 'namespace': NS,
              'fields': {}, 'monthly_returns': [], 'holdings': [], 'checks': [],
              'confidence_definition': 'Medium: parsed explicit XML field and verified fund/date; not independent financial validation. Low: class scope unresolved. Missing/invalid fields unavailable.',
              'notes': ['Total net assets are fund-level USD, not NAV per share or an AUM definition.',
                        'Monthly returns remain monthly; no annual return or share class is inferred.',
                        'Borrowings under Item B.2.c are not total liabilities or full economic leverage.']}
    numeric = {}
    for field in AMOUNTS:
        raw = text(info, field)
        node = info.find('n:' + field, ns)
        value = decimal_value(raw)
        numeric[field] = value
        report['fields'][field] = {'value': float(value) if value is not None else None,
            'raw': raw, 'unit': 'USD', 'confidence': 'medium' if value is not None else 'unavailable', 'status': 'extracted' if value is not None else 'missing_or_invalid',
            **(evidence(node) if node is not None else {})}
    a, l, n = [numeric[k] for k in TOTALS]
    if all(v is not None for v in (a, l, n)):
        difference = a - l - n
        report['checks'].append({'check': 'assets_minus_liabilities_equals_net_assets',
            'status': 'pass' if abs(difference) <= Decimal('0.02') else 'fail',
            'difference_usd': float(difference), 'tolerance_usd': 0.02})
    else:
        report['checks'].append({'check': 'assets_minus_liabilities_equals_net_assets', 'status': 'unavailable'})
    for node in info.findall('n:returnInfo/n:monthlyTotReturns/n:monthlyTotReturn', ns):
        record = {'class_id': node.get('classId'), 'values_pct': {}, **evidence(node),
                  'confidence': 'medium' if node.get('classId') else 'low',
                  'status': 'class_identified' if node.get('classId') else 'class_unconfirmed'}
        for field in ('rtn1', 'rtn2', 'rtn3'):
            value = decimal_value(node.get(field))
            record['values_pct'][field] = float(value) if value is not None else None
        report['monthly_returns'].append(record)
    holdings = root.findall('n:formData/n:invstOrSecs/n:invstOrSec', ns)
    for position_index, node in enumerate(holdings, 1):
        record = {k: text(node, k) for k in ('name', 'title', 'cusip', 'curCd', 'units', 'assetCat', 'issuerCat', 'payoffProfile', 'fairValLevel')}
        for field in ('balance', 'valUSD', 'pctVal'):
            raw = text(node, field)
            value = decimal_value(raw)
            record[field] = float(value) if value is not None else None
            record[field + '_raw'] = raw
        # Nested alternatives carry attributes instead of text in some filings.
        for tag in ('assetConditional', 'issuerConditional', 'currencyConditional'):
            e = node.find('n:' + tag, ns)
            if e is not None:
                record[tag] = dict(e.attrib)
        record['confidence'] = 'medium' if record['valUSD'] is not None else 'unavailable'
        record['identifiers'] = [{etree.QName(e).localname: dict(e.attrib)}
                                for e in node.findall('n:identifiers/*', ns)]
        record['locator'] = f'XML /n:edgarSubmission/n:formData/n:invstOrSecs/n:invstOrSec[{position_index}]'
        debt_security = node.find('n:debtSec', ns)
        if debt_security is not None:
            record['debt_security'] = {etree.QName(e).localname: e.text for e in debt_security if len(e) == 0}
        # Raw position remains in the immutable source; avoid duplicating enormous XML in exports.
        report['holdings'].append(record)
    report['holdings_summary'] = {'count': len(holdings),
        'value_usd_sum': float(sum((decimal_value(h['valUSD_raw']) or Decimal(0)) for h in report['holdings'])),
        'missing_value_count': sum(h['valUSD'] is None for h in report['holdings']),
        'note': 'Sum of reported position values only; not reconciled to total assets (cash, derivatives and other items differ).'}
    candidates = []
    # Useful for analyst review, but the category scope must be accepted before headline use.
    if n is not None and n > 0 and all(numeric[k] is not None and numeric[k] >= 0 for k in BORROWINGS):
        debt = sum(numeric[k] for k in BORROWINGS)
        value = float(debt / n)
        inputs = {k: float(numeric[k]) for k in BORROWINGS + ('netAssets',)}
        quote = '\n'.join(report['fields'][k]['quote'] for k in BORROWINGS + ('netAssets',))
        c = candidate(fund, filing, source, 'leverage', value,
            'XML /n:edgarSubmission/n:formData/n:fundInfo; Item B.2.c components and netAssets',
            quote, 'nport_borrowings_ratio', period=period,
            basis='nport_borrowings_to_net_assets:scope_requires_review', share_class='Fund-level',
            reasons=['Derived Item B.2.c borrowings / net assets; confirm scope before treating as comparable debt/equity.',
                     'Zero reported borrowings do not prove zero economic leverage.'])
        c.extraction_meta = {'calculation': {'expression': 'sum(B.2.c borrowing components) / netAssets',
            'inputs': inputs, 'output': value}, 'reconciliation': report['checks']}
        candidates.append(c)
    return report, candidates
