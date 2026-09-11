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
   retain the dataset, date, URL, stated bytes, modification time, and listing
   provenance. Discovery is separate from reading.
2. Exhaust the reader without a record or byte bound, require no exception and
   `stopped_early=False`, then compare `compressed_bytes` with the selected
   object's size.
3. Retain `source_url`, `rows_scanned`, `rows_yielded`, `compressed_bytes`,
   `decompressed_bytes`, `stopped_early`, and `resumes` beside the input pin.

Network read failures resume at the compressed-byte offset. A nonzero-offset
response must return HTTP 206; a server that restarts at byte zero is refused
because splicing it into the existing decompressor would corrupt the stream.

These checks have limits. The connector records no content digest or ETag and
does not explicitly require bzip2 end-of-stream after input exhaustion. CSV
decoding replaces invalid UTF-8 and tolerates row-width mismatches. Listing can
return a partial inventory when a truncated response lacks its continuation
token. Counters are final only after normal completion or a configured stop;
an exception or caller-initiated close can leave partial values. Preserve the
byte comparison and describe filtered, bounded, or interrupted work accurately.

## Change and check

```sh
uv run --frozen pytest -q tests/test_mirrulations_reader.py tests/test_courtlistener_bulk.py
```

Add a focused fixture for the transport or parsing condition. Keep raw-reader
failure and coverage promises separate from exact source-native enumeration.
Follow [the acquisition rules](../../AGENTS.md) for any new fetcher.
