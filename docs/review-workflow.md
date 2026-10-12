# Evidence review workflow

The prototype produces a review draft, not a compliance approval. Open `output/latest/index.html`. Start with retrieval errors, then the comparison, then the extraction queue. A number in the queue is only a candidate. The original SEC filing remains authoritative.

## What reviewers confirm

For each proposed value, open the source, locate the quoted passage using the anchor, table/block identifier or XBRL context, and verify the period, units, exact share class, footnotes and definition. Inspect other candidates for that metric, including later supplements. A source hash proves reproducibility, not financial correctness.

Fee basis must state both rate type and denominator: e.g. `contractual:average_daily_gross_assets`. Effective fees use `effective:<denominator>`. Preserve temporary waiver dates and conditions in the rationale. Never infer a waived rate or extend a waiver beyond its term. Narrative extraction deliberately retains entire relevant paragraphs.

Returns use `shareholder` for GBDC/KREF and `net_nav` for CCLFX/TAKIX. Confirm distribution reinvestment and annualization. Do not substitute a graph's index level for a percentage return. This prototype does not calculate missing trailing returns from market prices.

Leverage uses `debt_to_equity:<exact definition>`, distribution yield `annualized:<denominator and distribution basis>`. A reported regulatory coverage ratio is not debt/equity. KREF NAV row explicitly uses `book_value`, not fund NAV. GBDC uses `nav`. Exact share-class identifiers in the configuration must match the filing before accepting a candidate.

## Recorded decisions

Create a JSON array in an ignored local output directory. Use actual candidate IDs and values from your run, never the explanatory placeholders below:

```json
[
  {
    "candidate_id": "COPY_ID_FROM_REAL_RUN",
    "action": "accept",
    "reviewer": "Reviewer name",
    "reason": "Explain the selected figure, denominator, footnotes, waiver terms and why alternatives do not apply.",
    "value": 1.25,
    "unit": "%",
    "period": "2024-12-31",
    "basis": "contractual:average_daily_gross_assets",
    "share_class": "Institutional",
    "evidence_text": "COPY_EXACT_SOURCE_TEXT_CONTAINING_THE_VALUE"
  }
]
```

This illustrative JSON is not competitor data and cannot validate as supplied. The application rejects unknown/stale IDs, unsupported values, missing reviewer/rationale, mismatched units, absent verbatim evidence, and future periods. For rejection, supply candidate_id, action `reject`, reviewer and reason. Reject specific conflicting candidates explicitly; a newer filing does not silently win. Accepted definitions must also pass the metric-specific compatibility checks.

Rerun `apex-benchmark --offline --decisions output/decisions.json`. The PDF/CSV/HTML retain qualifications. Review decisions do not authorize board use: the PM and compliance still approve the package separately. Neither authentication nor a multi-user approval service is implemented.

## Status meanings

- `supported` / medium: structured source passed unit, context and temporal checks; human gates outstanding.
- `supported_with_review`: a dated, definition-matched source supports the value, while other numeric passages have unconfirmed context or duplicate it. Those passages remain explicit review items. This is not a resolved disagreement between comparable facts.
- `reviewed`: a named reviewer resolved interpretation with verbatim supporting evidence. This is a confidence label, not compliance sign-off.
- `conflict`: accepted evidence differs for the same period; value withheld.
- `needs_review`: candidates exist but interpretation or conflicting candidates are unresolved.
- `not_found`: extraction did not establish a value. This is not a claim of non-disclosure.
- `retrieval_incomplete`: missing source access prevents reliable coverage/freshness verification.
- `lagged`: supported period is more than 120 days behind target (configurable review threshold, not a client-approved materiality rule).

## Internal figures

Dana must confirm the authoritative Apex source and permitted rows. Only then set `apex_data_approved`, `apex_approved_by` and `apex_approval_note` in a local config copy. Only the target quarter and history from Q1 2024 through the target enter output. The original input remains unchanged. Approval is a documented local control, not an identity-security system.

## Scanned PDF evidence

Candidates with method `ocr_evidence` are never automatically qualified. The audit records the original PDF URL/hash, physical page number, local engine version, render hash, 300-dpi settings, recognized words and pixel boxes (top-left origin), and word recognition scores. Open the original PDF and visually check the number, punctuation, units, period, class and surrounding terms. Acceptance also requires `"visual_verified": true` in the existing decision record. This flag records reviewer attestation; it is not authenticated sign-off. Low recognition scores increase review need; high scores never replace visual review. OCR errors are coverage errors, not evidence of non-disclosure.

## N-PORT structured records

Use `nport.json` for aggregate amounts, monthly returns, reconciliation checks and position details; use `nport-holdings.csv` for flat position data. All XML paths use `n` for the N-PORT namespace documented in each report. An individual position locator plus field name identifies its exact XML field. Fund-level net assets must not be accepted as NAV per share. Return entries without class IDs remain unassigned. B.2.c borrowing/net-asset ratios are calculated candidates with explicit inputs and are not automatically used as comparable leverage. The current decision file cannot approve a derived value by pretending it is a quoted number; adding a benchmark rule requires an explicit supported transformation and scope checks.
