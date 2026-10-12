"""SEC discovery and content-addressed caching. No synthetic-data fallback."""
from __future__ import annotations
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests


class RetrievalError(RuntimeError):
    pass


class SecClient:
    def __init__(self, user_agent: str, cache: Path, offline=False, refresh=False):
        if not user_agent.strip():
            raise ValueError("Set SEC_USER_AGENT to an application name and real contact email.")
        self.cache, self.offline, self.refresh = Path(cache), offline, refresh
        self.cache.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent, 'Accept-Encoding': 'gzip, deflate'})
        self.last_request = 0.0

    def get(self, url: str) -> tuple[bytes, dict]:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'www.sec.gov', 'data.sec.gov'}:
            raise ValueError('Only HTTPS SEC sources are allowed')
        key = hashlib.sha256(url.encode()).hexdigest()
        meta_path = self.cache / f'{key}.json'
        if meta_path.exists() and (self.offline or not self.refresh):
            meta = json.loads(meta_path.read_text())
            try:
                body = (self.cache / meta['sha256']).read_bytes()
            except OSError as exc:
                raise RetrievalError(f'Cached source body missing: {url}') from exc
            if hashlib.sha256(body).hexdigest() != meta['sha256']:
                raise RetrievalError(f'Cached source checksum mismatch: {url}')
            return body, meta
        if self.offline:
            raise RetrievalError(f'No cached SEC response: {url}')
        for attempt in range(3):
            time.sleep(max(0, 0.25 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                response = self.session.get(url, timeout=(10, 60))
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RetrievalError(f'Network failure for {url}: {exc}') from exc
            if response.status_code == 403:
                raise RetrievalError(f'SEC access denied (HTTP 403): {url}. Verify declared contact and network access; no numbers substituted.')
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    retry = response.headers.get('Retry-After', '')
                    delay = min(float(retry), 30) if retry.isdigit() else 2 ** (attempt + 1)
                    time.sleep(delay)
                    continue
            if not response.ok:
                raise RetrievalError(f'HTTP {response.status_code}: {url}')
            body = response.content
            if b'Your Request Originates from an Undeclared' in body or b'Request Rate Threshold Exceeded' in body:
                raise RetrievalError(f'SEC returned a block page: {url}')
            digest = hashlib.sha256(body).hexdigest()
            meta = {'url': url, 'sha256': digest, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                    'content_type': response.headers.get('Content-Type', ''), 'bytes': len(body)}
            (self.cache / digest).write_bytes(body)
            meta_path.write_text(json.dumps(meta, indent=2))
            return body, meta
        raise RetrievalError(f'Retries exhausted: {url}')

    def json(self, url):
        body, _ = self.get(url)
        try:
            return json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RetrievalError(f'Invalid JSON from {url}') from exc


def rows(columns):
    keys = list(columns)
    if not keys:
        return []
    return [{key: columns[key][i] if i < len(columns[key]) else '' for key in keys}
            for i in range(len(columns.get('accessionNumber', [])))]


def discover(client, cik, cutoff):
    obj = client.json(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json')
    filings = rows(obj['filings']['recent'])
    for page in obj['filings'].get('files', []):
        if page.get('filingFrom', '') <= cutoff:
            filings.extend(rows(client.json('https://data.sec.gov/submissions/' + page['name'])))
    unique = {r['accessionNumber']: r for r in filings if r.get('filingDate', '') <= cutoff}
    return sorted(unique.values(), key=lambda r: (r['filingDate'], r['accessionNumber']), reverse=True)


def family(form):
    form = form.removesuffix('/A')
    if form in {'10-K', '10-Q', 'N-CSR', 'N-CSRS'}:
        return 'report'
    if form in {'NPORT-P', 'NPORT-EX'}:
        return 'portfolio'
    if form.startswith(('497', '424B')) or form in {'N-2', 'N-2ASR', '485BPOS', '486BPOS'}:
        return 'prospectus'
    if form == '8-K':
        return 'current'
    return None


def select_filings(inventory, target):
    """No top-N truncation: all relevant reports/history and recent supplements."""
    year = int(target[:4])
    history_start = f'{year - 2}-01-01'
    supplement_start = f'{year - 1}-01-01'
    selected = []
    for row in inventory:
        kind = family(row['form'])
        if kind in {'report', 'portfolio'} and row['filingDate'] >= history_start:
            selected.append(row)
        elif kind in {'prospectus', 'current'} and row['filingDate'] >= supplement_start:
            selected.append(row)
    # If no recent prospectus exists, retain latest older one as explicitly dated evidence.
    if not any(family(r['form']) == 'prospectus' for r in selected):
        older = next((r for r in inventory if family(r['form']) == 'prospectus'), None)
        if older:
            selected.append(older)
    return sorted(selected, key=lambda r: (r['filingDate'], r['accessionNumber']), reverse=True)


def filing_url(cik, filing):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{filing['accessionNumber'].replace('-', '')}/{filing['primaryDocument']}"


def filing_documents(client, cik, filing):
    primary = filing_url(cik, filing)
    # Complete submissions preserve exhibits: annual reports can live outside primary document.
    base = primary.rsplit('/', 1)[0]
    full = base + '/' + filing['accessionNumber'] + '.txt'
    return primary, full
