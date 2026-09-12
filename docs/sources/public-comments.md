# Captured public comments

This profile captures whole named agency partitions from the community
spicy-regs comment table. It retains the exact Parquet bytes before reconstructing
logical rows. This is an input source for source-native releases; the
[public-table commands](../cli.md#publish-public-table) separately produce flat
tables from admitted releases.

Install `public-table` to parse captured Parquet or run full source replay, and
add `acquisition` for the default HTTP fetcher. Reading already admitted source
records and their evidence needs only the core package. See
[installation choices](../installation.md).

## Scope and evidence

The Python query contains exactly `table: "comments"` and a sorted, distinct
list of agencies. The [CLI](../cli.md#publish) accepts repeated `--agency`
values and canonicalizes their order. Dates are invalid: filtering rows while
claiming whole-partition capture would change the meaning of the input pin.

For each agency, acquisition starts with `part-0.parquet`. One-part look-ahead
marks the preceding partition terminal when the next part is missing. This
assumes the publisher names partitions contiguously: discovery stops at the
first missing part and does not search for later upstream objects. If part 0
exists, part 1 is missing, and part 2 exists, acquisition captures part 0 and
never requests part 2. It makes no claim about part 2's existence. A missing
first part or exhausted 64-part probe bound refuses the run. Gaps within the
retained sequence, repeated locators, wrong agencies, and extra partitions after
a terminal marker in retained evidence also refuse verification.

A present Parquet partition with zero rows remains evidence and can produce an
observed-empty release. A missing first part leaves that agency unresolved;
it does not establish that the agency has no comments. Request failures abort
collection rather than becoming empty partitions or terminal markers.

Each ZIP binds the exact Parquet object to its URL, fetch time, stated freshness,
byte size, and digest. Replay validates the manifest and ZIP, hashes the object,
and checks the physical column order and row types. The Hive path supplies
`agency_code`; the other values come directly from the file. The logical row
therefore contains the publisher's 16 columns, including nulls, while the file
contains 15. The closed schema and projection live in
[`schemas/spicy_regs_public_tables.py`](../../src/spicy_docs/schemas/spicy_regs_public_tables.py).

Acquisition policy `1.1` declares `observed-crawl`, accepted as one
`single-observed-traversal`. Its `observed-contiguous-part-probing` strategy
states the contiguous-name assumption in the policy itself. The capture pins
the observed partition bytes; it does not prove complete upstream membership,
all agencies, historical versions, or a single publisher-wide instant.

The terminal marker records the acquirer's stopping decision. The missing-part
HTTP response is not retained, so replay checks the declared captured sequence
and its bytes, rather than proving why the live scan stopped. The
[collection outcome](../source-native-outcomes.md) exposes the exact requested
agencies and the digest-checked policy with these limits. Policy `1.0` releases
are refused by the current profile; capture-pack and source-row shapes are
unchanged.

You can stop at the admitted source release and stream the captured comments
through `SourceNativeReleaseReader`. This input profile has no separate
public-table export command; the original Parquet parts are already retained
inside its evidence. Listed attachment formats remain document candidates,
not downloaded files. See [source workflows](../source-workflows.md).

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
first-missing and gap probes, empty partitions, request failures, repeated
identity, and malformed attachment diagnostics.
The [supply decision](../decisions.md#community-supply-precedes-origin-acquisition)
explains when this source takes precedence over origin acquisition.
