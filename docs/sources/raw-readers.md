# Raw readers and projections

Raw readers yield source-shaped dictionaries. The caller owns filtering,
persistence, checkpoints, failures, and run receipts. Use a
[source release](../releases.md) for retained evidence and independent replay;
compare [output choices](../source-workflows.md).

Install `acquisition` for Mirrulations and CourtListener raw readers. The pure
CourtListener listing parser needs only core. See [installation](../installation.md).

[`Reader`](../../src/spicy_docs/sources/base.py) defines `iter_records()`.
[`RecordType`](../../src/spicy_docs/schemas/base.py) names a record family and
optional flat output. Selecting a type configures the source path; a caller
explicitly calls `record_type.extract(raw)` to flatten rows. Schema declarations
neither coerce extractor output nor validate evidence.

Flat field mappings live in [`regulations.py`](../../src/spicy_docs/schemas/regulations.py)
and [`federal_register.py`](../../src/spicy_docs/schemas/federal_register.py).
The latter feeds the public table. Preserve ordered columns, nulls, and source
values; schemas and consumer checks establish output guarantees. Source-native
classification separately retains original structure.

## Mirrulations

[`sources/mirrulations.py`](../../src/spicy_docs/sources/mirrulations.py) provides:

| Mode | Behavior | Caller responsibility |
| --- | --- | --- |
| `iter_records()` | May omit processed keys; yields JSON in download-completion order. Default factory caches an agency's multi-collection listing. | Retain final processed keys, failures, and run provenance. |
| `reader_factory(..., bounded=True)` | Streams the listing, fails after a transient retry, and avoids retaining processed keys. | Own checkpoints or full retry and completion receipts. |
| `iter_source_objects()` | Lists and yields in key order; pins GETs to listed ETags and checks metadata/bytes. | Preserve exact objects through the [release evidence pack](regulations-gov.md). |

After complete raw iteration:

- `last_keys` includes successes and deterministic parse failures.
- `parse_failed_keys` identifies failures for deliberate replay after a parser
  fix, avoiding endless retries of unchanged malformed objects.
- `failed_keys` holds transient failures, which stay outside processed keys.

Partial iteration does not establish final accounting. The exact path accepts
no nonempty processed-key set. It retries connections, 429s, and server errors
with bounded jittered backoff; missing/changed objects, refused preconditions,
and byte mismatches abort. Concurrent GETs use a bounded queue. Closing iteration
cancels queued work; running calls finish under their transport limits.

## CourtListener

[`courtlistener_bulk.py`](../../src/spicy_docs/sources/courtlistener_bulk.py)
streams a dated network `.csv.bz2` dump or local file. It handles concatenated
bzip2 streams and incremental CSV. An unquoted empty field becomes `None`;
`""` remains an empty string. Other values remain strings, including whitespace
and literal `\N`. `row_filter` runs before `max_records` counts accepted rows.

The [publisher's export script](https://github.com/freelawproject/courtlistener/blob/main/scripts/make_bulk_data.sh)
uses PostgreSQL CSV with UTF-8, a header, backslash escaping, and `FORCE_QUOTE *`.
Backslashes escape quotes and backslashes inside quoted values. This follows
[PostgreSQL's CSV rules](https://www.postgresql.org/docs/current/sql-copy.html).
The source decoder handles this dialect directly because
[Python 3.12's `QUOTE_NOTNULL` reader is affected by a documented bug](https://docs.python.org/3.12/library/csv.html#csv.QUOTE_NOTNULL).
It refuses invalid UTF-8, malformed quoting, empty/duplicate header names, and
row-width mismatches. Errors identify the CSV record (header = 1), without values.

Decompression drains in 64 KiB blocks. `max_record_characters` defaults to
64 Mi characters, including CSV syntax but excluding the record's line ending;
raise it explicitly for larger source records. Records also have a 1,024-column
limit. These are per-record limits, so memory does not grow with dump size.
A compressed-byte bound caps each read to its remaining allowance. Already-read
bytes drain; an unfinished final record is discarded.
Counters finalize on completion, configured stop, failure, or explicit generator
close. The latter three set `stopped_early=True`.

Use a new reader per pass. For a full network pass:

1. Select with `list_bulk_dumps()` and `published_object_pin()`. Retain dataset,
   date, full-key URL, stated bytes, exact quoted ETag, modification time, and
   listing provenance. Supply independently retained `expect_bytes`,
   `expect_last_modified`, and `expect_etag`; discovery is separate from reading.
2. Exhaust without record/byte bounds. Require no exception and
   `stopped_early=False`; compare `compressed_bytes` with the listed size.
3. Retain `source_url`, `rows_scanned`, `rows_yielded`, `compressed_bytes`,
   `decompressed_bytes`, `stopped_early`, and `resumes` beside the input pin.

Network failures resume at the compressed-byte offset. Nonzero offsets require
HTTP 206; a restart at zero is refused to prevent decompressor corruption.
Natural source exhaustion must finish a bzip2 member; a missing footer raises.
A configured byte cutoff remains a partial pass, even at a member boundary.

Know the limits before treating a pass as complete:

- Listed ETags mark revisions, not content hashes. The reader sends no
  `If-Match` and hashes no downloaded object; a matching pin does not bind the
  later transfer to listed bytes.

### Reuse listing rules through the installed wheel

[`courtlistener_listing.py`](../../src/spicy_docs/sources/courtlistener_listing.py)
is a public standard-library parser. Importing it starts no transport, loads no
CSV reader or third-party package, and changes no CSV limits:

```python
from spicy_docs.sources.courtlistener_listing import BulkObject, parse_listing_page

objects, next_token = parse_listing_page(retained_page_bytes)
for obj in objects:
    print(obj.key, obj.size, obj.etag, obj.last_modified)
    print(obj.dataset, obj.dump_date, obj.media_type, obj.url)
```

`BulkObject(key, size, etag, last_modified)` requires all four facts. Keys and
ETags retain XML-decoded text. Filename rules recognize dated exports, retain
unknown/undated exports, and assign known media types. URLs preserve nested keys
and escape punctuation. A key containing `.` or `..` segments remains a listing
fact, but its `url` raises `ValueError`. `transport_version` combines exact ETag,
size, and timestamp as a revision marker, never a content hash.

The parser requires the CourtListener S3 root/bucket, requested prefix, explicit
`IsTruncated`, and each object's size, ETag, and timestamp. It refuses duplicate
page keys and truncated pages without continuation tokens. A narrowed prefix
must remain under `bulk-data/` and match the page declaration.
`MAX_LISTING_PAGE_BYTES` is 8 MiB; live listing reads at most one extra byte to
detect overflow. Live traversal also rejects duplicate keys across pages and
repeated continuation tokens.

This parser checks pages, not a complete captured population. DocSpec owns
capture pins, ordered-page completion, dataset selection, and withdrawn versus
excluded states. DocSpec D42 and SpicyRegs SR03 own adoption and removal of their
copies; the wheel API alone does not establish adoption.

## Change and check

```sh
uv run --frozen pytest -q tests/test_mirrulations_reader.py tests/test_courtlistener_bulk.py tests/test_courtlistener_listing.py
```

Add a focused transport/parsing fixture. Preserve each reader's actual failure
and coverage guarantees. Follow [acquisition rules](../../AGENTS.md) for new fetchers.

## FEC

[`FecClient` and `spicy-docs-fec`](fec.md) read official JSON, XML object listings,
sitemaps and explicit collection links. Metadata and selected originals share
content-addressed storage but have separate acquisition operations. The guide
covers source scope, body references, pagination, native formats and failure handling.
