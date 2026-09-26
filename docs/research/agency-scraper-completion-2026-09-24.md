# Agency scraper completion plan

The new FCC, SEC, FERC, CFTC and EDIS adapters have bounded live evidence, but
they are not yet a complete operator workflow. Keep two completion decisions
separate: acquiring every offered item in a selected scope, and publishing an
immutable release that another caller can inspect and replay.

This assessment follows the source review and parallel live qualification on
2026-09-24 through 2026-09-25 UTC. Exact requests, responses, hashes, failures,
commands and code pins are retained under
`~/Work/corpora/supply-2026-09-02/receipts/` in
`scraper-review-live-2026-09-24T225923Z` and
`scraper-completion-2026-09-24T235248Z`. Continued implementation and live checks
are retained in `scraper-delivery-2026-09-25T003133Z`; its source reports and
verification receipts supersede the corresponding earlier blockers. Earlier
failures remain observations of those attempts.

## Qualified behavior and remaining source work

| Source | Verified selected scope | Work still required |
| --- | --- | --- |
| [FCC](../sources/fcc-ecfs-attachments.md) | `FccEcfsReader.iter_filings` proves the partition for a crowded selection: it checks the exact count, pools shifted walks, splits by submission time below the offset ceiling and refuses rows outside the filters it sent. Docket 17-108, received 2017-04-01 through 2017-05-01, enumerated 19,676 filings matching the native count without an offset crossing the ceiling (`fcc-mirror-implementation-2026-09-25`). The backfill driver now enumerates each window through it, and `--capture-documents` verifies a completed window by replaying its pages offline. Earlier live capture checks (interruption, resume, zero-request rerun, single-file repair) ran on the previous day-window walk (`scraper-delivery-2026-09-25T003133Z`). | Requalify `--capture-documents` live on the current driver. A crowded single millisecond still refuses. Measure larger files and additional formats. Add retained-capture release integration. |
| [SEC](../sources/sec-comments.md) | S7-11-23 supplied all 106 files. The new `rule_urls` path follows publisher-stated links: S7-08-23's descriptive rule slug supplied both listing pages and all 51 files (5,158,954 bytes). Resume captured only outstanding files; final resume made zero file requests. Full/trimmed rule-page parsing agrees. A live uppercase docket-path defect was fixed while preserving exact URLs. | Qualify a non-S7 rule with offered comments, then deliver durable checkpoints (a resume skips files by URL without re-reading retained bytes) and release integration. Valid pages with no offered comment link remain unresolved discovery observations; derived 404s never establish absence. The offline join reads act-named releases (`Investment Company Act Release No. N` as `IC-N`), `File Nos.` lists and citations to pages below 1000. Receipt `sec-file-number-grammar-2026-09-25` measures the list grammar over the whole Federal Register release: it loses no number the one-token grammar read, keeps every dash-less single number's reading, and re-spells only truncated readings into the full number (`File No. 812- 9182` now reads `812-9182`, not `812`). A citation several SEC records share still refuses when those records state no release or file number; `tools/analysis/sec_comments_join_coverage.py` counts those refusals. |
| [FERC](../sources/ferc.md) | RM24-5 discovery matched the browser. The new original-file POST route supplied all five discovered comment PDFs, totaling 1,815,666 bytes, with every declared size matched. Browser/direct original digests agree. The existing generated-PDF route also succeeded again. | Test other docket shapes, larger searches and a multi-page docket sheet, then add durable capture/release integration that consumes the captures, not the readers' rows. The new-docket window's serial-numbered `ID-` dockets are now admitted by the docket grammar. Earlier generated-PDF timeouts remain unexplained observations; they were not reproduced and no request-shape defect was established. |
| [CFTC](../sources/cftc-comments.md) | Production `recover_walls=True` supplied rule 7639's five comments, details and PDFs through the reader. The reader's own multi-page walk then qualified live on rule 1647's complete four-page/34-comment listing (distinct comments against a constant stated total; receipt `cftc-reader-multipage-2026-09-25`), matching the identities the campaign script walked earlier. Every ladder attempt shares request accounting and pacing, and a comment quoting a block page's words is read as the portal's page, not a wall. The post-cutover Regulations.gov document query and bounded mirror inventories also completed. | Add durable portal checkpoints/release integration. The source selection is documented: comment periods opened on or after 2026-04-28 use Regulations.gov. Its origin API currently supports documents/details/files; mirror comment presence does not establish current origin comment completeness. |
| [EDIS](../sources/usitc-edis.md) | Investigation 337-1438/Other1 supplied two documents and 87 attachment metadata rows, including explicit empty download offers. On September 25, `EDIS_TOKEN` supplied both offered PDFs of public document 894762 through the explicit Zyte route: 219,572 bytes, with declared sizes and page counts matched. Direct access was walled; the credential itself passed. Receipt: `edis-token-qualification-2026-09-25`. | Complete a selected investigation's offered public files and recovery checks, while retaining restricted and unavailable offers as metadata outcomes. The accepted credential closes the earlier token blocker. A listing walk cannot see a deletion during the walk, so completion needs a reconciling re-walk. The document listing matches partial investigation numbers (receipt `edis-partial-number-probe-2026-09-25`); the reader keeps rows for longer numbers as evidence outside the docket. |

