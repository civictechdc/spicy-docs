# Source fidelity repairs and shared-library adoption

The [70-table, 20-source audit](data-validation-sprint-2026-09-21.md) led to
four bounded repairs. This sprint checks each repair against retained publisher
inputs and actual Parquet or capture outputs. It does not establish that the
whole public collection has been rebuilt.

All new measurements live under
`~/Work/corpora/supply-2026-09-02/receipts/remediation-sprint-2026-09-21/`.
Earlier receipts remain unchanged. Implementations use isolated branches,
independent review before merging, and separate register commits at each landing.
No remote push, external package release, upload or deployment is part of this
sprint.

## Repairs and direct evidence

| Repair | What changed | Direct check | Remaining boundary |
| --- | --- | --- | --- |
| Federal Register identity (H12) | Preserve number plus publication date; use dated identity in four downstream materialization families; retain ambiguous number-only observations and candidates. | The complete retained daily responses contain 237 rows: the old merge loses one, the repaired merge preserves all 237. The 474-number RefSpec collision census retains all 957 dated identities. Repairing the pinned 803,996-row artifact adds only `00-111@2000-01-14`, loses no keys, and changes no unrelated source fields. | Historical backfill, bridge regeneration and coherent downstream publication. A seven-day incremental window cannot recover older discarded rows. |
| Court text variants (H13) | Preserve all eight native text strings, empty versus NULL, and availability derived from stored values. Version-2 priors carry all 25 columns; legacy artifacts require an explicit rebuild. | A bounded original 2 MiB bulk prefix yields 284 records and 2,272 exact field comparisons. Opinion `380204` now retains its 17,461-character HTML. An independent CSV read confirms the actual native value in the materialized output. | Full selected-scope rebuild. Seven variants were observed nonempty in this slice; `xml_scan` has synthetic preservation controls, not a positive native witness. |
| Report headings | Append literal `heading`; leave unresolved `agency_label` and `agency_key` NULL. Preserve parser spans, text, patterns, row keys and the existing column prefix. | Complete CRPT-119hrpt796 HTML retains eight blocks and seven printed headings. A rendered appropriations page retains a real office heading and its account text. All 110 existing non-agency cells across these eleven blocks are unchanged. | Broader segmentation and any separately qualified agency resolver. A heading pattern is not an asserted agency identity. |
| Shared capture validation (G5 adoption) | Install Rulespec 1.0.14; remove copied parent/profile schemas, copied validator and fallback loader. Use owner resources and checks directly. | All seven retained captures replay with identical artifacts, structure and text. The two owner counterexamples pass the old copy and fail the installed checker; repairing each input clears its finding. | Provenance gaps G3/G4 and population-wide extraction qualification remain open. The shared parent bytes did not change. |

The FR witness consists of two different publisher records: the Treasury
housing-credit rule dated January 14, 2000 and the Interior island-plat notice
dated January 18, both numbered `00-111`. The correction does not decide that
they represent one legal matter. Source record identity and RefSpec's
matter-identifier adjudication remain separate.

The FR whole-file replay initially exceeded its existing 4 GB memory limit
when ranking wide payloads. Ranking key/source/row positions first completed
the same replay within that limit. Conflicting observations of one dated key
refuse the write; a new observation of the same dated key replaces the prior
one. Output promotion occurs only after the complete merge succeeds.

## Adoption in the installed host

The locally built SpicyDocs 0.25.0 wheel contains the report-heading correction,
the previously committed cosponsor correction and Rulespec 1.0.14 adoption.
All 264 packaged source files equal the reviewed checkout. The installed
registry exposes 39 tables over 814 columns. The wheel SHA-256 is
`3bd52a8916e8c470111dd31bcdc6cb7fa7e41c5b70011b567b78a7c1b58a5745`.

SpicyRegs installs those wheels through its existing pinned reader group.
Its report checkpoint now includes the package version, CBO rule and report
section reader version. Successful reads replace the complete child-row set
for that report, including an empty result; failed or unread reports retain
their rows. This uses the existing parent-replacement merge facility.

The installed GovInfo acquirer replayed the retained summary, MODS and complete
HTML for CRPT-119hrpt796. With an unchanged publisher timestamp and no discovery
result, the old checkpoint triggers a fresh read. Eight blocks preserve all
80 existing non-agency fields, seven headings survive, and agency claims are
NULL. A second run performs no acquisition. The replay used three local
transport responses and zero network requests.

The installed wheel also rebuilt the earlier bounded 118th-Congress HR/S
candidate from the same native archives:

| Table | Rows | Columns |
| --- | ---: | ---: |
| `congress_bills` | 16,213 | 49 |
| `bill_actions` | 75,239 | 14 |
| `bill_committees` | 26,029 | 10 |
| `bill_publisher_summaries` | 10,806 | 7 |
| `cbo_cost_estimates` | 1,431 | 16 |

