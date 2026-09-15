# Additional official FEC collections — September 14, 2026

The next acquisition pass completed the selections below through existing
SpicyDocs readers. Originals remain separate from metadata and derived tables.
These are local source captures and qualification results, not additional
admitted releases, downstream catalogs, financial views or search indexes.

| Selection | Acquired and checked | Evidence with commands, pins and limits |
| --- | --- | --- |
| Advisory opinions numbered 2025 | 8 cases, 40 originals; JSON search/detail and exact legal XML listing reconcile, including document associations | [Legal receipt](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/legal/README.md>) |
| Administrative fines with final determination in 2025 | 16 cases, 27 originals; declared date filter, details, case-directory XML membership and attachments reconcile | [Legal verification](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/legal/qualification.json>) |
| 2024 committee-to-candidate and independent-expenditure archive, `pas224.zip` | Complete sole ZIP member, CRC and digest; 703,597 rows × 22 fields independently compared as strings | [Financial qualification](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/financial/qualification.json>) |
| 2024 independent-expenditure notice CSV | 73,449 rows × 23 fields independently compared as strings, with native headers retained | [Financial qualification](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/financial/qualification.json>) |
| Historical electronic filings | 10 complete originals; 32,135 rows, 1,247,944 positional fields and 7 separate narratives checked against an independent whole-file CSV parse | [Historical qualification](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/historical/qualification.json>) |
| XML-linked FOIA annual reports in the captured FEC index | 17 originals spanning 2009–2025; 16 NIEM reports and one Word XML package, with all element names, attributes, text, tails and order reconstructed independently | [Agency verification](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/agency/verification.json>) |

The legal scopes describe AO numbers and AF final-determination dates; they do
not mean every legal document issued during 2025. Both selections replay and
resume without HTTP. PDFs are retained originals without a text/OCR claim.
The legal [raw inventory review](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/legal/raw-inventory-review.json>) compares publisher cases, objects and associations.

The two financial exports overlap in purpose and remain separate. The archive
contains other election-year labels and older transaction dates. Notice amendment
codes include numbered amendments. Blank dates, leading whitespace, cents,
identifiers and memo fields remain literal source values. No current-amendment
view, sum across the exports or schedule-wide completeness is inferred.
[Direct raw samples](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/financial/raw-sample-review.json>) retain positions and comparisons.

## Small library changes

- Recognize only the observed literal `5.00` CSV version for TEXT body separation.
  Genuine complete originals now qualify `5.00`, `5.1` and `5.2`. Source-derived
  regression fragments preserve exact bytes and identify themselves as fragments;
  removing `5.00` makes the new test fail. Literal `5.0` remains unobserved in the
  selected originals, although workbook evidence and known-answer tests cover
  its declared layout. Other padded labels remain unsupported. Completing
  FEC-13034 also preserves a fourth Schedule I account absent from the previous
  tail sample. [Historical evidence](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/historical/README.md>)
- Approve exact `beta.fec.gov` because the current FEC index publishes older
  report links there. Each redirect still passes the existing host checks;
  requested and resolved URLs remain separate, and API credentials are absent.
  Positive, unchanged-host and unapproved-redirect tests cover the change.
  [Independent review](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/legal/agency-review.md>)

The follow-up also fixes proxy-reported HTTP 401/403 handling in the existing
FEC client: these remain aborting refusals, matching direct requests. A generic
transfer failure previously let the caller continue to the next selected file.
Both metadata and original-file paths have regression checks; removing the fix
makes them fail. The campaign's external-file adapter follows the same rule.
[Focused checks and mutation](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/checks.json>)

FOIA XML classification follows the actual root: NIEM exchange 1.02 for 2010,
1.03 for 2011–2025, and Word Flat OPC for 2009. The latter retains Word parts,
text and relationships; it is not a normalized report-data table. XML comments,
prefix spelling and processing instructions remain in originals, outside the
derived element tables. Replay is not XSD validation, statistical interpretation
or visual Word fidelity. [Changed-text and dropped-element controls](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/agency/controls.json>) pass against retained originals. The original capture and later
offline classification/reuse receipts are both retained under `agency/`.

## Research inventory follow-up

The follow-up uses the retained research inventory to select three additional
collections. One campaign adapter calls the existing
`examples.fec_legal_year.acquire_originals` resume loop; all families share its
checkpoints and disposition format, `BoundedAcquirer`, `FecClient` and blob
storage. Source selectors and qualification stay separate. No new production
module or package dependency was added for this pass. The external FOIA.gov and
Oversight assets use explicit host checks; the FEC host list is unchanged.