The DataWeb control returned 200 with and without a token, so it does not
establish token validity. The EDIS 403 establishes refusal by EDIS for that
request. Do not repeat it through other transports as a credential experiment.

## Implement the durable workflow using existing components

Raw readers deliberately leave persistence and recovery with their caller;
see [source workflows](../source-workflows.md). Successful bounded scripts do
not supply that missing operator experience. The new adapters also have no
registration in [`cli/sources.py`](../../src/spicy_docs/cli/sources.py) for the
common `publish` command.
FCC has the `spicy-docs-list` capture CLI and now connects the date-window
backfill driver to durable acquisition of declared files. The other readers
still need an equivalent operator workflow; caller-owned resume keys alone do
not verify stored files.

Use the existing [release profile interfaces](../../src/spicy_docs/releases/profile.py),
publisher, blob store and verifier. Keep publisher-specific URL, identity and
traversal checks in each source package. Retained FEC profiles provide a reuse
example; other sources must not depend on FEC internals. A second acquisition
framework or a separate publication format is unnecessary.

The operator path needs these explicit inputs and outputs:

| Boundary | Required behavior |
| --- | --- |
| Selected scope | Record source, dates/dockets/investigation phase, filters, byte/request/page budgets, code version and credential names, without credential values. |
| Discovery | Retain exact pages, source counts and continuation evidence. Record each parent and every offered file, including an explicitly empty or restricted offer. |
| Capture | Retain exact bytes and digest, source identity, request method and scrubbed locator, observed time, parent-page digest and chosen transport. Keep failed, requested-empty, unavailable and never-requested states distinct. |
| Recovery | Persist a success only after its blob and receipt are durable. Verify retained successes before skipping them; retry every unsuccessful item. Abort a credential refusal and preserve completed work. A restarted run must retain the union of earlier and new successes. |
| Completion | Reconcile discovered identities against terminal file outcomes for the selected scope. Explain omitted/restricted files and unresolved requests; a green parser test or a source count alone cannot establish completion. |
| Release | Add thin source profiles over retained captures, explicit source registration and CLI scope validation. `verify` must reconstruct records and deterministic parser rejections from retained blobs without network access. Unresolved acquisition or transport failures produce a failed-run receipt and no admitted release. `inspect` describes admitted releases, not unfinished captures. |

## Delivery order and acceptance checks

