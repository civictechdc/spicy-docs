# Publish rows from retained FEC originals

`FEC_POSITIONAL_ROWS_PROFILE` publishes the complete positional records of one
retained original or explicitly selected ZIP member. It uses the existing source
publisher, immutable format and verified blob store. Originals remain separate;
the release stores row metadata and source references.

This core-only interface makes no network requests. Use the existing acquisition
API and [bulk file inventories](fec-bulk.md) to retain originals and select a
member first. Releasing a selected member does not establish archive-wide row
coverage, a complete cycle or a complete financial population.

## Select the input syntax

```python
from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher
from spicy_docs.sources.fec.row_profile import (
    FEC_POSITIONAL_ROWS_PROFILE,
    iter_retained_positional_rows,
    positional_row_scope,
)

# capture is the retained original's acquisition description.
scope = positional_row_scope(
    capture,
    member={"ordinal": 0, "name": "ccl.txt"},
    format="delimited",
    encoding="utf-8",
    delimiter="|",
    quoting="literal",
    max_records_per_page=1000,
)
published = SourceNativeReleasePublisher(FEC_POSITIONAL_ROWS_PROFILE, blob_store=output_blobs).publish(
    iter_retained_positional_rows(scope, blob_source=originals),
    build=SourceNativeReleaseBuild(query_scope=scope, producer=producer, started_at=started_at),
    destination=destination,
)
```

The capture requires `requestUrl`, `observedAt`, `responseSha256`, `byteSize` and
`representation` (`zip` or `opaque`). Available acquisition headers and optional
`objectKey` stay in scope. URLs must be official and credential-free. Pins establish
retained-byte identity; caller metadata does not independently authenticate a
publisher or establish a complete response without a source witness.

Use `member=None` for an opaque original. ZIP selection requires both the exact
central-directory ordinal and full name, so repeated names remain distinguishable.
Directories cannot supply rows. Other members remain in the exact ZIP.

For CSV use `delimiter=","` and `quoting="csv"`. Literal mode preserves quote
characters and supports comma, pipe, tab or ASCII file separator. Encoding must be
explicitly `utf-8`, `latin-1` or `cp1252`; parsing never restarts with a guessed
encoding. To parse a native `.fec` filing, select `format="fec"` and omit delimiter
and quoting. The existing filing parser reads syntax/version from its header.

## Preserve source meaning

The output includes headers, blank records, unknown filing types and repeated
contents. Values remain strings: leading zeros, decimal spellings, empty fields
and quoted multiline text survive. Delimited rows keep an ordered field array;
filings retain their existing positional field indexes. Header/dictionary mapping
is separate, through the [filing-field API](fec-filing-fields.md) or the retained
bulk companion. No financial column names or data types are guessed.

Each observation has an original digest, member selection and record ordinal.
Byte offsets and lengths refer to the **decoded selected stream**, with that
stream's digest and encoding. Two identical rows remain distinct observations.
These identities do not assert a transaction, committee or filing identity;
native identifiers remain literal source fields.

Filing narrative bodies remain byte/field references through the existing parser.
For a direct `.fec` original, the existing `filing_body` resolver can use those
references. For a ZIP member, open the identified original/member once, verify its
decoded digest and resolve ranges within that stream; its decoded digest does not
imply a separately stored blob. Keep the containing record's member reference
with each body pointer. Do not repeatedly reopen/hash a whole archive per body.

`reader.iter_records()` streams admitted metadata. `reader.iter_evidence(ref)`
streams the exact original and verifies it on exhaustion. The shared lifecycle
keeps the original open while producing/replaying bounded pages, checks declared
page order and terminal state, and refuses omitted or extra pages. One original
is one evidence blob even when it yields many acquisition pages. Failed parsing
produces no partial successful release.

## Resource and qualification limits

Pages contain at most 1,000 records and 1 MiB of serialized response data. The
caller may lower the record count. Each parsed input record is bounded at 128 KiB;
bracketed filing bodies retain the existing line-bounded reference behavior.
Originals, ZIP inventories, member counts and decoded bytes use the existing
[bulk inspection ceilings](fec-bulk.md#bounds-and-refusal-behavior). These limits
are controls, not demonstrated production capacity.

Publication and replay each keep one original open across all its pages. The
existing disk index sorts observations in O(R log R) work for R rows. ZIP integrity
inspection decodes every member, then parsing reads the selected member again.
Nonseekable ZIP providers spool once to disk. Separate releases for many members
repeat archive verification; efficient multi-member batch publication remains open.
Storage and admission also perform their own integrity reads.

[Qualification evidence](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-row-release-2026-09-15/README.md>)
covers retained delimited data and raw filing records, known-answer controls,
stream lifetime, independent replay and an installed core-only wheel. Field-name
mapping, financial interpretation, database restoration, amendment selection,
downstream adoption and population backfills retain their separate status.
