# Captured public comments

Capture whole named agency partitions from the community spicy-regs comment
table, retaining exact Parquet before reconstructing rows. This input profile
has no separate public-table export; the original parts stay in its evidence.
[Public-table commands](../cli.md#publish-public-table) export other admitted
source releases.

Install `public-table` for captured Parquet parsing/full replay and `acquisition`
for default HTTP fetching. Admitted record/evidence reading needs only core.
See [installation](../installation.md).

## Scope and evidence

The query requires exactly `table: "comments"` and sorted, distinct agencies.
The [CLI](../cli.md#publish) canonicalizes repeated `--agency` values. Dates are
invalid because this capture pins whole partitions.

- Acquisition starts at `part-0.parquet`. One-part look-ahead marks the preceding
  part terminal when the next is missing; discovery then stops.
- Names are assumed contiguous. If part 1 is missing, part 2 is unrequested even
  if it exists. The capture makes no claim about later parts.
- A missing first part or exhausted 64-part probe bound refuses acquisition.
  Request failures never become empty parts or terminal markers.
- A present zero-row part is evidence and may produce an observed-empty release.
  A missing first part leaves the agency unresolved, not absent.
- Replay refuses gaps, repeated locators, wrong agencies, and extra parts after
  a terminal marker. Missing-part HTTP responses are not retained: replay checks
  captured bytes and the declared sequence, not why live discovery stopped.

Each ZIP binds the Parquet bytes to URL, fetch time, stated freshness, size, and
digest. Replay checks the ZIP/manifest, object hash, physical column order, and
row types. The Hive path supplies `agency_code`: the file has 15 columns, and the
logical row has 16, preserving nulls. See the
[closed schema](../../src/spicy_docs/schemas/spicy_regs_public_tables.py).

Policy `1.2` uses `observed-crawl`, `single-observed-traversal`, and
`observed-contiguous-part-probing`. It pins observed parts, not all upstream
members, agencies, historical versions, or one publisher-wide instant.
[Outcomes](../source-native-outcomes.md) expose these digest-checked limits and
requested agencies. Current readers refuse earlier policies; pack and row shapes
remain unchanged.

## Selection and attachment diagnostics

Identity is `comment_id`. Upstream selected the current row with
`modify_date DESC NULLS LAST`; this profile preserves that date and reports
upstream selection. It refuses repeated identities instead of selecting again.

Original `attachments_json` always remains in the record. A separate strict
parse derives attachment locators:

| Condition | Result |
| --- | --- |
| Malformed attachment JSON, groups, or formats | Field diagnostic; unusable formats omitted from renditions, source text retained |
| Usable format | Locator, declared size when available, and media type supplied or inferred from format/URL; no invented content digest |
| Partition corruption, changed columns, wrong cell types, or identity failure | Fatal refusal |

Rendition IDs and source fields retain the original attachment and format
positions, including gaps left by invalid entries. Policy `1.2` pins those rules
and the media-type aliases. Publisher types take precedence; fallback uses only
the final URL path extension, ignoring queries, fragments and parent directories.
JSON is `application/json`; unknown formats remain `application/octet-stream`.

Renditions describe candidates, not downloaded files. Stream captured records
through `SourceNativeReleaseReader`; see [output choices](../source-workflows.md).

## Change and check

Owners: [`native.py`](../../src/spicy_docs/sources/public_comments/native.py)
and [`profile.py`](../../src/spicy_docs/sources/public_comments/profile.py).

```sh
uv run --frozen pytest -q tests/test_spicy_regs_public_tables_source_native.py
```

Cover exact bytes, Hive agency insertion, terminal evidence, first-missing and
gap probes, empty parts, request failures, repeated identity, and attachment
diagnostics. Follow the [community supply rule](../decisions.md#community-supply-precedes-origin-acquisition).
