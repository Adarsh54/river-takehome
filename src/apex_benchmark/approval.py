"""Local, version-bound publication gate. Names are attestations, not authenticated identities."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_FILES = ('audit.json', 'benchmark.docx', 'benchmark-evidence.docx', 'benchmark.pdf', 'benchmark.csv')
DOWNLOADS = set(PACKAGE_FILES) - {'audit.json'}


def fingerprint(folder):
    digest = hashlib.sha256()
    for name in PACKAGE_FILES:
        path = Path(folder) / name
        if not path.exists():
            raise ValueError('Generate the complete report before approval.')
        digest.update(name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def status(folder):
    try:
        version = fingerprint(folder)
    except ValueError:
        return {'released': False, 'version': None, 'approvals': {}}
    path = Path(folder) / 'publication-approvals.json'
    saved = json.loads(path.read_text()) if path.exists() else {}
    approvals = saved.get('approvals', {}) if saved.get('version') == version else {}
    return {'released': all(role in approvals for role in ('pm', 'compliance')), 'version': version, 'approvals': approvals}


def approve(folder, role, reviewer, version, confirmed):
    if role not in {'pm', 'compliance'} or confirmed is not True:
        raise ValueError('Select a review role and explicitly confirm the approval statement.')
    reviewer = reviewer.strip()
    if not 2 <= len(reviewer) <= 100:
        raise ValueError('Enter the reviewer name.')
    state = status(folder)
    if not version or version != state['version']:
        raise ValueError('The report changed. Review the current version before approving.')
    other = state['approvals'].get('compliance' if role == 'pm' else 'pm')
    if other and other['reviewer'].casefold() == reviewer.casefold():
        raise ValueError('PM and compliance approvals require separate reviewers.')
    run = json.loads((Path(folder) / 'audit.json').read_text())
    if not run.get('pm_narrative','').strip():
        raise ValueError('Save the PM-authored summary before publication approval.')
    for result in run['results'] + run['nav_history']:
        if result.get('value') is None:
            continue
        sources = result.get('sources', [])
        if result.get('unresolved_conflict') or not sources or not all(
            s.get('source_url') and s.get('locator') and s.get('quote') and s.get('source_sha256') for s in sources
        ):
            raise ValueError('Exclude figures with missing citations or unresolved conflicts before approval.')
    state['approvals'][role] = {'reviewer': reviewer, 'at': datetime.now(timezone.utc).isoformat(),
        'statement': 'All included figures located in original sources; unlocatable figures excluded.' if role == 'compliance' else 'Comparison, definitions, dates and exclusions reviewed; approved for circulation.'}
    path = Path(folder) / 'publication-approvals.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'version': version, 'approvals': state['approvals']}, indent=2))
    tmp.replace(path)
    return status(folder)


def exclude(folder, section, index, reason, version):
    if status(folder)['version'] != version or not version:
        raise ValueError('The report changed. Reload before excluding a figure.')
    if section not in {'results', 'nav_history'} or not isinstance(index, int) or index < 0:
        raise ValueError('Select a current or historical figure.')
    if not reason.strip():
        raise ValueError('Explain why the figure is excluded.')
    folder = Path(folder)
    run = json.loads((folder / 'audit.json').read_text())
    if index >= len(run[section]):
        raise ValueError('Unknown figure.')
    result = run[section][index]
    if result.get('value') is None:
        raise ValueError('This figure is already excluded.')
    # Preserve the original decision for investigation, outside published report content.
    path = folder / 'publication-exclusions.json'
    records = json.loads(path.read_text()) if path.exists() else []
    records.append({'section': section, 'index': index, 'reason': reason, 'original': result.copy(),
                    'at': datetime.now(timezone.utc).isoformat()})
    path.write_text(json.dumps(records, indent=2))
    result.update(value=None, sources=[], status='withheld', has_verifiable_evidence=False,
                  directly_reported=False, unresolved_conflict=False, conflict_candidates=[],
                  calculation=None, comparability='', basis='', judgment={},
                  reason='Excluded from publication: ' + reason.strip(),
                  evidence_rationale='Excluded from publication: ' + reason.strip())
    from .report import export
    export(run, folder)
    return status(folder)