All 2,206,611 cells match the previous corrected candidate by stable keys.
Independent native XML checks pass 1,189,950 named field comparisons including the
CBO restatements, with zero mismatches, missing/extra keys, duplicate keys or
orphans. Imported module files match the installed wheels; no sibling source
path substitutes for the package. This verifies package adoption for the named
cohort. It does not qualify inferred stage, money or committee-action meaning,
produce missing bill bodies, or replace the broader public generation.

## Existing features used, and why

| Owner and existing resource | Effective use in this sprint | Boundary retained |
| --- | --- | --- |
| RefSpec dated collision census and matter adjudications | Independent cross-check of 957 source identities and the distinction between records and matters. | No copied normalization policy, collision whitelist or new identifier scheme. |
| RefSpec asserted agency projection | Confirmed that heading matching cannot supply its required roster identity evidence. | A separately qualified consumer may use the pinned projection; the heading splitter does not create agency claims. |
| SpicyDocs Federal Register identity functions and public-table key | Reused owner validation and `number@date` encoding in downstream consumers; source merge follows its composite key. | The encoding is a source key, not a Rulespec IRI or a matter assertion. |
| SpicyDocs CourtListener bulk reader and CSV decoder | Retained exact native values through the existing acquisition/decoder path. | HTML/XML variants remain source strings until explicitly converted. |
| SpicyDocs GovInfo acquirer, MODS validation, body extraction and report blocks | Replayed the real package through installed source APIs; preserved text and evidence spans. | No replacement body parser or new agency heuristic. |
| SpicyDocs BILLSTATUS reader and bill-family builder | Reproduced five coherent local outputs from pinned archives using the installed package. | The named cohort and unavailable inputs remain explicit. |
| Rulespec capture schemas and invariant validator | Installed and called the owner package, removing three copied files and the loader fallback. | Family grammars remain SpicyDocs-owned; capture does not assert legal meaning. |
| Rulespec artifact mechanics and SpicyDocs immutable releases | Existing release, admission, digest and replay facilities remain the suitable publication path. | A schema declaration, successful test or seal does not prove source completeness or publication. This sprint does not invent another release format. |

The ownership decisions remain RefSpec REF-024/REF-048 and the September 19
capture ruling in [SpicyDocs decisions](../decisions.md). Products exchange
installed packages and pinned artifacts. RefSpec and Rulespec source trees
remain unchanged by this sprint; their existing resources are sufficient for
these repairs. RefSpec's older SpicyDocs pin is not upgraded merely for version
parity: its own adapters and retained outputs need their own qualification.

## Evidence index and remaining work

The reviewed repairs are committed on local main branches. SpicyDocs package
commit `1c86f16` contains heading fix `a7519d6` and capture adoption `8303afa`
with replay `169438f`. SpicyRegs integrated merge `fe8b0e4` contains Court text
fix `d641411`, dated Federal Register fix `5587315` and host adoption `230cce5`.
The integrated source gate passed 7,255 tests (four skipped, 46 deselected);
the combined host gate passed 1,905 tests (three deselected), Ruff, type checks
and the 67-table dictionary check. Existing unrelated host formatting debt
remains outside this change. These checks complement the native comparisons;
they do not establish public replacement or whole-population completeness.

- `fr-identity/verified-replay/replay-results.json`,
  `unrelated-row-preservation.json` and `independent-review/` bind source keys,
  actual output rows and independent review. `native-consumers-results-verified.json`
  supersedes the original consumer receipt's substring-filtered witness field;
  it matches the literal `00-111` number exactly without changing any outputs.
- `court-text/capture.json`, `raw-output-witness.json`,
  `materialized-replay.json` and `independent-review.json` bind original bulk
  bytes, exact values and stored output.
- `report-headings/before/`, `after/`, `cell-differences.json` and
  `reuse-and-review.md` retain the raw headings, rendered positive witness,
  actual rows and reviewed ownership choice.
- `rulespec-adoption/verification.json`, `independent-capture-comparison.json`,
  `independent-review.md` and `final-gate.txt` retain preservation and negative
  controls. Historical September 20 measurements still replay their pinned
  Git bytes; current source-field and mutation checks remain active.
- `source-reader-adoption/docs-0.25.0/`, `report-replay/` and `bill-replay/`
  retain the installed package pins, raw host replay and independent native
  bill validation. `integrated-*.txt` retain the combined host gates;
  `integrated-catalog-review.json` pins the independently reviewed merged catalog.

The next data work remains concrete: repair older published rows from pinned
inputs, propagate mapped regulations.gov fields that the current reader already
retains (H14), correct lifecycle grouping/precision (H15), acquire the missing
bill and regulatory bodies, and qualify interpretation against thresholds
declared before scoring. A fuller heading detector or another acquisition
family does not substitute for these open output defects.
