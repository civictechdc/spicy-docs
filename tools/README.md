# Corpus diagnostics

Use these tools to investigate retained releases or publisher metadata. They
produce measurements and do not ship in the installed package.

Run them from the repository after [contributor setup](../CONTRIBUTING.md):

```sh
uv run --frozen python -m tools.analysis.observation_census --help
```

Keep reports with their inputs and command receipts outside the repository.
Each diagnostic answers one question; it does not verify a whole release.

## Compare local evidence

These four commands write JSON to stdout:

- [compare_source_native_releases](analysis/compare_source_native_releases.py):
  compare added, removed, and changed records. Supply two release roots, a shared
  blob store, and explicit identity fields. Verifies blob digests, not full release
  admission.
- [cross_filing_census](analysis/cross_filing_census.py): count regulations.gov
  document or docket identities across releases. Supply `[root, artifactDigest,
  profile]` triples and a blob store. Counts name their populations; source records
  and downstream catalog items differ.
- [observation_census](analysis/observation_census.py): count retained observations,
  including those publication discarded. Supply a release root, blob store,
  artifact pin, verifier id, and source profile. Record and observation counts differ.
- [fr_discarded_distinctness](analysis/fr_discarded_distinctness.py): compare content
  across Federal Register observations sharing a document number. Supply a release
  root and blob store. Reproduces evidence for compound identity without interpreting
  the number's year.

## Check GovInfo metadata

These commands use the network and write append-only JSONL:

- [govinfo_granule_census](analysis/govinfo_granule_census.py): compare exact document
  numbers with keyless issue MODS granule ids in both directions. Supply a Federal
  Register release root, blob store, upper date bound, and output path. Missing or
  failed listings leave missing evidence; a mismatch alone does not prove a missing
  document.
- [govinfo_resolve_unmatched](analysis/govinfo_resolve_unmatched.py): check fused
  identifiers left unmatched by MODS. Supply the prior census, an explicit credential
  file, and output path. Only complete, populated listings support `fused-match` or
  `not-listed`; the latter describes this endpoint, not all GovInfo holdings.

Both outputs record `sourceReleaseDigest` and resume only against the same source
release. Rows lacking that digest require a fresh output file. The resolver also
retries when an issue's requested unmatched-number set changes.

- [legislative_data_map](analysis/legislative_data_map.py): measure what each
  Congress.gov and GovInfo collection route lists and from when, sample the
  publisher XML candidates, compare overlapping routes, follow every
  cross-source reference on real items, and rewrite the generated tables in
  `docs/research/legislative-data-map-2026-09-18.md` from those measurements
  and the judgments held in the tool. Supply an explicit credential file, the
  JSON output path and the map path. A full run measures everything;
  `--freshness`, `--floors`, `--samples`, `--compare` and `--flow --sample N`
  re-measure one part and merge it; `--offline` rewrites from the saved output;
  `--diff PREVIOUS.json` prints what moved. Coverage is a lower bound from a
  capped walk, never proof of absence; a freshness date is a floor where the
  API ignored the sort. `tests/test_legislative_data_map_tool.py` renders the
  saved output and proves every `have` or `port` row against its evidence file.

- [reconstruction_benchmark](analysis/reconstruction_benchmark.py): build the
  paired CFR corpus, reconstruct each section from its PDF with the XML
  hidden, and score text precision and recall, hierarchy F1, critical
  discrepancies, coverage and wall time against the XML that was hidden; then
  rewrite the generated block in
  `docs/research/reconstruction-benchmark-2026-09-19.md`. Supply an explicit
  credential file (one keyed route, the granule listing; both body routes are
  keyless), the JSON output path and the report path. `--sections` sets the
  corpus size and `--max-requests` bounds the run. `--rescore --scratch DIR`
  re-reads the bodies an earlier run left there, checking each digest against
  the one that run recorded, so changing a parsing rule costs no request;
  `--offline` re-renders the report from the saved output; `--receipts DIR`
  retains the command, the run log, the request log and the corpus manifest
  outside this repository. Splits are whole editions, so no volume's
  typography reaches two splits — but a split only pays on a run whose rules
  were fixed before it read the corpus, which the document states for each
  run. `tests/test_reconstruction_benchmark_tool.py` renders the committed
  block from the committed sidecar and fails if they have drifted apart.
