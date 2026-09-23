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
| `iter_records()` | May omit processed keys; yields JSON in download-completion order. Default factory caches an agency's multi-collection listing. | Retain final processed keys, outcomes, and run provenance. |
| `reader_factory(..., bounded=True)` | Streams the listing, fails after a transient retry, and avoids retaining processed keys. | Own checkpoints or full retry and completion receipts. |
| `iter_source_objects()` | Lists and yields in key order; pins GETs to listed ETags and checks metadata/bytes. | Preserve exact objects through the [release evidence pack](regulations-gov.md). |

**Recovery.** A 401/403 during an agency-object listing or GET raises
`MirrulationsAccessRefusedError`, a `CredentialRefusedError`. It ends the run
and is never recorded as a failed or processed key: a refusal over a prefix
would otherwise read downstream as those objects being absent. `fail_fast`
governs unresolved-key failures; refusals always abort.

After complete raw iteration:

- `last_keys` holds only the keys that produced a record. Manifest exactly these.
- `failed_keys` holds every key that produced none, whatever the reason. They stay
  outside processed keys, so the next run asks for them again.
- `unresolved` holds a `KeyOutcome(key, status, reason, attempted_at, attempts)`
  for each, with `status` one of `transport` (connection, 429, 5xx, a vanished object),
  `unreadable` (bytes that are not a JSON record), or `requested-empty` (a 2xx
  that held no identified record — the reason names the shape). `requested-empty` is an
  observation of the answer, never of absence. `parse_failed_keys` remains as the
  non-`transport` subset. `attempts` counts reader download attempts, including
  in-run retries; botocore's internal retries are not counted.
- `unresolved_keys=` (reader) or `unresolved_keys=lambda agency, record_type: ...`
  (factory) feeds those keys back to the next run, which attempts them before any
  newly listed work. Pass the prior `KeyOutcome` values, such as
  `unresolved_keys=previous_reader.unresolved`, to carry attempt counts forward.
  Bare key strings retain priority but supply no attempt history; counts start
  at one when no prior outcome is supplied.

**Record identity.** Dockets, documents, and comments each require a nonblank
string at `data.id`, the source field for their declared `docket_id`,
`document_id`, and `comment_id` keys. The raw reader checks identity only and
preserves the rest of the payload unchanged; it does not validate a full record
schema. This prevents a populated object from becoming a null-id row and a
processed key. `{"data":{}}` and `{"errors":[{"detail":"upstream failed"}]}`
both reproduced that defect. They now yield no record, stay off `last_keys`, and
produce `requested-empty` observations that name the missing identity. A
publisher error envelope is also named as such, with its own message scrubbed
through `scrub_credential` before truncation, logging, or raising. Direct
`download_keys` and `download_and_parse` calls apply the same identity check;
passing `record_type=` adds the type and its declared key to the reason.

The downstream spicy-regs host carries a temporary identity guard until it
adopts the release containing this fix. This local change does not establish
release adoption or repair previously manifested null-id rows.

Nothing is marked processed on a failure, so an object repaired upstream — or a
parser fixed here — comes back on the next run. The in-run retry pass covers
`transport` answers only; the other two cannot change without a new request.
The base cost is one GET per unresolved key per run, with no automatic
retirement. A permanently corrupt or empty object incurs that cost indefinitely;
transport failures can add the in-run retry and botocore's internal retries.

Partial iteration does not establish final accounting. The exact path accepts
no nonempty processed-key set. It retries connections, 429s, and server errors
with bounded jittered backoff; missing/changed objects, refused preconditions,
and byte mismatches abort, and it yields exact bytes without the record-shape
check `iter_records` applies. Concurrent GETs use a bounded queue. Closing
iteration cancels queued work; running calls finish under their transport limits.

## CourtListener

[`courtlistener_bulk.py`](../../src/spicy_docs/sources/courtlistener/bulk.py)
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

**Changed in 0.18:** eligible read exceptions resume only when the initial HTTP
response supplied a strong ETag. Each resume sends that exact `If-Match` with
`Range` at the consumed compressed-byte offset, including zero. Before reading
the resumed body, the reader requires HTTP 206, the same ETag and resolved URL,
and an exact `Content-Range` covering the remaining bytes. It requests identity
HTTP encoding and refuses other encodings. Absent or weak initial ETags allow an
uninterrupted read; malformed or repeated metadata refuses. See the focused
[HTTP owner](../../src/spicy_docs/sources/courtlistener/http.py).

