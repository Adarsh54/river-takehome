"""Question-specific retrieval over immutable passages, without document parsing."""
import hashlib
import re
from pathlib import Path
from .passages import document_passages, VERSION

# Legal waivers alone are not fee evidence. Retain fee reductions, expense caps,
# and the contractual disclosures needed to interpret effective rates together.
FEE = re.compile(r'(?:management|advisory)\s+fee|expense\s+(?:ratio|limit|cap)|'
                 r'fee\s+waiv|waiv\w*\s+(?:of\s+)?(?:the\s+)?(?:management\s+|advisory\s+|incentive\s+)?fee|'
                 r'(?:net|total)\s+(?:operating\s+)?expenses', re.I)



def retrieve_fee_passages(candidates, cache):
    cache = Path(cache)
    documents = {}
    preserved = []
    for c in candidates:
        if c.get('calculation') or c.get('review') or c['method'] == 'ocr_evidence':
            preserved.append(c)
        documents.setdefault((c['source_sha256'], c['source_url'], c['accession']), c)
    audit = {'strategy': 'indexed-fee-context-v1', 'documents_searched': 0,
             'indexed_passages_searched': 0, 'matched_passages': 0,
             'context_passages': 0, 'nonmatching_passages': 0, 'index_unavailable': []}
    out = list(preserved)
    for (digest, url, accession), template in documents.items():
        # Do not silently reparse a filing when servicing an incremental question.
        index = cache / 'passages' / VERSION / (digest + '.json')
        if not index.exists():
            audit['index_unavailable'].append(url)
            out.extend(c for c in candidates if c['source_sha256'] == digest and c['source_url'] == url)
            continue
        passages = document_passages(cache, digest)
        hits = {i for i, p in enumerate(passages) if FEE.search(p['text'])}
        selected = set()
        for i in hits:
            # Keep neighboring headings, continuation paragraphs and footnotes as
            # separately numbered citations; overlapping windows become one set.
            selected.update(range(max(0, i - 1), min(len(passages), i + 2)))
            # Footnote lists can exceed three paragraphs. Preserve the entire
            # consecutive numbered footnote run after a matched table.
            if passages[i].get('kind') == 'table':
                selected.update(range(max(0, i - 3), min(len(passages), i + 4)))
                j = i + 1
                while j < len(passages) and (re.match(r'^\(?\d{1,2}\)?[.)\s]', passages[j]['text']) or re.fullmatch(r'\d+|TABLE OF CONTENTS', passages[j]['text'], re.I)):
                    selected.add(j)
                    j += 1
        audit['documents_searched'] += 1
        audit['indexed_passages_searched'] += len(passages)
        audit['matched_passages'] += len(hits)
        audit['context_passages'] += len(selected - hits)
        audit['nonmatching_passages'] += len(passages) - len(selected)
        chunks = []
        for i in sorted(selected):
            p = dict(passages[i])
            if p.get('rows'):
                # A table's introduction can establish its observation date.
                # Preserve it on the same citable passage, without duplicating intervening
                # tables, so values retain their reporting context.
                preceding = [x for x in passages[max(0, i - 3):i] if not x.get('rows') and len(x['text']) <= 4000]
                p['text'] = ' '.join(x['text'] for x in preceding) + ' ' + p['text']
                p['locator'] += '; nearby preceding non-table introductions included'
            if (chunks and i == chunks[-1][0] + 1 and not p.get('rows')
                    and not chunks[-1][1].get('rows')
                    and len(chunks[-1][1]['text']) + len(p['text']) < 12000):
                previous = chunks[-1][1]
                previous['text'] += ' ' + p['text']
                previous['locator'] = previous['locator'].split('; through ')[0] + '; through ' + p['locator']
                previous['id'] = previous['id'].split('|')[0] + '|' + p['id']
                previous['section_headings'] = list(dict.fromkeys(previous.get('section_headings', []) + p.get('section_headings', [])))
                chunks[-1] = (i, previous)
            else:
                chunks.append((i, p))
        for i, p in chunks:
            rows = []
            for row in p.get('rows', []):
                cells = []; column = 0
                for cell in row:
                    try: span = max(1, int(cell.get('colspan', 1)))
                    except (TypeError, ValueError): span = 1
                    if cell['text']: cells.append([column, cell['text'], span, cell.get('rowspan', '1')])
                    column += span
                if cells: rows.append(cells)
            # Narrative XBRL tables repeat an entire note in one cell. Its text
            # is sufficient; retain row geometry only for genuinely tabular data.
            if rows and all(len(row) <= 2 for row in rows) and any(len(cell[1]) > 4000 for row in rows for cell in row):
                rows = []
            out.append(dict(template, id=hashlib.sha256((p['id'] + accession + url + ':effective_fee').encode()).hexdigest()[:20],
                metric='effective_fee', value=None, period='', eligible=False, calculation=None,
                basis='requires interpretation', reasons=['Retrieved management-fee disclosure or adjacent context'],
                method='indexed_fee_evidence', quote=p['text'], locator=p['locator'] + '; indexed passage ' + p['id'],
                section_headings=p.get('section_headings', []), table_rows=rows,
                table_format='Rows of cells [column index, text, colspan, rowspan]; spacer columns preserved',
                parent_candidate_id=template['id']))
    # An XBRL note can repeat paragraphs from the main filing. Remove only
    # exact contained prose from the SAME accession, never numeric table rows
    # or a differing disclosure. The retained larger passage supplies context.
    kept = []
    audit['contained_duplicate_passages'] = 0
    for c in sorted(out, key=lambda c: len(c['quote']), reverse=True):
        duplicate = next((other for other in kept if not c.get('table_rows')
            and not c.get('eligible') and not c.get('review') and not c.get('calculation')
            and c['accession'] == other['accession'] and c['quote'] in other['quote']), None)
        if duplicate is not None:
            audit['contained_duplicate_passages'] += 1
            audit.setdefault('duplicate_locations', []).append({
                'source_url': c['source_url'], 'locator': c['locator'],
                'retained_id': duplicate['id'], 'source_sha256': c['source_sha256']})
        else:
            kept.append(c)
    return kept, audit
