# Apex Ridge - auditable competitor benchmarking

A local Python prototype for the Q4 2024 board cycle. It connects to SEC EDGAR, inventories filings published through **February 28, 2025**, parses source evidence, and exports a comparison plus a review queue. No mock competitor data. OpenAI interprets evidence and writes per-value rationales; the standard run requires an API key. Parser-only review is explicitly available with --llm off.

**Current validation status:** live SEC access works after configuring a real contact email. Live testing exposed and fixed N-PORT archive paths and oversized XML evidence extraction. The parser baseline establishes 26 of 40 current comparison cells and 21 of 32 historical per-share observations, with review flags where appropriate. The live LLM run retains 17 current values and 17 historical observations; interpretation and validation gaps remain explicit. Definitions, formulas, rounding reconciliation and remaining gaps are explicit. PM/compliance approval and disputed Apex input approval remain outstanding. See the validation record for the latest run counts.

The supplied Apex Ridge file is preserved but **withheld by default**: Dana disputes its provenance and its dates through Q4 2025. Approving the source is a separate client action. Competitor extraction runs independently.

## Install and run

Python 3.11 or newer; run from the repository root:

```sh
git clone https://github.com/Adarsh54/river-takehome.git
cd river-takehome
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,ocr]'
# OCR engine (macOS):
brew install tesseract
# Ubuntu/Debian instead: sudo apt-get install tesseract-ocr tesseract-ocr-eng
# Put these in the ignored .env file (loaded automatically):
# SEC_USER_AGENT='ApexBenchmark/0.1 Your Name your-real-contact-email@your-domain.com'
# OPENAI_API_KEY=<your key>
# OPENAI_MODEL=gpt-6.1-sol
export SEC_USER_AGENT='ApexBenchmark/0.1 Your Name your-real-contact-email@your-domain.com'
apex-benchmark --refresh
```

Replace the contact with your real details. SEC requests need an identifying User-Agent; a declared contact does not guarantee that SEC will allow a particular network. The application caps requests at four per second, backs off for transient errors, stops a fund's document loop on 403, and never circumvents denial.

The repository is private; cloning requires authorized GitHub access. Installation requires internet. SEC retrieval also requires access to `data.sec.gov` and `www.sec.gov`.

Open `output/latest/index.html` directly or serve it locally:

```sh
python -m http.server 8000 --bind 127.0.0.1 --directory output/latest
```

Visit http://127.0.0.1:8000. There is no hosted application or authentication. In LLM mode, selected public SEC passages are sent to OpenAI; the disputed Apex CSV is excluded from model input.

## Interactive workspace: funds, custom metrics and Word

```sh
apex-workspace
```

Open http://127.0.0.1:8766. Search EDGAR by company/fund name, ticker or CIK; select a registrant, confirm structure, share class and return basis, then add it to the comparison. The browser uses SEC company and mutual-fund ticker directories, the SEC name/CIK directory, and live submissions metadata. Those directories are incomplete: if a ticker returns nothing, search by name or CIK. A registrant can contain multiple series/classes; select the intended identifiers and inspect source scope before accepting values. Search results are registrants, not an endorsement that every company is a comparable fund. The local workspace supports up to 20 comparison entries.

Add a custom metric with a precise definition, unit, measurement period, fund/share-class scope and literal search phrases. The three example buttons are editable starting definitions. Optionally list context to document, such as reference rate, fee/floor treatment, weighting, coverage and timing. Known context needs a verbatim citation; unknown context stays explicit. The spread example defaults to portfolio weighting at quarter end, records that assumption, and never treats matching labels as proof of comparability. Save, then run the comparison. Matching HTML tables, narrative and native PDF text become cited evidence for OpenAI judgment. Custom metrics support **explicitly reported values only**; arbitrary formulas and custom N-PORT field mappings are not implemented. OCR passages already collected by the core pipeline can contribute, but custom-only terms on scanned pages can be missed. Search phrases and retrieval coverage constrain recall; a blank means unresolved, not necessarily undisclosed.

Definitions are stored in ignored `config/workspace.json`, snapshotted for each run, included in the model request and exported with results. Editing a definition invalidates its matching judgment cache. A new fund triggers SEC discovery and extraction; a definition-only change can reuse an existing source audit. Runs execute in the background with status, elapsed time and logs. A completed run includes source preparation, AI review and export timings in `timings.json`; saved-audit reuse is labeled separately from retrieval. OpenAI mode can incur API charges; parser-only mode leaves custom values for review; cached mode makes no network calls and shows gaps when no exact judgment is cached. One run executes at a time. Reports reflect the configuration at launch, not later edits.

