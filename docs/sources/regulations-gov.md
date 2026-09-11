# Regulations.gov through Mirrulations

Three profiles capture documents, dockets, and comments from the anonymous
Mirrulations S3 mirror. They enumerate exact objects for the named agencies,
retain those bytes in deterministic ZIP packs, and select in-scope records for
an immutable release. `complete-snapshot` refers to the enumerated mirror
scope, not the whole Regulations.gov service or its history.

## Scope and evidence

| Collection | Date window uses | Selection version uses |
| --- | --- | --- |
| Documents | `postedDate` | `modifyDate`, falling back to `postedDate` |
| Dockets | `modifyDate` | `modifyDate` |
| Comments | `postedDate` | `modifyDate` |

The [CLI](../cli.md#publish) requires dates and named agencies. An object's S3
path, collection, agency, and body identity must agree. Refetch suffixes in
object filenames are understood by the source classifier; they do not create
new record identities. Documents with a null or unusable posted date are
retained as excluded evidence. Dockets and comments require their respective
scope dates.

Each date-window query reads the full named agency/collection enumeration and
then decides inclusion from each object's body. Splitting history into shorter
date windows repeats those reads; it does not reduce the acquisition scope or
make the source cheaper to fetch.

The exact reader lists objects in key order, pins each GET to its listed ETag,
and checks response metadata and byte length. Changed or missing objects abort
the complete enumeration. This path accepts no processed-key omission; the
[raw reader](raw-readers.md#mirrulations) has a separate incremental mode.
ETags and conditional GETs pin each listed object's bytes. The listing itself
is not a transactionally frozen snapshot: the release covers the ordered
objects observed during enumeration, not one shared upstream instant.

Each pack records exact object bytes and their disposition. Packs start at zero
and remain contiguous within each agency; every agency ends with a terminal
pack. Agencies and keys must stay ordered and distinct. Publication and replay
recompute inclusion from each saved body and compare it with the manifest and
result list. Changing an `included` flag cannot silently change membership.

## Selection preserves source differences

All three profiles identify a record by `data.id`. Timestamps are normalized
to UTC only for comparison; the original source timestamp stays in the record.
A non-null version wins over null.

| Collection | Repeated winning version |
| --- | --- |
| Documents | Identical canonical records collapse. If only `openForComment` or `withinCommentPeriod` differs, the last-listed observation wins. Any other difference refuses publication. |
| Dockets | Identical canonical records collapse; different records refuse publication. |
| Comments | Any repeated identity and normalized version refuses publication, even for identical records or null versions. |

The two document fields above can change at read time without a new source
version. The tie comparison omits only those fields; the published digest still
covers the full selected record, and evidence retains every observation. See
[the source decisions](../decisions.md#similar-sources-can-need-different-rules).

Classifiers accept closed source shapes. Unknown fields, malformed identity,
wrong agency, and ambiguous versions fail rather than being silently repaired.
Rendition rows preserve supplied attachment locators and metadata; downloading
or interpreting their contents belongs to later work.

## Change and check

[`sources/regulations_gov/`](../../src/spicy_docs/sources/regulations_gov/)
owns this behavior: declarations in `definitions.py`, source validation in
`validation.py`, classification and versions in `records.py`, schemas in
`schemas.py`, membership and completeness in `scope.py`, capture decoding in
`evidence.py`, acquisition in `acquisition.py`, and profile composition in
`profile.py`.

```sh
uv run --frozen pytest -q tests/regulations_gov/ tests/test_mirrulations_reader.py
```

Keep fixtures for out-of-scope objects, refetches, null dates, changed metadata,
missing terminal packs, source drift, and ties. A schema-only test does not
exercise key-to-body identity or enumeration proof; include replay when changing
those rules.
