"""Explain support without ordinal confidence grades."""
def annotate_result(result):
    result.pop('confidence', None)
    result['has_verifiable_evidence'] = result.get('value') is not None and bool(result.get('sources'))
    result['directly_reported'] = result['has_verifiable_evidence'] and not bool(result.get('calculation'))
    result.setdefault('decision_author', 'rules_only')
    result['evidence_rationale'] = result.get('reason', '')
    result.setdefault('unresolved_issues', [])
    result['gap_kind']=gap_kind(result)
    return result


GAP_LABELS = {
    'conflict':'Unresolved conflict — PM review required',
    'not_searched':'Evidence not found', 'review_pending':'AI review pending',
    'review_failed':'AI review failed', 'source_incomplete':'Source retrieval incomplete',
    'context_incomplete':'Evidence context incomplete', 'not_established':'Reviewed — value not established', 'needs_interpretation':'Interpretation needed',
    'supported':'Evidence linked',
}


def gap_kind(result):
    if result.get('value') is not None and result.get('sources'):return 'supported'
    if result.get('unresolved_conflict'):return 'conflict'
    if result.get('judgment',{}).get('packet_complete') is False:return 'context_incomplete'
    reason=result.get('reason','')
    if result.get('status') in {'retrieval_incomplete','extraction_incomplete'} or 'coverage is incomplete' in reason:
        return 'source_incomplete'
    if 'No retrieved passages' in reason or result.get('status')=='not_found':return 'not_searched'
    if result.get('decision_author')=='llm_not_completed':
        return 'review_pending' if 'No matching cached' in reason or 'AI review pending' in reason else 'review_failed'
    if result.get('decision_author')=='llm':return 'not_established'
    return 'needs_interpretation'


def evidence_label(result):
    return GAP_LABELS[gap_kind(result)]


def migrate_evidence_contract(run):
    """Upgrade cached audit exports; OCR recognition scores are unrelated and retained."""
    run['schema_version'] = 2
    for group in ('results', 'nav_history'):
        for result in run[group]:
            annotate_result(result)
    for value in run['apex'].get('values', {}).values():
        value.pop('confidence', None)
        value['evidence_rationale'] = 'Client-approved internal input; not independently verified against SEC filings.'
    for report in run.get('nport_reports', []):
        report.pop('confidence_definition', None)
        report['evidence_note'] = 'Explicit XML fields with source paths. Numeric transcription does not confirm comparability; inspect balance checks and class identifiers.'
        for field in report['fields'].values():
            field.pop('confidence', None)
            field['has_verifiable_evidence'] = field.get('value') is not None and bool(field.get('locator'))
        for item in report['monthly_returns']:
            item.pop('confidence', None)
            item['evidence_rationale'] = 'Return attributes are cited in XML; ' + ('class ID is present.' if item.get('class_id') else 'share class is unresolved.')
        for holding in report['holdings']:
            holding.pop('confidence', None)
            holding['has_verifiable_evidence'] = holding.get('valUSD') is not None and bool(holding.get('locator'))
    return run
