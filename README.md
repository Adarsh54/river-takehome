# Apex Ridge - auditable competitor benchmarking

A local Python prototype for the Q4 2024 board cycle. It connects to SEC EDGAR, inventories filings published through **February 28, 2025**, parses source evidence, and exports a comparison plus a review queue. No mock competitor data. OpenAI interprets evidence and writes per-value rationales; the standard run requires an API key. Parser-only review is explicitly available with --llm off.

**Current validation status:** live SEC access works after configuring a real contact email. Live testing exposed and fixed N-PORT archive paths and oversized XML evidence extraction. The current run establishes 26 of 40 current comparison cells and 21 of 32 historical per-share observations, with review flags where appropriate. Definitions, formulas, rounding reconciliation and remaining gaps are explicit. PM/compliance approval and disputed Apex input approval remain outstanding. See the validation record for the latest run counts.

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
# OPENAI_MODEL=gpt-5.4
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

## What you receive

| Output | Purpose |
| --- | --- |
| `index.html` | Comparison, eight-quarter competitor NAV table, filing inventory, searchable source review queue |
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

The LLM receives current annual/interim reports and subsequent metric passages, retaining latest available evidence and baseline supported sources. Historical cells use exact reporting dates. Duplicate passages are consolidated; long unqualified blocks use label-centered excerpts with original character offsets. This is retrieval, not a claim that the entire filing was read by the model. If the 600,000-character packet budget omits evidence, publication is blocked and the omitted count is visible. Every supplied passage needs an assessment. Linked footnotes outside retrieved context can still require further retrieval or human review.

By default, `gpt-5.4` is used through the OpenAI Responses API with a strict output schema and `store=false`; override with `OPENAI_MODEL` or `--model`. No API key, request authorization header, or Apex CSV is written into model audit records. Prompt/input/model hashes bind cached judgments to their exact evidence. Refusals, invalid citations, incomplete responses, missing caches and transport errors never fall back silently to parser decisions. The response schema constrains format, not truth.

```sh
# Re-judge the downloaded real evidence without fetching SEC filings again:
apex-benchmark --from-audit output/live/audit.json --llm on --output output/llm
# Replay matching judgments without any model network call:
apex-benchmark --from-audit output/live/audit.json --offline --llm cached --output output/replay
# Explicit parser-only review; banner says the LLM has not assessed it:
apex-benchmark --from-audit output/live/audit.json --offline --llm off --output output/rules
```

A standard complete run assesses 40 current cells and 32 historical cells; requests are cached and model usage is retained. API charges apply. Saved audits must use the same engagement configuration; changing funds or dates requires rebuilding source evidence. The model can select a different quoted figure from a parser passage, or select an existing supported calculation. It cannot invent calculations, treat N-PORT borrowings as approved comparable leverage, or waive visual verification for OCR.

The current 26-value/21-observation coverage is the **parser baseline**, not a validated LLM result. Live model-quality validation remains pending until an API key is configured and real judgments are inspected. Official references: [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), [GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4).

## Documents

- [Implementation plan and client decisions](docs/implementation-plan.md)
- [Technical approach - 3 pages](docs/technical-approach.pdf)
- [Solution brief - 2 pages](docs/solution-brief.pdf)
- [Internal-data discrepancy note - draft, not sent](docs/apex-data-discrepancy.md)
- [Validation record](docs/validation.md) and [observed live result](docs/live-validation.json)
- [Original starter README](docs/starter-readme.md)

Regenerate written PDF deliverables with `python scripts/build_documents.py`. PDF runtime dependencies install with the project. Documentation source is in that script.

## Operational constraints and next validation

Keep SEC identification configured with a real contact. Manually audit a representative set of actual passages and conflicting disclosures; calibrate extraction rules before relying on coverage. Confirm the interval-fund class identifiers from those filings. Obtain Dana's approval or replacement Apex file. Review the populated output with Dana and confirm the portable format. Authentication, scheduled runs, signed approvals, extraction coverage targets, and market-data integrations are production follow-ups, not features claimed here.

Official references: [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [SEC developer resources](https://www.sec.gov/about/developer-resources). The tool fetches public evidence only; client data and generated outputs stay local unless you explicitly share them.

## N-PORT and OCR operation

`apex-benchmark --offline --llm off --ocr auto` reuses the real source cache and OCRs PDF pages with sparse selectable text (fewer than 120 alphanumeric characters). `--ocr always` also processes pages with a substantial text layer, useful for mixed image/text pages that the heuristic misses. `--ocr off` records a coverage error for each sparse page rather than silently treating it as undisclosed. Missing OCR dependencies, timeouts and empty results are explicit extraction errors and produce exit code 2. Native text and OCR failures on one page do not stop later pages.

OCR runs locally in English at 300 dpi, with a 90-second engine timeout and a 35-million-pixel page limit. OCR itself is local; LLM mode can send extracted public SEC passages to OpenAI for judgment. Install the `ocr` extra and the Tesseract system engine as above; without them, HTML and N-PORT extraction still work. Cache identity includes parser code, OCR mode, engine version and renderer version; failed OCR is retried on rerun. A recognition score describes transcription quality, not financial correctness. See the review workflow for `visual_verified`.

N-PORT mapping is an explicit subset, not a complete SEC taxonomy validator. It retains class identifiers where present but does not infer classes or turn monthly returns into annual returns. Holdings include reported USD values, balances, weights, categories, identifiers and debt terms where available; derivative-specific nested contracts and portfolio risk grids are not normalized. Missing fields remain null, and amendments are kept as distinct sourced reports. Totals reconciliation is a diagnostic, not an audit opinion. The holdings sum is not equated to total assets.

Mapping references: [SEC Form N-PORT instructions](https://www.sec.gov/files/formn-port.pdf), [SEC N-PORT technical specification](https://www.sec.gov/info/edgar/specifications/form-n-port-xml-tech-specs-1.3.htm), [Tesseract TSV output](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).
