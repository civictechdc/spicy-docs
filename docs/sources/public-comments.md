# Captured public comments

This profile captures whole named agency partitions from the community
spicy-regs comment table. It retains the exact Parquet bytes before reconstructing
logical rows. This is an input source for source-native releases; the
[public-table commands](../cli.md#publish-public-table) separately produce flat
tables from admitted releases.

## Scope and evidence

The Python query contains exactly `table: "comments"` and a sorted, distinct
list of agencies. The [CLI](../cli.md#publish) accepts repeated `--agency`
values and canonicalizes their order. Dates are invalid: filtering rows while
claiming whole-partition capture would change the meaning of the input pin.

For each agency, acquisition starts with `part-0.parquet`. One-part look-ahead
marks the preceding partition terminal when the next part is missing. This
assumes the publisher names partitions contiguously: discovery stops at the
first missing part and does not search for later upstream objects. A missing
first part or exhausted scan bound refuses the run. Gaps, repeated locators,
wrong agencies, and extra partitions after a terminal marker in retained
evidence also refuse verification. Empty present partitions remain evidence.

Each ZIP binds the exact Parquet object to its URL, fetch time, stated freshness,
byte size, and digest. Replay validates the manifest and ZIP, hashes the object,
and checks the physical column order and row types. The Hive path supplies
`agency_code`; the other values come directly from the file. The logical row
therefore contains the publisher's 16 columns, including nulls, while the file
contains 15. The closed schema and projection live in
[`schemas/spicy_regs_public_tables.py`](../../src/spicy_docs/schemas/spicy_regs_public_tables.py).

`complete-snapshot` describes the discovered partitions for the named agencies.
It does not cover all agencies, all historical versions, or all origin records.

## Selection and attachment diagnostics

Identity is `comment_id`. The upstream public-table pipeline has already
selected a current row using its declared `modify_date DESC NULLS LAST` rule.
This profile preserves that date and reports upstream selection. It does not
select again: a repeated comment identity refuses publication.

The original `attachments_json` text always stays in the source record. A
separate strict parse derives usable attachment locators. Malformed JSON,
groups, or formats produce field diagnostics; unusable formats are omitted
from the rendition index without losing the source text. Valid renditions
retain declared size where available and infer a media type from the format
or URL when needed. They carry no invented content digest.

Partition corruption, changed physical columns, wrong cell types, and identity
failures remain fatal. Keep this distinction when improving diagnostics:
malformed publisher-authored attachment text is a recordable observation;
unproved partition membership is a failed acquisition.

## Change and check

Capture and replay live in
[`sources/public_comments/native.py`](../../src/spicy_docs/sources/public_comments/native.py),
with profile composition in
[`sources/public_comments/profile.py`](../../src/spicy_docs/sources/public_comments/profile.py).

```sh
uv run --frozen pytest -q tests/test_spicy_regs_public_tables_source_native.py
```

Check exact capture bytes, Hive agency insertion, missing terminal evidence,
empty partitions, repeated identity, and malformed attachment diagnostics.
The [supply decision](../decisions.md#community-supply-precedes-origin-acquisition)
explains when this source takes precedence over origin acquisition.
