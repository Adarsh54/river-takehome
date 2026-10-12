# Validation record

Development validation: October 12, 2026. Historical comparison cutoff remains February 28, 2025; run date is not the financial reporting period.

## Automated checks

`pytest -q`: 77 passing tests. Coverage includes units/scales and exact contexts, historical discovery, inclusive cutoff, future-period exclusion, source conflicts, evidence-bound decisions, waiver-term retention, return-table definitions, source-cache integrity, disputed internal data, export citations and HTTP error handling. New live-driven regressions cover N-PORT display-folder paths, financial XML exclusion, explicit KREF date-column mapping, distinct evidence IDs for repeated documents, historical observations not being mislabeled as stale current figures, current versus old fee rates, target versus actual leverage, annualization conditions, return compounding, exact share classes, source-index conversion and rounding reconciliation.

Synthetic unit fixtures never supply competitor output. Actual report values come from downloaded SEC sources.

## Live SEC retrieval

Initial calls without a real contact email returned HTTP 403. After the user supplied a contact, the SEC submissions API succeeded. The contact is stored in ignored, owner-readable local configuration, not in Git or generated evidence.

The corrected live run retrieved **167 selected filings** across all four funds with **zero retrieval errors**. It processed 2,940 source documents/exhibits. Historical metadata filtering retained only filings dated on or before February 28, 2025. Two live defects were fixed: N-PORT metadata's XSL display folder was incorrectly included in raw submission paths, and status detection previously searched arbitrary error text instead of checking the HTTP status field.

Financial XML and label dictionaries are no longer copied into narrative evidence. This reduced the initial 775 MB audit to approximately 30 MB. Original SEC sources remain in the immutable local cache. Parsed evidence is separately cached by source, configuration and parser version.

## Financial checks and coverage

Source inspection confirmed:

- Golub NAV per common share: **$15.13 at December 31, 2024**, from its February 4, 2025 Form 10-Q. Inline XBRL specifies USD/share and the exact instant date.
- KREF book value per share: **$14.76 at December 31, 2024**, from its February 3, 2025 Form 10-K. The date-column span and common-equity/share table establish the mapping. This is labeled book value, not fund NAV.

These figures retain `supported_with_review` flags because other numeric passages have unconfirmed context. Confirmed contradictions for the same period/definition still block a value. The system does not treat a rough narrative match as a proven competing fact.

The current mappings establish **26 current values and 21 historical observations** across the four funds. Thirteen current values are supported with additional review flags and thirteen are supported; thirteen need further interpretation and one was not extracted. These gaps are not claims of non-disclosure. The complete observed summary and source links are in `live-validation.json`; that file is not used as runtime input. No claim of completed PM/compliance approval or measured time savings is made.

Golub return extraction reconciles the summary percentage of 15.8% to the more precise 15.77% in the financial highlights. The matching NAV-based return is 8.98%, a difference of 6.79 percentage points; these have different definitions. Carlyle return chains use only Class I, not the Class N headline. KREF returns are derived from the disclosed reinvested-dividend index. Quarterly management fees and hurdles retain inputs, formulas and conditions when annualized. Cliffwater's fiscal transition includes a partial period, so its return chain remains unfilled rather than being incorrectly compounded as consecutive full years.

## Documents and reproducibility

The technical approach remains 3 pages and the solution brief 2 pages; all pages were rendered and visually inspected. The CLI can rerun from the downloaded source cache without network calls. Output files remain local and ignored by Git. GitHub CI verifies installation and tests separately from SEC connectivity.

## Remaining acceptance checks

1. Complete source-specific metric and interval-fund class mappings; audit representative cases against original filings.
2. Reconcile actual gross/net return differences and temporary fee waivers.
3. Verify leverage/yield definitions and matching-period NAV/shareholder return comparisons with the PM.
4. Obtain Dana's source approval or replacement Apex file.
5. Review the populated portable report with Dana, then complete PM and compliance gates.

## N-PORT and OCR extension validation

Reprocessed all 28 downloaded N-PORT XML reports (including amendments) using explicit namespace-aware paths. They contain 41,585 position observations across filing vintages and 103 monthly-return entries; these are not counts of unique investments or unique return months. All 28 reports satisfy total assets minus total liabilities equals net assets within $0.02. The latest Cliffwater and Carlyle reports contain 4,805 and 989 positions respectively. Monthly-return entries with no class ID remain unassigned. Borrowing ratios are review-only, so the supported headline coverage remains 26 current values and 21 historical observations. Raw structured exports retain confidence meanings, XML provenance and independent amendment records.

The downloaded competitor corpus contains no PDF exhibits. OCR was therefore validated with explicitly synthetic image-only and mixed native/scanned PDFs using the real installed Tesseract engine, not claimed as validation on a scanned competitor filing. The integration test recovers 1.25% and $12.34 from pixels, retains word boxes and page numbers, and proves that OCR values remain ineligible without recorded visual verification. Additional tests cover negative/low-confidence tokens, unavailable or disabled engines, timeout continuation, malformed PDFs, prevention of automatic qualification, and extraction errors distinct from SEC retrieval errors. CI installs the OCR runtime and engine and runs this integration test.

N-PORT regressions cover observation versus fiscal year-end, namespaces and SGML wrappers, missing/invalid/zero inputs, balancing failures, CIK/series/date mismatches, duplicate fields, external-entity rejection, position exports and spreadsheet formula escaping. Tests prevent fund-level net assets from becoming per-share NAV and calculated borrowing ratios from being accepted as quoted values.

## LLM judgment and evidence explanations

The OpenAI Responses integration is tested with controlled transport responses, not claimed as a live model evaluation. Tests cover selecting a quoted figure from an ineligible parser passage, consideration of competing sources, verbatim quote checks, source hashes, date/unit/basis constraints, exact existing calculations, OCR review gates, truncated packets, refusals, incomplete responses, cache replay and key exclusion. Ordinal confidence fields are removed from report exports in favor of evidence support, direct-versus-calculated provenance, decision author and written rationale.

A live API key was not configured during implementation validation. The 26 current and 21 historical values remain the parser baseline; do not describe them as LLM-validated. Model-quality validation must include actual answers, assessment of conflicting disclosures and confirmation that unsupported cases are withheld. The input budget is 600,000 characters per metric packet; any overflow is explicit and blocks publication. The model must assess each supplied passage, so large packets also need sufficient output budget. The system does not quietly drop evidence and publish anyway.