| Declared selection | Retained originals and residual scope | Evidence |
| --- | --- | --- |
| Complete observed OpenFEC `form_type=F13` query | 31 rows; all 23 supplied raw filings and 28 PDFs acquired. Three PDFs exceed the 32 MiB per-object bound; eight records supply no raw URL. Amendments and every literal field remain separate. This is the observed query, not every historical inaugural filing. | [Inaugural acquisition](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/inaugural/acquisition-check.json>) and [metadata replay](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/inaugural/metadata-verification.json>) |
| Archived-enforcement research difference set | All 33 difference rows have dispositions; 23 primary originals and one separately selected comparison original are acquired. Larger objects and invalid originals remain separate. The selection includes named recovered and comparison documents, so these counts describe different populations. | [Enforcement selection](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/enforcement/selection-check.json>) and [acquisition](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/enforcement/acquisition-check.json>) |
| FOIA.gov and retained Oversight subset | 13 originals: the 2009/2025 FOIA.gov ZIPs, two FEC XML comparison witnesses, files for the six observed 2026 issue-year reports and a 2022 recommendation snapshot. Report-page metadata stays separate. Other years and current recommendation status remain outside this selection. | [Agency acquisition](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/agency/acquisition-check.json>) and [selection](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/agency/selection.json>) |

The F13 raw check independently compares every positional field and narrative
range. Acquired PDFs load every page node and match publisher-declared page
counts; this does not establish OCR accuracy or financial meaning.
[Whole-file qualification](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/inaugural/qualification.json>) records the exact population and limits.
The source has negative `file_number` values that the current filing release
profile refuses. Raw metadata preserves them. Release admission needs a separate
fix and qualification; rewriting the source identifiers would lose information.
[Profile boundary](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/inaugural/release-profile-boundary.json>)

The native FOIA.gov ZIP members preserve report-data XML, including repeated
statute associations. The 2009 FEC Word package remains a separate rendition;
the paired 2025 XML reports differ in their creation date. Oversight qualification
replays the retained index to establish its selected issue-year subset, checks
source fields and file links, and separates native PDF extraction observations
from report metadata. Identical document bytes share extraction output while
retaining each source URL. The 2022 memo, report issue and export dates describe
different events. These checks establish neither current recommendation status
nor OCR fidelity. [Agency qualification](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/agency/qualification.json>)

The enforcement pass keeps invalid HTML responses and the truncated current
2035 PDF as failed-original evidence, alongside the complete historical
alternative. MUR2152 is explicitly associated within 2189; the 1829/2229 leads
remain related-only. The filename/body conflict for 4307 remains visible.
A further comparison finds byte-identical 1999/1847 originals whose retained API
case metadata disagree; byte equality does not resolve those competing source
identities. Other equal-byte bundles also retain distinct case associations.
Fifteen difference rows still need larger originals, and ten acquired difference
rows have whole-file checks without manual case-identity adjudication.
[Enforcement findings and limits](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/enforcement/README.md>)

Research reuse preserves the original response time, URL, transport, digest and
receipt. It is not a new live observation. The shared controls reject changed
bytes, associations and observation dates, exercise failed-transfer retry and
successful reuse, and verify the explicit public-denial proxy path.
[Controls](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/campaign-controls.json>) remain functional evidence, not a throughput measurement.

## Remaining work

The [financial preflight](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/financial/preflight.json>) records exact object sizes, native dictionaries and publisher
restore instructions. Schedule A's listed download exceeds the observed local
free disk before restoration. Other dumps still lack measured scratch, restored
table and index requirements. No database dump was restored. Targeted source
prefixes exhausted; the broader parent listing hit its declared page bound and
remains explicitly partial.

Continue FEC06–FEC10 in the [task list](../simplification-todo.md): other historical
layouts and populations, further legal/agency years and families, remaining
financial files, source-specific refresh and additional immutable releases.
The original FOIA history covers XML links in one pinned collection page; the
follow-up adds the two specified FOIA.gov bulk renditions. PDF-only years, other
report types and public FOIA releases remain outside those selections.
No recurring job was scheduled. The existing load exception applies to these
functional checks; timings do not support a performance comparison.

Before the follow-up proxy-refusal fix, `./scripts/check` passed lint, formatting
and the offline suite; opt-in network checks remained deselected. The isolated working tree and HEAD were
unchanged across the run. [Check receipt and input pins](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/checks.json>)
record the uncommitted tree explicitly. The [independent historical review](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/financial/historical-review.md>)
also approved the exact-version fix, source fragments and reconstructed fields.

After that fix, focused FEC tests, repository lint/format, the deliberate
refusal-type mutation and shared campaign controls passed. The full suite and
installed wheel were not rerun at that acquisition checkpoint, when the changes
were uncommitted. [Follow-up check receipt](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/checks.json>)

Code integration with SpicyDocs 0.8.1 and its subsequent combined checks are
recorded in the [local integration receipt](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-local-integration-2026-09-14/integration.json>).
The code and reusable findings are distinct from data-release publication,
installed-wheel qualification and downstream adoption.