1. **Broaden source qualification.**
   EDIS now has an accepted token and a complete public document's attachment
   set. Its separate [bulk ZIP workflow](../sources/usitc-edis.md#bulk-zip-backfills)
   supplied both a basket job and a separate direct-HTTP job for that document,
   with both ZIP PDFs matching the EDWS captures byte for byte. The direct
   create/status/download sequence uses a signed-in web session and CSRF token;
   `EDIS_TOKEN` alone redirected to login on the tested bulk status/ZIP routes.
   Receipt `edis-direct-bulk-2026-09-25` retains the direct replay. Add thin
   package integration and qualify larger batches, session recovery and a
   complete selected investigation next. Reuse the shared transport and ZIP
   reader, with scheduling and recovery owned by SpicyRegs. `BoundedAcquirer`
   compares whole header values when it looks for an echoed credential, only
   sends `GET` and follows redirects, so a session cookie's value echoed alone
   would pass it: use `BoundedHttpCapture` for the create `POST` and status, and
   add a per-component echo check before any client carries the session values.
   FERC's original-file route, SEC's
   source-stated slug discovery and CFTC's supported recovery now pass bounded
   live checks. Finish the source-specific coverage items in the table above.
2. **Extend the recoverable vertical slice.** FCC now passes interruption,
   resume and deleted/corrupt-file recovery with the complete selected identity
   set. Its earlier exact-page request scope, journal credential escaping and
   repeated-filing outcome findings were fixed and independently retested.
   Deliver equivalent durable workflows for the other sources, preserving their
   existing acquisition APIs and source-specific identities.
3. **Add retained-capture release profiles and operator entry points.** Publish
   locally from the same captures, inspect the result and verify it offline.
   Alter a source identity, page continuation or blob digest in an isolated
   test: verification must fail with a specific reason. Exercise failed-run
   receipts for incomplete acquisition, and deterministic rejected records,
   unavailable and empty outcomes alongside complete runs. Offline profile
   work over retained EDIS metadata needs no credential.
4. **Qualify broader scope and hand off.** Reconcile publisher counts and
   stable IDs across a second representative scope, document source-specific
   size/rate limits, and supply a reproducible command with its artifact pin.
   Downstream interpretation, catalog adoption and public deployment are
   separate delivery decisions.

These checks define completion for an explicitly selected scope. They do not
claim historical completeness, continuous availability, or public publication
from local test results.

## Open items after the 2026-09-25 validation

Seven independent reviews (one per source package, one for the shared
transport and docs, one for the SpicyRegs consumer) validated the tree above,
their agreed findings were fixed, three bounded live probes requalified the
changed paths, and the result is spicy-docs 0.34.0. Reports with `file:line`
evidence are outside the repository (session scratchpad); receipts are under
`~/Work/corpora/supply-2026-09-02/receipts/` (`wall-marker-prevalence`,
`sec-file-number-grammar`, `edis-partial-number-probe`,
`fcc-capture-requalification`, `cftc-reader-multipage`, all `2026-09-25`).
What remains, by owner:

- **All five sources.** Delivery items 2–4 above are still open: durable
  checkpoints for SEC, FERC, CFTC and EDIS (their resume is a full re-walk;
  only FCC verifies retained bytes before skipping), retained-capture release
  profiles, and `publish` registration in `cli/sources.py`.
- **EDIS.** The publisher matches partial investigation numbers; whether by
  prefix or substring, and whether `/data/investigation/{n}` matches
  partially too, needs one more bounded probe. Deletions during a listing
  walk are undetectable (insertions surface as repeats); a confirming
  identity-set re-walk would cost one extra pass. The bulk ZIP job
  (create/status/download over a signed-in session) has no package client.
- **FERC.** The search and docket-sheet walks stay in a local `_walk`: folding
  them into `reading/paged_json.pages()` needs a per-call family and would
  drop the offending-page capture every other consumer lacks. Docket-sheet
  paging beyond one page is unqualified offline; the new-docket and sheet
  readers have no production caller; the comment and accession readers still
  yield bare rows without an identity or page digest;
  `interpretation/identifier_shapes.py` keeps a separate FERC prefix list that
  lacks the `ID-` spelling.
- **FCC.** The capture journal fsyncs once per window, so a power loss can
  lose one window's rows (files are durable and refetched). A traversal has
  no explicit total request cap; its bound is structural (depth times leaves).
  `build_fcc_proceedings` in SpicyRegs still materializes the whole proceedings
  walk by design; `MAX_RESULT_WINDOW` stays restated there because a
  module-level import would break its optional-dependency contract.
- **SEC.** The join keys rulemakings by file number, so comments reached
  through a slug-only rule page cannot join. Shared Federal Register start
  pages whose record states no release or file number remain refused, and a
  handful of sub-1000-page citations fall on such pages (measured in the
  `sec-file-number-grammar` receipt).
- **CFTC.** No route memory in the wall ladder: a persistent wall costs every
  rung per item (rejected, since one success does not establish a route).
  Listing-page provenance is not carried per record.
- **Shared.** `sources/zyte.py` and `sources/firecrawl.py` still chain the
  provider `HTTPError` (`from error`), which keeps the provider response
  reachable from the exception; `BoundedAcquirer` compares whole header
  values, which matters once a client carries a session cookie; the older
  media-type and PDF-magic copies outside the five packages were left where
  merging was not net smaller. `tests/test_cbo.py` skips one case whose
  fixture path points outside the workspace.