The **Download committee Word** link produces `benchmark.docx`: a short review summary, comparison tables with selected share classes and reporting dates, metric definitions, and numbered source/methodology notes for every reported current figure. The separate **Detailed evidence Word** (`benchmark-evidence.docx`) retains full rationales, gaps, conflicting evidence, calculations and NAV history. Wide comparisons are split into groups of four funds. The dashboard keeps the full extraction queue in a separate `candidates.html` page so thousands of candidate passages do not slow the main comparison view. Both documents are generated by the CLI and workspace. The summary explicitly withholds Apex relative-position claims while internal provenance is unresolved; approving the source alone does not establish comparable definitions or authorize automatic LP language. PM/compliance approval remains required.

This is a single-user localhost application, not a hosted service. It binds to 127.0.0.1, checks request origins and uses a local request token for changes. Keep the project and evidence cache private. On restart the workspace loads saved settings; select an existing report with `apex-workspace --report output/path` or run again.

## What you receive

| Output | Purpose |
| --- | --- |
| `index.html` | Comparison, eight-quarter competitor NAV table, filing inventory, searchable source review queue |
| `benchmark.docx` | Formatted committee package with comparison, definitions and per-value evidence notes |
| `benchmark.pdf` | Portable review package with the same flags, definitions and source evidence |
| `benchmark.csv` | Editable long-form data with status, period, definitions and source references |
| `nport.json` | Structured fund totals, borrowing fields, monthly return entries, holdings and balance checks with XML provenance |
| `nport-holdings.csv` | Position-level values with source URL, hash and XML path |
| `judgments.json` | Model decisions, all considered passages, competing-figure assessments and validation outcomes |
| `audit.json` | Full configuration, source hashes, candidates, selection reasons, errors and recorded reviewer decisions |

All formats say REVIEW DRAFT. Publication still requires PM and compliance review. Unscoped narrative guesses are kept in the review queue rather than treated as comparable facts. A missing result is not silently replaced by an older value. Retrieval failure is distinguished from unresolved extraction; neither is asserted to be non-disclosure.

## Repeat a run and review evidence

```sh
# Reuse real downloaded evidence, with zero network calls:
apex-benchmark --offline --llm cached
# Apply evidence-backed reviewer interpretations:
apex-benchmark --offline --llm cached --decisions output/decisions.json
# Check current SEC discovery rather than using cached URL responses:
apex-benchmark --refresh
# Verify behavior without contacting SEC:
pytest -q
```

Exit codes: 0 = pipeline completed (may still contain review gaps); 2 = retrieval incomplete or invalid inputs. Always inspect the audit coverage and status counts. Offline mode is not a demo fixture: an empty cache produces explicit failures. Raw sources are retained under `.cache/sec`, with SHA-256 verification. Cached runs preserve the original retrieval time.

See [review workflow](docs/review-workflow.md) for decision format, evidence support explanations and internal-data approval. Do not paste unsupported values into the report. Reviewer edits bind to immutable evidence IDs and require quoted source text, a named reviewer and a rationale.

## Financial rules from consultation

- Q4 2024 comparison; filings on or before February 28, 2025 (inclusive date-only convention). Filing date and reporting period are both retained. No later filings leak into this historical view.
- Latest available supported value at or before target period. Eight quarter-end NAV observations for competitors, with explicit gaps and no carry-forward. Approved Apex history starts Q1 2024.
- Contractual management fee primary; effective rate only when disclosed. Waiver dates and conditions remain in supporting passages and reviewer rationale.
- Golub (GBDC) and KREF: total shareholder return, including distributions. Interval funds: net NAV return for the intended class. Never label different return bases as identical.
- KREF is a **mortgage REIT**, not a BDC. Book value per common share is labeled separately from fund NAV. Leverage and distribution definitions are preserved rather than forced into false equivalence.

## How extraction works - and its limits

SEC submissions discovery includes historical filing-list pages, not only recent records. The inventory selects financial reports, portfolio reports, prospectuses/supplements and current reports across the lookback. Complete submissions preserve HTML/text/XML exhibits; PDF exhibits are retrieved separately. Sources are parsed into reproducible locations and complete relevant passages.

