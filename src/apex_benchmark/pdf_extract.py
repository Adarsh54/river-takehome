"""Page-level local OCR with retained word boxes and mandatory visual review."""
from __future__ import annotations
import csv
import hashlib
import importlib.metadata
import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from pypdf import PdfReader
from pypdf.errors import PyPdfError

DPI = 300
TIMEOUT_SECONDS = 90
MAX_PIXELS = 35_000_000


def ocr_environment():
    engine = shutil.which('tesseract')
    result = {'tesseract': engine, 'renderer': None, 'engine_version': None, 'dpi': DPI}
    try:
        result['renderer'] = importlib.metadata.version('pypdfium2')
        importlib.metadata.version('Pillow')
    except importlib.metadata.PackageNotFoundError:
        result['renderer'] = None
        pass
    if engine:
        try:
            result['engine_version'] = subprocess.run([engine, '--version'], capture_output=True,
                text=True, timeout=10, check=True).stdout.splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            result['tesseract'] = None
    return result


def parse_tsv(tsv):
    words = []
    lines = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row.get('level') != '5' or not row.get('text', '').strip():
            continue
        confidence = float(row['conf'])
        word = {'text': row['text'], 'confidence': confidence,
                'box_px': [int(row[k]) for k in ('left', 'top', 'width', 'height')]}
        words.append(word)
        key = tuple(row[k] for k in ('block_num', 'par_num', 'line_num'))
        lines.setdefault(key, []).append(word['text'])
    scores = [w['confidence'] for w in words if w['confidence'] >= 0]
    return {'text': '\n'.join(' '.join(line) for line in lines.values()), 'words': words,
            'mean_word_confidence': sum(scores)/len(scores) if scores else None,
            'low_confidence_words': sum(score < 80 for score in scores)}


def ocr_page(body, index, engine):
    import pypdfium2 as pdfium
    with tempfile.TemporaryDirectory(prefix='apex-ocr-') as folder:
        with pdfium.PdfDocument(body) as doc:
            page = doc[index]
            width, height = page.get_size()
            scale = DPI / 72
            if width * height * scale * scale > MAX_PIXELS:
                page.close()
                raise ValueError('OCR page exceeds 35 million pixel rendering limit')
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            path = Path(folder) / 'page.png'
            image.save(path)
            dimensions = image.size
            image.close()
            bitmap.close()
            page.close()
        result = subprocess.run([engine, str(path), 'stdout', '-l', 'eng', '--psm', '3', 'tsv'],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=True)
        return {**parse_tsv(result.stdout), 'image_size_px': list(dimensions),
                'render_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'dpi': DPI}


def pdf_candidates(body, fund, filing, source, diagnostics, mode='auto', environment=None):
    from .extract import narrative, clean, candidate
    if mode not in {'auto', 'always', 'off'}:
        raise ValueError('Unknown OCR mode')
    environment = environment or ocr_environment()
    results = []
    try:
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('Password-protected PDF cannot be inspected')
    except (PyPdfError, ValueError) as exc:
        diagnostics.append({'stage': 'parse', 'status': 'failed', 'error': f'PDF unreadable: {exc}'})
        return results
    for index, page in enumerate(reader.pages):
        page_number = index + 1
        try:
            text = clean(page.extract_text() or '')
        except (PyPdfError, ValueError) as exc:
            text = ''
            diagnostics.append({'stage': 'pdf', 'page': page_number, 'status': 'native_text_failed', 'note': str(exc)})
        # A scanned page can have a selectable header. Sparse text therefore still triggers OCR.
        needs_ocr = mode == 'always' or len(''.join(c for c in text if c.isalnum())) < 120
        if text:
            results.extend(narrative([(f'PDF page {page_number}; native text', text)], fund, filing, source))
        if not needs_ocr:
            diagnostics.append({'stage': 'pdf', 'page': page_number, 'status': 'native_text'})
            continue
        if mode == 'off' or not environment['tesseract'] or not environment['renderer']:
            diagnostics.append({'stage': 'ocr', 'page': page_number,
                'status': 'disabled' if mode == 'off' else 'unavailable',
                'error': 'Page requires OCR. Install .[ocr] and Tesseract, or enable OCR; extraction incomplete.'})
            continue
        try:
            extracted = ocr_page(body, index, environment['tesseract'])
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            diagnostics.append({'stage': 'ocr', 'page': page_number, 'status': 'failed',
                                'error': f'OCR failed: {type(exc).__name__}: {str(exc)[:300]}'})
            continue
        metadata = dict(extracted, engine=environment['engine_version'], language='eng',
                        coordinate_system='pixels from top-left of rendered page', page=page_number)
        text = extracted['text']
        if not text.strip():
            diagnostics.append({'stage': 'ocr', 'page': page_number, 'status': 'empty',
                                'error': 'OCR returned no text; inspect whether page is blank or unreadable.'})
            continue
        diagnostics.append({'stage': 'ocr', 'page': page_number, 'status': 'processed',
                            'mean_word_confidence': extracted['mean_word_confidence'],
                            'low_confidence_words': extracted['low_confidence_words']})
        locator = f'PDF page {page_number}; OCR {DPI} dpi; word boxes in extraction_meta'
        found = narrative([(locator, clean(text))], fund, filing, source)
        if not found:
            found = [candidate(fund, filing, source, 'source_text', None, locator, clean(text),
                               'ocr_evidence', reasons=['OCR page retained; no recognized metric label.'])]
        for c in found:
            c.method = 'ocr_evidence'
            c.eligible = False
            c.extraction_meta = metadata
            c.reasons.append('OCR transcription requires visual verification against the original PDF; engine confidence is not financial confidence.')
            results.append(c)
    return results