- [bill_html_xml_gap](analysis/bill_html_xml_gap.py): measure how far a bill's
  HTML rendition is from its XML, to size the reconstruction profile gap B1 and
  §3.1 of the closing-the-gaps proposal name. Fetches a paired corpus of 113th
  and 114th bill versions that offer both renditions, parses the XML through
  `parse_bill_tree` as the reference, derives text from the HTML through
  `extraction.body_text`, and reports text fidelity, per-kind structure
  precision and recall, the element inventory, and the same rules run on
  pre-113th HTML with no XML to score against. Supply an explicit credential
  file, a cache directory for the fetched bytes, the JSON output path and the
  document path. At most 90 requests **per process**; the cache is reused, so a
  rerun against a full cache makes none.
  **Two corpora.** The rules were revised against the default `tuning` draw, so
  its score is an in-sample upper bound. `--selection held-out` draws the same
  listings at disjoint quantiles, excludes every tuning package id, refuses on
  any overlap, and merges an untuned score into the sidecar's `heldOut` block;
  that is the figure the document leads with. `--quantiles` and `--listings`
  override either draw. `--offline` rewrites
  `docs/research/bill-html-xml-gap-2026-09-19.md`'s generated block from the
  saved measurement. Precision and recall are measured against one engine's
  reading of the XML, never against the publisher's intent; the bill DTD is
  pinned by digest and cited, **not validated against**; and the title-level
  contents-list form is unscored in both draws.
  `tests/test_bill_html_xml_gap_tool.py` renders the block from the committed
  sidecar, pins each rule against a constructed print sample and against the
  real GPO bytes in `tests/fixtures/govinfo_bill_html/`, and proves the two
  corpora disjoint.

- [pdf_family_rollup](analysis/pdf_family_rollup.py): measure what the ten
  PDF-only families of the [census](../docs/research/pdf-only-corpus-2026-09-19.md)
  would add as hosted tables. `acquire` samples each family's index record and up
  to eight of its documents, over three request classes — keyless, keyed
  (`API_GOV`, header only) and Zyte for the two routes the census recorded as
  walled — writing every request to `requests.jsonl` and every body to
  `blobs/<sha256>`; it is resumable and re-requests only what has no retained
  body. `analyze` makes no request: it extracts each retained PDF with
  `tables=True`, strips GPO print artifacts, and reports per family which join
  keys and which structured content the documents hold **that the index does not
  already state** — the owner's rule that existing data is not recreated, made
  measurable by reading the same rule off both sides and reducing both to one
  canonical key. The report is
  [`docs/research/pdf-family-rollup-yield-2026-09-20.md`](../docs/research/pdf-family-rollup-yield-2026-09-20.md).
  The index side is rendered generously on purpose, so every "beyond the index"
  count is a floor; at most 60 pages of a document are read and each row records
  the real page count beside it.

  **Superseded for the GovInfo-served families** by
  [pdf_yield_mods_recheck](analysis/pdf_yield_mods_recheck.py), which asks the
  same question against the record a GovInfo body actually has. The rollup
  compared each print against GovInfo's `published` listing row; the index is
  the package MODS, which `GovInfoBodyAcquirer` fetches for every body it reads
  and which states bills, laws, U.S. Code sections, CFR parts, Statutes at Large
  pages, RINs, committees and the submitting member as named elements. `fetch`
  reads one MODS per sampled package or granule (keyed, `API_GOV` header only,
  24 requests bounded at 40, identity proved by `validate_package_mods` where
  `bodies.py`'s grammar reaches and by the MODS's own `accessId` where it does
  not). `analyze`, `uncapped` and `render` make no request: the first
  restates the rollup's own figures against the MODS, the second removes the
  60-page cap and re-reads all 18,119 pages of the retained PDFs -- the check
  the headline result turns on -- and also runs the **false-positive pass** the
  rollup never ran, testing each surviving key against the publisher's real
  ranges (it is what found `Public Law 188-11`, `S 08` read out of a
  name-and-date column, and a docket dated 2029). `render` rewrites the
  report's generated block from the committed sidecar, and a test byte-compares
  the two so a report cannot drift from its own measurement. Rules and
  committee resolution are imported from `pdf_family_rollup`, never restated.
  The report is
  [`docs/research/pdf-yield-mods-recheck-2026-09-20.md`](../docs/research/pdf-yield-mods-recheck-2026-09-20.md)
  and `tests/test_pdf_yield_mods_recheck_tool.py` pins the MODS shapes, the
  credential scrub, the identity proof and the committed sidecar.

