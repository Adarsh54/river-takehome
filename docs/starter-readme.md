# Apex Ridge — build phase starter package

This package contains the starter data for the Apex Ridge engagement. The
full brief — the client, scope, metrics, competitor set, and deliverables —
is in your River workspace, and the client is available in your consultation
windows there.

## Contents

| File | What it is |
| --- | --- |
| `data/apex_ridge_fund_data.csv` | Apex Ridge's own fund metrics, Q1 2024 – Q4 2025 (8 quarters): quarterly and trailing net returns, NAV per share, AUM, fee terms, leverage ratio, distribution yield. This is the client's side of the comparison — input data, not an answer key. |
| `data/competitor_cik_list.csv` | The four competitor funds with their SEC CIK numbers — your keys into EDGAR. |
| `docs/board_deck_excerpt.md` | How the comparison is presented to the board today. Format reference only — every value is redacted. |

## The short version of the ask

Build a working system that pulls the competitor funds' filings from SEC EDGAR
(the real API — no mock data on the competitor side), extracts the benchmark
metrics from those filings, normalizes them, compares them against the Apex
Ridge data in this package, and produces an output the PMs could take to a
board meeting.

One thing to understand before you start: the manual process you're replacing
was the client's only source for these numbers — there is nothing to check
your output against. Your system must report, for every extracted value,
where it came from and how confident you are, and you must be able to defend
both. Establishing that confidence is the hard problem of this engagement.

Deliverables: a GitHub repo we can clone and run from your README, a 2–3 page
technical approach document (including your validation strategy and confidence
model), and a 1–2 page solution brief written for the client's CIO and
Managing Partner — the full spec is in the workspace brief.

Treat this like a real engagement: scope may evolve, and if something is
unclear, ask the client rather than assume. Your consultation windows are in
the workspace.