Deterministic extraction supports selected inline-XBRL per-share tags, KREF book-value tables with explicit date-column spans, and simple explicitly labeled return tables. Text rules locate rates and relevant narrative, footnotes and tables. Ambiguous units, share classes, return definitions, merged table layouts and most narrative rates require reviewer confirmation. PDF text is searchable evidence; sparse-text pages use local Tesseract OCR when installed. OCR candidates retain page numbers, word boxes, recognition scores and rendering settings, and require visual verification before acceptance. N-PORT XML maps fund totals, all eight B.2.c borrowing components, selected other liabilities/cash fields, monthly return entries and holdings. It uses repPdDate (observation date), not repPdEnd (fiscal year-end), and checks assets minus liabilities against net assets. XML paths, raw values and source hashes remain available in nport.json. Total net assets are not NAV per share; unassigned monthly return classes are never guessed. Derived N-PORT borrowing/net-asset ratios remain review candidates because their scope is not automatically comparable to reported debt/equity. Narrow disclosure rules distinguish current contractual fees from old rates, target ranges and expense ratios. Trailing returns can be calculated from consecutive annual total returns or a disclosed reinvested-dividend index; formulas and original inputs are exported. Quarterly fee/hurdle percentages can be annualized with explicit conditions. Unsupported leverage or yield conversions stay unavailable. Cliffwater return chaining is deliberately disabled because its fiscal transition includes a partial period.

There are no ordinal confidence tiers. Each value states whether evidence is linked, whether the value is directly reported or calculated, why it was selected, and what remains unresolved. A linked quote proves traceability, not that every financial interpretation is correct. The LLM performs semantic judgment; Python validates source hashes, exact quotations, dates, units, required definitions and supported calculations. A confident model statement cannot substitute for a citation. PM and compliance approval remain separate.

The LLM receives current annual/interim reports and subsequent metric passages, retaining latest available evidence and baseline supported sources. Historical cells use exact reporting dates. Duplicate passages are consolidated; long unqualified blocks use label-centered excerpts with original character offsets. This is retrieval, not a claim that the entire filing was read by the model. If the 600,000-character packet budget omits evidence, publication is blocked and the omitted count is visible. The model selects numbered passages and explains material competing figures. The application restores source text from the index and verifies every selected passage ID; quotes are not regenerated by the model. Linked footnotes outside retrieved context can still require further retrieval or human review.

By default, `gpt-6.1-sol` is used through the OpenAI Responses API with a strict output schema and `store=false`; override with `OPENAI_MODEL` or `--model`. No API key, request authorization header, or Apex CSV is written into model audit records. Prompt/input/model hashes bind cached judgments to their exact evidence. Refusals, invalid citations, incomplete responses, missing caches and transport errors never fall back silently to parser decisions. The response schema constrains format, not truth.

```sh
# Update only changed metric definitions against saved evidence:
apex-benchmark --config config/workspace.json --from-audit output/live/audit.json --llm on --output output/llm
# Replay matching judgments without any model network call:
apex-benchmark --from-audit output/live/audit.json --offline --llm cached --output output/replay
# Explicit parser-only review; banner says the LLM has not assessed it:
apex-benchmark --from-audit output/live/audit.json --offline --llm off --output output/rules
```

A standard complete run assesses 40 current cells and 32 historical cells; requests are cached and model usage is retained. API charges apply. Saved audits may change custom definitions and funds: only changed metrics and new/changed funds are reviewed. A date change requires a fresh inventory check; `--from-audit ... --refresh` reuses unchanged accessions and ingests only new or changed ones. Unrelated saved gaps remain gaps until explicitly retried with `--retry-unfinished` (unfinished or truncated reviews) or `--repair-gaps` (all unresolved cells). Pass the revised `--config` when using `--from-audit`. The model can select a different quoted figure from a parser passage, or select an existing supported calculation. It cannot invent calculations, treat N-PORT borrowings as approved comparable leverage, or waive visual verification for OCR.

Temporary rate limits receive up to three retries with bounded backoff; quota and billing failures do not. If a structured judgment fails evidence validation, the model receives one correction request containing the failed decision and validator feedback. Both attempts are retained, separately cached, and subject to the same checks. An unsuccessful correction leaves the value blank. Offline replay never sends correction requests over the network.

