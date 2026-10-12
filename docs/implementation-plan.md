# Implementation plan and acceptance criteria

1. Establish reproducible SEC access, immutable source cache, and dated filing inventory.
2. Discover submissions including historical pages; select filings publicly available by February 28, 2025 for the Q4 2024 board cycle. Capture annual/semiannual reports, quarterly reports, N-PORT, prospectuses/supplements and material earnings exhibits.
3. Parse inline XBRL, HTML tables and narrative text, and PDF text. Retain exact evidence and distinguish extraction candidates from defensible results.
4. Resolve sources per metric, period, share class and definition. Conflicts become review items; no guessed values. Keep contractual fees separate from effective rates and waiver terms. Listed-company returns must be shareholder returns.
5. Export a concise committee Word attachment, a separate detailed evidence Word document, portable PDF, HTML review view, long-form CSV and complete JSON audit record. Include eight quarter-end NAV observations where actually disclosed; no interpolated or carried-forward history.
6. Test cutoff handling, historic discovery, duplicate/amended sources, units, periods, definitions, gaps, evidence and internal-data gating. Exercise live SEC access and record failures honestly.
7. Deliver a private GitHub repository, a 3-page technical document and 2-page business brief.

## Confirmed client decisions

- February 28, 2025 is an agreed proxy for analyst preparation date, inclusive for date-only filing metadata.
- Q4 2024 is the target cycle; older competitor periods must be visible.
- Latest metrics except eight quarters of competitor NAV. Apex history starts Q1 2024, with four quarters through target date, once approved.
- Contractual management fee primary; disclosed effective fee, waiver conditions and expiry alongside.
- Golub/KREF: total shareholder returns; flag disclosed NAV-return differences.
- Keep KREF, correctly classified as a mortgage REIT. Do not imply leverage/yield definitions are identical.
- Gaps are preferable to unsupported numbers. A retrieval failure is not non-disclosure.
- PM reviews, then compliance must locate each figure in the original source. Prototype output is a review draft until those gates complete.

## Open items

- Dana disputes supplied Apex data provenance. No internal number is published until documented approval.
- Comparative LP-letter language remains pending approved Apex data and PM confirmation of comparable definitions and periods. The Word summary states this limitation explicitly.
- Confirm precise institutional share-class identity against filings; ambiguous class remains a review item.
- No client-defined threshold for meaningful NAV/shareholder return divergence; display disclosed differences rather than invent a business threshold.


## Follow-up consultation requirements

Dana confirmed the following in the follow-up consultation supplied by the user:

- New-scope priority: formatted Word attachment first, custom metrics second, fund browser third. Cliffwater and Carlyle remain the highest-priority competitors.
- A PM or analyst supplies the metric definition and likely filing labels; adding or revising a metric must not require code changes. Weighted average spread is the example request.
- Ares is the likely next fund, with portfolio turnover the immediate question. New funds follow the same search, add, retrieve and review workflow as existing funds.
- The main Word attachment contains Apex alongside all selected competitors, visible reporting periods, a filing/period/locator reference per reported value, methodology differences, and a two- or three-sentence summary. Keep the main attachment sparse; detailed evidence and NAV history remain in a separate Word document.
- The summary cannot claim Apex outperformance or relative positioning while its internal source remains disputed. Source approval alone also does not establish comparable methodology; comparative LP language requires PM review.
- Institutional share classes are the default where available. Show the selected class in each comparison header and disclose that class selection must be verified against the filing. Never silently replace it with another class.
- Normalize only when defensible; preserve and disclose incompatible definitions. Neither an identical label nor matching units proves comparability.
