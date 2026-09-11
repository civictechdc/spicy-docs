# Raw readers and projections

Raw readers yield source-shaped dictionaries for a caller that owns filtering,
persistence, checkpoints, and run receipts. They do not publish source-native
releases. Use the [release path](../releases.md) when you need preserved evidence
and independent replay.

[`Reader`](../../src/spicy_docs/sources/base.py) defines `iter_records()`.
[`RecordType`](../../src/spicy_docs/schemas/base.py) names a record family and its
optional flat projection. Selecting a record type configures a reader's source
path; it does not call the projection. A caller explicitly uses
`record_type.extract(raw)` when it wants flat rows. Schema declarations do not
coerce the extractor's output or validate source evidence.

Regulations.gov projections live in
[`schemas/regulations.py`](../../src/spicy_docs/schemas/regulations.py).
The Federal Register projection lives in
[`schemas/federal_register.py`](../../src/spicy_docs/schemas/federal_register.py)
and feeds the public-table profile. Preserve ordered columns, nulls, and source
values when changing a projection; schema and consumer checks own its output
guarantees. Source-native classification follows a separate path that retains
the original source structure.

## Mirrulations

[`sources/mirrulations.py`](../../src/spicy_docs/sources/mirrulations.py)
supports two different uses of one mirror:

| Use | Input and behavior | What the caller must retain |
| --- | --- | --- |
| Incremental raw records | `iter_records()` can omit processed keys and yield parsed JSON in download-completion order. The default factory caches an agency's multi-collection listing. | Processed-key manifest, failure summary, and run provenance after iteration finishes. |
| Bounded raw records | `reader_factory(..., bounded=True)` streams the listing and fails after a transient retry; it avoids retaining processed keys. | An independent checkpoint or full retry strategy and a complete run receipt. |
| Exact source objects | `iter_source_objects()` lists keys and metadata in order, uses ETag-pinned GETs, checks byte bounds, and yields in listing order. | Exact bytes and metadata through the [Regulations.gov](regulations-gov.md) evidence pack. |

After raw iteration finishes, `last_keys` includes successful keys and
deterministic parse failures. `parse_failed_keys` identifies the latter for
deliberate replay after a parser fix; transient failures remain in `failed_keys`
and outside the processed manifest. This prevents an unchanged malformed object
from causing endless automatic retries while retaining a route to recovery.
A partial iterator does not establish final key accounting.

The exact path accepts no nonempty processed-key set. It retries transient
connection failures, 429s, and server errors with bounded jittered backoff;
missing or changed objects, refused preconditions, and byte mismatches abort.
Concurrent GETs have a bounded queue. Closing iteration cancels queued work;
already-running calls finish under their configured transport limits.

## CourtListener

[`sources/courtlistener_bulk.py`](../../src/spicy_docs/sources/courtlistener_bulk.py)
streams a dated network `.csv.bz2` dump or a local compressed file. It handles
concatenated bzip2 streams and parses CSV incrementally. Empty cells become
`None`; other source strings remain available for downstream shaping.
`row_filter` runs before `max_records` counts accepted rows. A compressed-byte
limit stops at a chunk boundary, so it can exceed the requested threshold by
the final chunk.

Use a new reader for each pass. For a full network pass:

1. Select the dump with `list_bulk_dumps()` and `published_object_pin()`;
   retain the dataset, date, full-key URL, stated bytes, exact ETag (including
   quotes), modification time, and listing provenance. `expect_bytes`,
   `expect_last_modified`, and `expect_etag` compare independently retained
   listing values. Discovery is separate from reading.
2. Exhaust the reader without a record or byte bound, require no exception and
   `stopped_early=False`, then compare `compressed_bytes` with the selected
   object's size.
3. Retain `source_url`, `rows_scanned`, `rows_yielded`, `compressed_bytes`,
   `decompressed_bytes`, `stopped_early`, and `resumes` beside the input pin.

Network read failures resume at the compressed-byte offset. A nonzero-offset
response must return HTTP 206; a server that restarts at byte zero is refused
because splicing it into the existing decompressor would corrupt the stream.

These checks have limits. Listed ETags are publisher revision markers, not
content digests, and the streaming reader does not send an `If-Match` condition
or hash the downloaded object. Matching a listing pin does not bind the later
transfer to those bytes. The reader does not explicitly require bzip2
end-of-stream after input exhaustion. CSV decoding replaces invalid UTF-8 and
tolerates row-width mismatches. Counters are final only after normal completion
or a configured stop;
an exception or caller-initiated close can leave partial values. Preserve the
byte comparison and describe filtered, bounded, or interrupted work accurately.


### Reuse listing rules through the installed wheel

[`sources/courtlistener_listing.py`](../../src/spicy_docs/sources/courtlistener_listing.py)
is the public, standard-library-only parser. Importing it starts no transport,
loads no CSV reader or third-party package, and changes no CSV limits:

```python
from spicy_docs.sources.courtlistener_listing import BulkObject, parse_listing_page

objects, next_token = parse_listing_page(retained_page_bytes)
for obj in objects:
    print(obj.key, obj.size, obj.etag, obj.last_modified)
    print(obj.dataset, obj.dump_date, obj.media_type, obj.url)
```

`BulkObject(key, size, etag, last_modified)` requires all four facts. ETags and
keys retain the exact XML-decoded text. Filename rules recognize dated exports,
retain undated and unknown exports, and provide media types for known suffixes.
URLs retain nested keys and escape URL punctuation. Keys containing `.` or `..`
path segments remain listing facts, but requesting their `url` raises
`ValueError`; this reader has no proven URL representation for those keys.
`transport_version` combines the exact ETag, size, and timestamp as a revision
marker, never as a content hash.

The parser requires the CourtListener S3 root and bucket, the requested prefix,
an explicit `IsTruncated`, and every object's size, ETag, and timestamp. It
rejects duplicate keys within a page and truncated pages without a continuation
token. `MAX_LISTING_PAGE_BYTES` is 8 MiB; live listing reads at most that bound
plus one byte before parsing. Live traversal also rejects duplicate keys across
pages and repeated continuation tokens. A narrower `prefix` must stay under
`bulk-data/`; it must match the page's declared prefix.

The page parser does not admit an entire captured population. DocSpec retains
capture pins, ordered-page completion checks, dataset selection, and withdrawn
versus excluded states. Its D42 task and SpicyRegs' SR03 task cover adoption of
this wheel API and removal of their copies; publishing this API alone does not
establish that either consumer has switched.

## Change and check

```sh
uv run --frozen pytest -q tests/test_mirrulations_reader.py tests/test_courtlistener_bulk.py tests/test_courtlistener_listing.py
```

Add a focused fixture for the transport or parsing condition. Keep raw-reader
failure and coverage promises separate from exact source-native enumeration.
Follow [the acquisition rules](../../AGENTS.md) for any new fetcher.