The 26-value/21-observation coverage is the **parser baseline**. After resuming the five billing-blocked cells, the live OpenAI run retained **17 current values and 17 historical observations** after local validation. Of 72 cells, 59 had accepted publish/withhold decisions; twelve responses failed validation and one had no retrieved evidence. No cells remain blocked by API billing. Some structurally valid withholding decisions incorrectly interpret dates or metric definitions, so this remains a diagnostic run, not board-ready financial validation. See [live LLM validation](docs/llm-live-validation.json). Official references: [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), [GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4).

## Documents

- [Implementation plan and client decisions](docs/implementation-plan.md)
- [Technical approach - 3 pages](docs/technical-approach.pdf)
- [Solution brief - 2 pages](docs/solution-brief.pdf)
- [Internal-data discrepancy note - draft, not sent](docs/apex-data-discrepancy.md)
- [Scope-update validation](docs/scope-validation.json): live Ares discovery and three custom-metric judgments
- [Validation record](docs/validation.md) and [observed live result](docs/live-validation.json)
- [Original starter README](docs/starter-readme.md)

Regenerate written PDF deliverables with `python scripts/build_documents.py`. PDF runtime dependencies install with the project. Documentation source is in that script.

## Operational constraints and next validation

Keep SEC identification configured with a real contact. Manually audit a representative set of actual passages and conflicting disclosures; calibrate extraction rules before relying on coverage. Confirm the interval-fund class identifiers from those filings. Obtain Dana's approval or replacement Apex file. Review the populated Word package with Dana. Authentication, scheduled runs, signed approvals, extraction coverage targets, and market-data integrations are production follow-ups, not features claimed here.

