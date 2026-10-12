# Validation record

Development validation: October 12, 2026. Historical comparison cutoff remains February 28, 2025; run date is not the financial reporting period.

## Automated checks

`pytest -q`: 20 passing tests at the final local validation checkpoint. Tests cover structured units/scales and locations, ambiguous dimensions/share classes, historical filing discovery, inclusive cutoff, future-period exclusion, conflicts, stale fallback prevention, evidence-bound decisions, waiver-term retention, explicit shareholder-return tables, cache integrity, internal-data gating and complete error-state PDF/HTML/CSV/JSON exports. Synthetic test fixtures are clearly identified and never used as competitor report data.

## Live SEC smoke run

Executed the actual CLI with `--refresh`, identifying the application and its GitHub project contact. Requests to all four `data.sec.gov/submissions/CIK....json` endpoints returned HTTP 403. Exit status was 2. Output recorded four retrieval errors, 40 unavailable current metric cells, zero invented competitor values and withheld Apex data. A real SEC contact email has been requested; it is not embedded in the repository.

No financial extraction accuracy, actual source conflict resolution, source reconciliation, eight-quarter NAV coverage or operational time savings can be claimed from this run. Those are outstanding acceptance checks after permitted SEC access succeeds. A contact header change may not resolve a network-level rejection.

## Document QA

Technical approach: 3 pages. Business solution brief: 2 pages. Benchmark failure report: 6 pages. PDF text extraction confirmed review-draft labels and absence of unapproved internal values. All document pages were rendered and visually inspected for clipping, overlap and readability. Generated benchmark outputs stay local and ignored by Git. GitHub Actions also passed on the initial pushed implementation; subsequent export fixes are covered by local regression tests.

## Remaining acceptance checks

1. Retrieve actual eligible filings for all four competitors and verify selected documents/exhibits against the inventory.
2. Confirm institutional share classes and calibrate table/text rules against their real layouts.
3. Manually audit supported figures and unknowns; test actual gross/net discrepancies and fee waivers.
4. Verify leverage/yield definitions and matching-period NAV/shareholder return comparisons with the PM.
5. Obtain Dana's source approval or replacement internal file.
6. Review the populated portable report with Dana, then complete PM and compliance gates.
