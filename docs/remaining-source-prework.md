# Reuse for the remaining source tasks

**Historical reuse inventory, captured before the source fidelity fixes.**
The [to-do list](simplification-todo.md) records current implementation and checks.
This inventory identified the existing media-type helper and DocSpec's catalog,
fetch, process and retained-input reuse flow.

This September 12, 2026 review inspected local code and prior evidence. It ran
no tests or live acquisitions and made no implementation changes. Task completion
remains in the [to-do list](simplification-todo.md).

## Use this work first

| Task | Pre-work to reuse | Remaining work at review time |
| --- | --- | --- |
| **P01: attachment positions** | [SpicyDocs attachment tests](../tests/test_spicy_regs_public_tables_source_native.py) cover valid renditions, malformed JSON, publication and replay. [DocSpec's comment example](../../DocSpec/examples/spicyregs_comments.py) already retains source locations and exact evidence. | Carry original format positions through filtering. Add invalid entries before and between valid entries; verify rendition IDs and source fields through publication/replay. |
| **F05: empty versus missing CSV values** | [The streaming reader and tests](../tests/test_courtlistener_bulk.py) already cover bounds, filtering, quotes, newlines and resumed transfers. | Add quote-aware empty/null preservation. SpicyRegs still uses its own lossy reader; adoption and its table normalization need separate checks. No completed fidelity fix was found. |
| **F02: format labels** | Local FEC/main already has [the helper](../src/spicy_docs/sources/media_types.py) and [URL-shape tests](../tests/test_source_media_types.py). Aliases came from `893f066`; URL-path inference from `71a7dda`. | Reuse those changes, then qualify affected Regulations.gov/public-comment policies, publication and replay. Add explicit JSON source-release coverage. |
| **F03: Federal Register XML links** | [The XML body acquirer](../src/spicy_docs/sources/federal_register/body_acquisition.py) and [its tests](../tests/test_federal_register_xml_acquisition.py) already provide validated capture and bounded fallback. | Add publisher-stated `full_text_xml_url` to source field selection, schema, policy and rendition rows; qualify admission/replay together. A constructed URL does not establish a publisher-stated field. |
| **F04: CRS version** | [The detail fetcher](../src/spicy_docs/sources/congress/crs_summaries.py) already receives `version`; only its saved success row drops it. [SpicyRegs' table mapping](../../spicy-regs/src/spicy_regs/transforms/build_crs_reports.py) and [tests](../../spicy-regs/tests/test_crs_reports.py) already handle list-response versions. | Preserve the detail response's value on new captures, including null/absence cases. Keep explicit refresh guidance; list metadata cannot backfill a previous detail capture. |
| **CFR dataset example** | [DocSpec's bill example](../../DocSpec/examples/govinfo_bills.py), [injected fetcher](../../DocSpec/examples/govinfo_bill_fetcher.py) and [wheel test](../../DocSpec/tests/test_govinfo_bill_installed_wheel.py) already exercise catalog creation, processing and reuse after closing the source client. | Adopt the qualified SpicyDocs wheel, map MODS records into supplied-record catalogs, select supported annual XML, adapt the fetcher and qualify an annual-compatible processor. |

## Preserve the ownership and format boundaries

- **Attachment provenance stays source-owned.** DocSpec's
  [comment test](../../DocSpec/tests/test_spicyregs_comments_example.py) preserves
  the provider's declared locations. Its valid-only fixture needs a mixed-validity
  companion after the provider correction; it should not repair source positions.
- **A raw-reader fix does not migrate its consumers.** SpicyRegs'
  [CourtListener reader](../../spicy-regs/src/spicy_regs/sources/courtlistener_bulk.py)
  has the same empty-to-null conversion. Opinion bodies, clusters and court-scope
  transforms import it locally; some also normalize empty text. DocSpec's
  CourtListener tool uses only the listing parser.
- **Keep CRS capture identity.** The existing resume test deliberately skips a
  previous successful row without a version. A fresh response can supply missing
  evidence; a separate listing version or date cannot reconstruct it. SpicyRegs'
  string conversion serves its table schema and need not be copied into JSON.
- **Keep annual CFR separate from eCFR snapshots.** RefSpec's
  [XML reader](../../RefSpec/src/refspec/registry/xml_text.py) currently accepts
  eCFR `ECFR`/typed `DIV` roots, not annual CFR or GovInfo bulk wrappers. Do not
  substitute another edition or strip wrappers to make processing pass. DocSpec's
  generic XML extractor is available, but annual-CFR behavior needs qualification.

## Check the actual checkout before adopting

| Snapshot | Why it matters |
| --- | --- |
| SpicyDocs task branch `50c701c`; MODS implementation `0a26fec` | Contains the five open source tasks and the new MODS API. |
| SpicyDocs FEC/main worktrees `62f786d` | Contain the reusable F02 helper. Their package label remains `0.2.0`; do not use that label alone to identify capabilities. |
| DocSpec `ddc875f`, `docs/dataset-experiment-plan` | Contains current bill/comment examples. Bill adoption was integrated through `03df308`; the original `4df1b44` is on a separate worktree branch. Unrelated staged work was present. |
| SpicyRegs `b990062` | Adopts the bill provider, while CourtListener, CRS and CFR acquisition remain independent. |
| RefSpec `84bc634` | Supplies the inspected eCFR reader and its format/address limits. |

DocSpec and SpicyRegs both retain the SpicyDocs `0.3.0` wheel from `8e485fe`,
SHA-256 `bef15f967b0840ccc119c812edca92b38c63adb8943074be17655b86c96f83f1`.
The source `0.5.0` wheel rehashes to
`4b658c4a1cd8d5a1e99697440b6e6d152ae1c665233d4e8b4fe4e8cee156815a`;
its CFR/MODS modules match the current source. Receiving adoption remains open.

## Research scope and evidence

A subagent inventoried Work, Codex checkouts/worktrees and saved local project
locations: **191 Git markers, 185 resolving HEAD, 139 common Git directories**.
Those include nested third-party repositories. Broad source/document searches
covered every discovered location, followed by targeted implementation reads.
Non-obvious matches in AdvocateCentral, Formspec, CoreATO/RapidATO and PKAF were
plans or regulatory fixtures, not another completed source fix.

This was not a manual read of every file or all Git history. Dependency/build
trees and raw corpora were excluded from broad search; relevant bounded fixtures,
wheels and receipts were checked directly. No permission errors occurred. Broken
or empty Git markers, stale linked paths and search exclusions are recorded in
the full inventory; remote state was not refreshed.

The [full report](../../corpora/supply-2026-09-02/receipts/local-source-prework-2026-09-12/local-source-prework-review-2026-09-12.md)
contains exact file/line evidence. The adjacent
[inventory](../../corpora/supply-2026-09-02/receipts/local-source-prework-2026-09-12/local-source-prework-inventory-2026-09-12.json)
records repositories, refs and search coverage. These local evidence and sibling
links require the corresponding checkouts; the commit pins identify the snapshot.
