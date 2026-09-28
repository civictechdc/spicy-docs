# Statements of Administration Policy

Use the community `unitedstates/statements-of-administration-policy` archive to
connect a bill with administration statements and their original documents.
The source provides explicit bill associations, dates, titles, archived PDF
paths, and earlier UCSB American Presidency Project page links. SpicyDocs
preserves those statements; downstream readers can derive support, opposition,
or veto threats from passages in the documents.

The owner is
[`administration_policy.py`](../../src/spicy_docs/sources/administration_policy.py).
Install `spicy-docs[yaml,acquisition]`. YAML decoding uses the shared bounded
reader; locators and models remain importable without optional dependencies.

## Read selected metadata and a document

Select a full Git commit and the administration's archive stem. A moving branch
does not identify an input edition. This example uses the inspected snapshot:

```python
from spicy_docs.sources.administration_policy import AdministrationPolicyAcquirer

with AdministrationPolicyAcquirer() as archive:
    result = archive.acquire_metadata(
        commit="2bdff048a85b1febd3c7fa85ab2b86426d2ef4fc",
        administration="47-Trump",
    )
    statement = result.file.records[0]
    print(statement.bill_ids, statement.document_title)
    pdf = archive.acquire_pdf(result.file, record_index=0)

# Retain result.capture.body and pdf.body independently, alongside their
# sha256, requested_url, resolved_url and observed_at properties.
```

`parse_policy_metadata(bytes, commit=..., administration=...)` replays already
retained metadata offline. A caller-supplied commit identifies the intended
edition; the parser independently hashes the bytes but makes no HTTP claim.
`acquire_metadata` additionally retains and validates the pinned HTTP capture.

Each `PolicyStatement` supplies a zero-based `source_record_index`, a
commit-qualified `source_id`, the explicit Congress/bill associations, title,
literal issue date, and archived PDF URL when stated. `raw_json` retains all
source fields, including `rescinded`, `date_fetched`, source URLs, and unknown
fields. An unusual date remains literal with a separate `date_issued_status`.

## Preserve the archive's useful distinctions

Statements with an empty `bills` list remain available for search and later
association. Repeated statements about the same bill remain separate records.
A statement can name several bills; `bill_ids` preserves each explicit link.
`rescinded` is the community archive's assertion and does not delete the record.
The archive's capture date and our HTTP observation time describe separate acts.

For archived PDFs, acquisition follows the literal `file` field within the
selected administration and commit. It does not reconstruct a filename from a
bill number or date. Earlier external-page links remain in `raw_json`; they are
acquired separately using an appropriate page reader. Metadata provenance and
document provenance stay distinct.

The reader requires string mapping keys at every level and refuses duplicate or
merged YAML keys, aliases, explicitly tagged dates and other non-JSON values,
unsupported shapes and out-of-bound input as a whole. The default metadata
bound is 4 MiB; PDF captures are bounded at 16 MiB. Both can be narrowed, never
raised, through `PolicyBudget`. Request limits apply to each selected operation,
including retries. The shared capture client retains HTTP failure evidence.
Keyless 401/403 refusals raise `AdministrationPolicyRefused`, preserving the
response bytes and operation context. PDF checks establish the magic header and
terminal trailer, not correct bill attribution or passage interpretation.

## Validation evidence

The September 28, 2026 probe read every administration metadata file at commit
`2bdff048a85b1febd3c7fa85ab2b86426d2ef4fc` through the new acquirer. Its retained
receipt reports 5,656 statements and 5,682 bill-link occurrences, including four
statements with no bill, twenty multi-bill statements, and one rescinded record.
Every stated archived-PDF path matched the pinned, untruncated Git tree.
Seven selected PDFs passed acquisition and format checks, including multi-bill
and rescinded examples. This establishes the selected metadata edition and
sample document routes, not the completeness of the historical archive.

The largest observed metadata file was 660,549 bytes and the largest sampled
PDF was 223,273 bytes; the explicit byte budgets provide bounded headroom.
Full inputs and receipt are outside the repository at
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/sap/live/`.
See the workspace's
[`validation/administration-policy/`](../../../docs/unitedstates-review-2026-09-28/validation/administration-policy/)
for the reproducible probe and summary. Reduced source records and selection
provenance live in
[`tests/fixtures/administration_policy/`](../../tests/fixtures/administration_policy/).

```sh
uv run --frozen pytest -q tests/test_administration_policy.py tests/test_yaml_input.py
```

These inputs can feed a DocSpec dataset or SpicyRegs statement/bill-link tables.
This change supplies acquisition and offline replay; it does not publish an
application table or assign political-position labels.