Official references: [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [SEC developer resources](https://www.sec.gov/about/developer-resources). The tool fetches public evidence only; client data and generated outputs stay local unless you explicitly share them.

## N-PORT and OCR operation

`apex-benchmark --offline --llm off --ocr auto` reuses the real source cache and OCRs PDF pages with sparse selectable text (fewer than 120 alphanumeric characters). `--ocr always` also processes pages with a substantial text layer, useful for mixed image/text pages that the heuristic misses. `--ocr off` records a coverage error for each sparse page rather than silently treating it as undisclosed. Missing OCR dependencies, timeouts and empty results are explicit extraction errors and produce exit code 2. Native text and OCR failures on one page do not stop later pages.

OCR runs locally in English at 300 dpi, with a 90-second engine timeout and a 35-million-pixel page limit. OCR itself is local; LLM mode can send extracted public SEC passages to OpenAI for judgment. Install the `ocr` extra and the Tesseract system engine as above; without them, HTML and N-PORT extraction still work. Cache identity includes parser code, OCR mode, engine version and renderer version; failed OCR is retried on rerun. A recognition score describes transcription quality, not financial correctness. See the review workflow for `visual_verified`.

N-PORT mapping is an explicit subset, not a complete SEC taxonomy validator. It retains class identifiers where present but does not infer classes or turn monthly returns into annual returns. Holdings include reported USD values, balances, weights, categories, identifiers and debt terms where available; derivative-specific nested contracts and portfolio risk grids are not normalized. Missing fields remain null, and amendments are kept as distinct sourced reports. Totals reconciliation is a diagnostic, not an audit opinion. The holdings sum is not equated to total assets.

Mapping references: [SEC Form N-PORT instructions](https://www.sec.gov/files/formn-port.pdf), [SEC N-PORT technical specification](https://www.sec.gov/info/edgar/specifications/form-n-port-xml-tech-specs-1.3.htm), [Tesseract TSV output](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).

## Incremental execution and the five-minute target

A metric edit is an update, not a full rebuild. The local workspace compares the saved report configuration with the new configuration. Editing spread retrieves only spread evidence and reviews one cell per fund; returns, fees, turnover, default rate and all historical NAV decisions remain unchanged. Adding a fund discovers and reviews only that fund. Removing a metric or fund requires no AI review. An unchanged configuration reuses every decision.

HTML tables, paragraphs, adjacent footnotes and native PDF page text are indexed once in `.cache/sec/passages/`, keyed by document SHA-256 and parser version, independently of metric definitions. Structured N-PORT and OCR outputs remain in the source audit with their original checks. Original source bytes are checksum-verified on reuse. Legacy audits can be migrated ahead of an interactive session:

```sh
python scripts/index_saved_sources.py output/live/audit.json
```

Independent AI reviews use three workers by default (`--review-concurrency 1` through `4`). Each worker has its own HTTP session. Validated publish **and withhold** decisions are checkpointed immediately in `.cache/sec/decisions/`, so an interrupted run does not discard completed work. Checkpoints bind the exact evidence packet, model, reviewer implementation and retrieval errors. Numbered source selections are checked locally and resolved to original quotations; unknown passage IDs, unsupported numbers, wrong periods/classes and unapproved calculations cannot publish.

The dashboard shows elapsed time, phase durations, affected review count, reused results and documents parsed. Five minutes is the target for updates to already indexed funds, not a promise for arbitrary cold ingestion, provider outages or twenty new funds. No cutoff silently drops evidence to meet the target. `timings.json` distinguishes live model responses from saved decision reuse.

Reports consume saved decisions. The website serves existing files; opening the dashboard or downloading Word never invokes source extraction or AI. To regenerate report files only:

```sh
apex-benchmark --render-audit output/llm/audit.json --output output/rendered
```

To intentionally retry old unfinished reviews as well as new changes, add `--retry-unfinished`. This is explicit so a small edit never unexpectedly retries the entire matrix. Review draft status and human approval requirements remain unchanged.

Measured local demonstration: a spread-only edit across five funds completed in **17.6 seconds** (three live OpenAI reviews, two explicit evidence gaps), preserved 100 unrelated results exactly, and parsed zero documents. An unchanged rerun took **2.2 seconds** with zero model calls. Dashboard reload: **0.12 seconds**; Word download initiation: **0.30 seconds**. These are single warm-run observations, not a cold-ingestion guarantee. See [timing and preservation evidence](docs/incremental-validation.json).

## Gap repair and source refresh

The workspace Action menu separates ordinary metric updates, retries of unfinished AI reviews, reassessment of all unresolved values, and checks for new SEC filings. Concurrency is configurable from one to four. Current values use the latest supported observation with its actual date; historical NAV cells use their requested quarter as the review target. Full table headers, cell positions and adjacent context are recovered from the saved passage index. Unrelated undated prospectus text and hypothetical dilution examples are excluded from NAV observation retrieval, with excluded counts retained in the audit. Exclusion is a documented retrieval rule, not proof of non-disclosure.

The dashboard and Word outputs distinguish evidence not found, pending AI review, failed AI review, incomplete evidence context, and reviewed values that were not established. They do not call every blank “not disclosed.” A source-backed result still needs PM and compliance review.

```sh
# Explicitly repair existing unresolved cells; leave supported cells unchanged.
apex-benchmark --config config/workspace.json --from-audit output/latest/audit.json --repair-gaps --review-concurrency 3 --output output/repaired
# Refresh SEC inventories; ingest only new/changed accessions and review changed dependencies.
apex-benchmark --config config/workspace.json --from-audit output/repaired/audit.json --refresh --output output/refreshed
```

Refresh compares accession, form, filing date, reporting date and primary-document metadata. Amendments have separate accession identities. Identical source inventories need no document fetch, parsing or AI. Metadata changes on an existing accession trigger content revalidation; a silent server-side rewrite with no inventory metadata change is outside this incremental check and requires a deliberate full content refresh. Checksums still verify cached source integrity before model review. Rate limits remain explicit errors; they do not become fake financial gaps. Completed decisions survive interruption, and worker/provider failures produce review items rather than crashing the entire export.

The decision path uses **one evidence-grounded LLM decision per affected cell**, not a separate LLM verifier. Code checks source integrity, numbered citations, cutoff and observation dates, units, and supported calculations. A validation failure permits one correction request; unresolved conflicts or interpretations remain visible for PM review. Quarterly rates are labeled in the comparison itself. Incentive participation rates and hurdle thresholds are separate metrics.

The gap-repair audit improved the saved five-fund comparison from 18/65 to 41/65 current values and from 17/40 to 32/40 historical NAV observations. During repair, an Ares incentive rate was corrected from its 1.75% quarterly hurdle to the 20% participation rate. The remaining quarterly hurdle is labeled explicitly. At that repair checkpoint, gaps included five searches without retrieved evidence and one oversized evidence context, alongside reviewed but unestablished values; none is automatically called non-disclosure. These are coverage counts, not certified accuracy scores.

A live website SEC refresh took 4.8 seconds, reused 267 unchanged filings and all 105 decisions, and made zero model calls with zero documents parsed. Dashboard reload took 0.145 seconds; Word download initiation took 0.259 seconds. The main resumed repair took 175.5 seconds, followed by targeted retries and corrections. The entire development/repair session was not a single five-minute run. See `docs/gap-repair-validation.json` for stages, preserved results, corrections and remaining limitations; `docs/incremental-validation.json` records the earlier 17.6-second spread-only edit. Cold ingestion remains separately measured.

### Conflicts and comparison rules

The initial LLM review distinguishes different arrangements (contractual versus effective fees, waivers and different classes) from a disagreement about the same measure, date and class. A newer filing alone is not an authoritative correction. An unresolved disagreement has no accepted value and is labeled **Unresolved conflict — PM review required**. HTML, committee Word and the evidence Word retain both candidate figures, explanations, SEC links and passage locations; CSV/JSON retain the structured alternatives. The code checks each quoted candidate number, its date/unit, and citation. Conflict handling does not add a second model call.

Rules can be versioned per metric in the configuration. For example:

```json
"comparison_policies": {
  "management_fee": {
    "version": "2",
    "instructions": "Show the contractual fee as primary. Preserve any disclosed waiver expiration and effective-fee distinction."
  }
}
```

Changing a rule's version or instructions reassesses only that metric across the selected funds, reusing saved passages; changing a NAV rule also reassesses its history. Use `"*"` for a deliberately shared rule affecting all metrics. Policies are passed to the model, included in request/checkpoint identities, and snapshotted in the audit. A changed policy clears the affected accepted values until reassessment completes, including when AI is disabled. It does not trigger filing downloads or reparsing. A source refresh with an unchanged inventory also honors these rule changes. Code citation/date/calculation checks cannot be overridden by a policy.

Older audits without policy snapshots retain their saved decisions; their prior configuration supplies the initial comparison baseline. Use explicit reassessment to revisit older decisions under the new conflict contract. This preserves earlier evidence and avoids silently re-reviewing the entire saved comparison. New reviews use the versioned contract; later policy changes invalidate the corresponding saved decisions automatically.

### Targeted effective-fee retrieval

Effective management fees now search the saved, metric-independent passage index for management/advisory fees, fee waivers and expense caps. Legal waiver wording alone no longer selects a passage. Overlapping neighborhoods merge; complete matched tables retain column positions, nearby introductions and numbered footnotes. Narrative XBRL tables do not repeat an entire note in both text and cell data. Exact contained prose within the same filing is deduplicated with duplicate locations retained in the retrieval audit. Different filings remain distinct. The index search includes contractual-fee source documents to distinguish contractual rates from effective fees. Missing indexes preserve original evidence rather than silently reparsing.

The targeted GBDC effective-fee review took **12.6 seconds**, used **one live model response**, parsed **zero documents**, and left **104 other results identical**. No retrieved evidence was omitted for packet size. It remains a reviewed gap: contractual rates, dollar fees and annualized SEC expense-table presentations were not accepted as an established effective fee. The rationale and citations are saved; an incomplete-context label is no longer the reason. This is one warm decision, not a guarantee for cold ingestion or every custom metric. See `docs/fee-retrieval-validation.json`.

### GPT-6.1 Sol trial

A targeted model-only trial on the same GBDC effective-fee evidence completed in **18.9 seconds**, with one live response, zero reparsing and 104 other decisions unchanged. Sol accepted the **1.56% annual management-fee expense ratio dated September 30, 2024**, preserving its period-end net-assets denominator and lag. GPT-5.4 had withheld this value. Source/definition checks passed; this one example does not establish overall accuracy or a speed improvement (the earlier GPT-5.4 run took 12.6 seconds). Estimated standard API cost was $0.44, including reported cache writes. Following this trial, GPT-6.1 Sol is the default for new reviews. Existing saved decisions retain their original model provenance and are not automatically rerun. Override the default with `OPENAI_MODEL` or `--model`. See `docs/sol61-model-trial.json`.

### Publication approval gate

In the local workspace, review the dashboard and use **Publication approval** to exclude any figure that cannot be located in its original source. Exclusion removes the figure from the comparison and regenerated exports; its original decision remains in `publication-exclusions.json` for investigation. Record separate PM and compliance attestations for the displayed report version. Word, PDF and CSV download routes return HTTP 403 until both approvals exist. Changes to the audit or any package file invalidate approvals automatically. No AI review runs during approval or exclusion.

This is a local application gate, not authenticated enterprise access control: reviewer names are self-entered, and a user with filesystem access can read generated files directly. CLI-generated artifacts are review outputs, not authorization to circulate. Production requires authenticated reviewer roles and controlled artifact storage. Approval records are stored beside the report in `publication-approvals.json` and bind to hashes of the audit and export files.