HTTP 401/403 raises `CredentialRefusedError`; HTTP 412 and invalid resume
metadata also stop immediately. Initial connection attempts and subsequent
resume attempts each have a five-attempt limit, without nested retries. Refusal
closes the response; a cleanup failure does not replace the original error.

Natural exhaustion must finish a bzip2 member and match the advertised total
length when known. A shorter response refuses even after a complete member;
the reader does not automatically restart it. Missing initial length is allowed,
and the first valid resume establishes a total. Configured record/byte cutoffs
remain partial passes, including a cutoff at a complete member boundary.

Listing pins and transfer identity are separate. Listed ETags mark revisions,
not content hashes; `published_object_pin()` checks only listing metadata.
Conditional resumes bind to the first download response, not an earlier listing.
The raw reader does not hash or retain the downloaded object for the caller.

### Full passes over a retained export

A network pass is bounded by the bucket (about 1.75 MiB/s). A retained local
original is bounded by decoding: single-threaded, the 54.6 GB `opinions` export
ran at 26 MB/s, near five hours. With the `courtlistener-local` extra there are
two faster routes, both measured on that export on 2026-09-22.

**The streaming reader, sped up.** The strict decoder's quoted-text fast path now
takes backslash escape pairs with it (output unchanged; 56 to 113 MB/s of parsing),
and a full pass over a local file decompresses on every core through
indexed_bzip2 (`decompression_threads`, 0 = all), after checking the magic and the
closing end-of-stream marker so what `bz2` refuses is still refused. Together:
127 MB/s, about an hour. Bounded passes and network streams keep the
single-threaded path and its exact compressed-byte accounting.

**Record-aligned pieces.**
[`CourtListenerLocalDump`](../../src/spicy_docs/sources/courtlistener/local.py)
yields Arrow batches of string columns in file order. With `FORCE_QUOTE *`, a
newline followed by an unescaped quote and a digit can only start a record (its
numeric `id`); on the first 6.0 GB the 134,310 such points were exactly the
records. The text is cut there into pieces of about 256 MB, each written under the
header line to a temporary file and parsed by DuckDB, several at a time. On those
6.0 GB, DuckDB over the pieces parsed 2,277 MB/s against the reference decoder's
137 MB/s, with identical values, NULLs and empty strings, so decompression becomes
the limit.

DuckDB is used only this way because the other ways failed on this export:
through a pipe it keeps every buffer and ran out of memory 160 GB in; its parallel
scan guessed a record start inside a long quoted field and refused a valid record;
and scanning sequentially it drops an unterminated last record without error. It
also accepts text `FORCE_QUOTE *` cannot produce (a lone backslash inside quotes,
a quote in an unquoted field). So each piece is scanned sequentially, its row count
must equal the dialect's count of record starts in it, and its opening 1 MiB is
decoded by `iter_postgres_csv` too and must match. `tests/test_courtlistener_local.py`
mutation-checks each guard and pins that the value check samples each piece's
opening rather than every record. pyarrow's CSV reader was also measured and
rejected: it accepts unterminated and doubled quotes; polars has no backslash
escape.

### Reuse listing rules through the installed wheel

[`courtlistener_listing.py`](../../src/spicy_docs/sources/courtlistener/listing.py)
is a public standard-library parser. Importing it starts no transport, loads no
CSV reader or third-party package, and changes no CSV limits:

```python
from spicy_docs.sources.courtlistener.listing import BulkObject, parse_listing_page

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
uv run --frozen pytest -q tests/test_mirrulations_reader.py tests/test_courtlistener_bulk.py tests/test_courtlistener_listing.py tests/test_courtlistener_csv.py tests/test_courtlistener_local.py
```

Add a focused transport/parsing fixture. Preserve each reader's actual failure
and coverage guarantees. Follow [acquisition rules](../../AGENTS.md) for new fetchers.

## FEC

[`FecClient` and `spicy-docs-fec`](fec.md) read official JSON, XML object listings,
sitemaps and explicit collection links. Metadata and selected originals share
content-addressed storage but have separate acquisition operations. The guide
covers source scope, body references, pagination, native formats and failure handling.
