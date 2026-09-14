# Capture a Unified Agenda edition

Give SpicyDocs an edition file stem such as `202510`. It returns the exact
reginfo.gov XML export for that edition and proves, from every record, that
the file states the edition you asked for. No key is required.

| Selection | What it supplies |
| --- | --- |
| `YYYYMM` with MM `04` (Spring) or `10` (Fall), from 1995 | One `REGINFO_RIN_DATA` file: a `RUN_DATE`, the publisher's XSD location, and one `RIN_INFO` per regulatory action. |
| `2012` | The publisher's one off-pattern file name; its records state edition `201210`. |

Every record must carry exactly one `RIN` and a `PUBLICATION_ID` equal to the
requested edition; a repeated RIN, a record from another edition, a second
root, or a DOCTYPE refuse the whole file. Abstracts carry HTML inside CDATA,
including a literal `<!DOCTYPE html>`, which is text and is accepted.

```python
from spicy_docs.sources.unified_agenda import UnifiedAgendaAcquirer, UnifiedAgendaBudget, UnifiedAgendaEdition

budget = UnifiedAgendaBudget(
    max_requests=2, max_bytes=64 * 1024**2, timeout_seconds=300, min_request_interval_seconds=1
)
with UnifiedAgendaAcquirer(budget=budget) as source:
    result = source.acquire_edition(UnifiedAgendaEdition("202510"))

print(result.metadata.record_count, result.metadata.run_date, result.capture.sha256)
edition_xml = result.capture.body  # retain in caller-owned storage
```

## Read the result correctly

- `metadata.rins` lists every record's RIN in file order; record bodies stay
  in the retained bytes. Fall 2025 stated 3,954 records and a run date of
  2026-07-03.
- Three publisher irregularities are recorded, not repaired: the `2012` file
  name, the unpublished Spring 2012 edition, and one control byte in each 2004
  edition that XML 1.0 forbids. The 2004 files are refused as malformed; the
  exact bytes remain the caller's to repair downstream, which RefSpec does.
- The capture of edition 202510 on 2026-09-14 matched the digest and byte
  length RefSpec had pinned independently.

## Evidence

The reduced fixture and full-file hash are in
[`tests/fixtures/unified_agenda/README.md`](../../tests/fixtures/unified_agenda/README.md).
The complete edition is retained in
`corpora/supply-2026-09-02/receipts/spicyregs-merge-probes-2026-09-14/`. The
pinned XSD is `sample-data/source-domains/reginfo-rin-data-ver10262011.xsd`.