- [record_communications_overlap](analysis/record_communications_overlap.py): score
  `sources/congress/record_communications.py`'s parse rule against Congress.gov's
  own decomposition of the same sentence, field by field. The research that
  proposed the backfill compared **two** rows; the 114th Congress onward is the
  overlap era, where a printed Record entry and a publisher-decomposed detail
  record both exist, so the rule can be scored on rows it was never fitted to.
  `fetch` acquires ten sampled House sitting days (two per Congress, 114th
  through 118th) through `GovInfoBodyAcquirer.acquire_granule` and then one
  detail record per printed number at the publisher's own upper-case locator
  `house-communication/{congress}/EC/{n}`; `score` and `render` make no request.
  **Caps declared before the first request and enforced by a counter across
  resumes: at most 40 GovInfo requests and 600 keyed Congress.gov requests for
  the whole campaign** (`MAX_GOVINFO_REQUESTS`, `MAX_CONGRESS_REQUESTS`). A 404
  on a detail record is recorded as the publisher's answer, a 200 with an empty
  body as requested-empty, a transport failure as refused and re-requested on
  the next resume; 401/403 ends the run. `API_GOV` is read with `read_api_key`
  and travels in a header only; every recorded URL and message is scrubbed
  before it is written or truncated. Entries are requested round-robin across
  issues so a cap truncates every issue's tail rather than deleting the last
  Congresses from the sample. The report is
  [`docs/research/record-communications-overlap-2026-09-20.md`](../docs/research/record-communications-overlap-2026-09-20.md)
  and `tests/test_record_communications_overlap_tool.py` pins the scoring, the
  request bookkeeping, the credential scrub and the committed sidecar.

Both stop on HTTP 401/403. The resolver retries request errors, empty, invalid,
and incomplete listings. It requests one page per issue and refuses `nextPage`,
count mismatches, or a full 1,000-row page. A full page is indeterminate even when
its declared count is 1,000: that may describe the page, not the issue. Empty
listings are also indeterminate. Unresolved listings cause exit status 1.

## Related operations

These operations ship with `spicy_docs` and accept caller-selected paths. Use
`uv run --frozen python -m MODULE --help` with:

- [`spicy_docs.sources.federal_register.replay`](../src/spicy_docs/sources/federal_register/replay.py):
  build a new release from retained responses and scope, offline.
- [`spicy_docs.cli.campaign`](../src/spicy_docs/cli/campaign.py): publish regulations.gov
  docket/document releases with attempt logs and receipts under one locked root.
  Start with `--dry-run`.
- [`spicy_docs.sources.congress.crs_summaries`](../src/spicy_docs/sources/congress/crs_summaries.py):
  fetch resumable summary JSONL from a Parquet list of report ids. Requires an
  explicit credential file and PyArrow (`public-table` extra).

## Prove a document shape

- [document_capture](analysis/document_capture.py): convert six real federal
  documents (a USLM law, a bill XML through DeltaTrack, a committee-report HTML
  body, a Federal Register notice XML, a reconstructed CFR section, a slip
  opinion's extracted lines) into the `DocumentCapture v1` shape, validate each
  against Rulespec's parent schema and its family profile, check the invariants
  with Rulespec's own validator, prove the text round trip with a second
  parser, render two leaves per document as rulespec `SourceFragment`s and
  measure where the bytes go. Reads committed fixtures and the retained inputs
  beside its output; makes no request. Supply `--output`; the design record is
  [`docs/research/document-capture-schema-2026-09-19.md`](../docs/research/document-capture-schema-2026-09-19.md).

## Reproduce a measurement through the product rules

- [hearing_bill_links_recompute](analysis/hearing_bill_links_recompute.py): run
  `interpretation/hearing_bill_links.py` and
  `sources/congress/house_committee_repository.py` over the retained responses
  of the [hearing-to-bill linkage receipt](../docs/research/hearing-bill-linkage-2026-09-20.md)
  and compare what they produce against that receipt's own offline recomputes:
  every hearing's `COVER` bill set, every event's resolved `BR` keys and parent
  committee codes, and the 46/36 totals. Supply `--receipt` and optionally
  `--output`; makes no request and reads no credential. Exit status 1 on any
  disagreement, which is what a product rule drifting from what was measured
  looks like. It cannot reproduce the bill-side confirmations: the receipt
  retains those as a scored summary, not as action lists.

[Repository checks and artifact maintenance](../scripts/README.md) live in
`scripts/`.

The offline [FEC layout generator](build_fec_layouts.py) rebuilds packaged field
definitions from pinned workbook fixtures. Its OpenPyXL dependency is used only
for generation; the [runtime API](../docs/sources/fec-filing-fields.md) uses core JSON.
