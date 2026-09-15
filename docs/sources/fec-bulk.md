# Publish retained FEC bulk originals

Use `FEC_BULK_FILES_PROFILE` to publish caller-selected original files through the
existing source-native publisher. Each release record describes one file. A ZIP
record also inventories every archive member. Exact originals remain separate
evidence blobs; they are neither repacked nor copied into JSON metadata.

This is a core-only, offline interface. Use the existing [FEC acquisition
API](fec.md) to enumerate XML listings and download selected originals first.
Keep those discovery captures separately; selecting files here does not establish
a complete listing, cycle, financial population or publisher snapshot.

## Inputs and publication

Supply ordered capture dictionaries with these required fields:

| Field | Meaning |
| --- | --- |
| `requestUrl` | Exact official S3 or `fec.gov/files/bulk-downloads/` object URL. |
| `objectKey` | Matching `bulk-downloads/...` key, unique within this release. |
| `observedAt` | Capture time with a timezone. |
| `responseSha256`, `byteSize` | Digest and size of the exact stored original. |
| `representation` | Explicitly `zip` for member inspection or `opaque` for byte retention only. |

Preserve available `resolvedUrl`, `mediaType`, `via`, `etag`, `lastModified`,
`contentEncoding` and `contentLength` as their original source strings. An identity
Content-Encoding with a different Content-Length refuses. Encoded transfer lengths
are distinct from decoded body lengths. Missing witnesses do not prove that an
opaque capture is the publisher's complete answer; a matching caller digest only
establishes the retained bytes. ETags are source observations, not content hashes.

```python
from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher
from spicy_docs.sources.fec.bulk_profile import (
    FEC_BULK_FILES_PROFILE,
    bulk_file_scope,
    iter_retained_bulk_files,
)

# captures, originals, output_blobs and producer come from the caller's retained run.
scope = bulk_file_scope(captures, max_members=1_000, max_decoded_bytes=8 * 1024**3)
published = SourceNativeReleasePublisher(FEC_BULK_FILES_PROFILE, blob_store=output_blobs).publish(
    iter_retained_bulk_files(scope, blob_source=originals),
    build=SourceNativeReleaseBuild(query_scope=scope, producer=producer, started_at=started_at),
    destination=destination,
)
```

Use the existing [release lifecycle](../releases.md) to retain the producer,
artifact pin and blob store, admit the release and replay its records. Publication
refuses missing or repeated selected files. Original object keys are ASCII in this
profile; ZIP member names preserve their native Unicode spelling.

## Outputs and evidence

Each record contains the exact `capture` dictionary and an `archive` inventory,
or `archive: null` for an opaque file. Identity is the original object key. Counts
mean files, including empty archives; they never mean transactions or financial
rows. No body rendition is inferred.

ZIP inventories retain central-directory order, full member names, directories,
repeated names, empty entries, compressed/decoded sizes, methods, flags, timestamps,
header offsets, attributes, extra fields and comments. Each member has its own
decoded SHA-256 and verified CRC. Use ordinal together with the full name to
distinguish duplicate entries. The original ZIP remains the authority for exact
encoded headers and member bytes.

`reader.iter_evidence(blob_ref)` streams an admitted original in bounded chunks:

```python
evidence = reader.record_evidence(object_key)
with destination_file.open("wb") as output:
    for chunk in reader.iter_evidence(evidence["evidenceBlobRef"]):
        output.write(chunk)
```

Exhaust the iterator to verify its complete size and digest. Closing it early
closes the underlying stream but does not establish full verification. The existing
`read_evidence` API retains its small-response limit. The [positional row profile](fec-rows.md) can publish a selected decoded stream
through the same publisher. File inventories do not restore databases, interpret
amendments or join header companions automatically.

## Bounds and refusal behavior

The caller explicitly bounds ZIP member count and total decoded bytes. Profile
ceilings are 1,000 selected files, 2 MiB of capture metadata, 64 GiB per original,
10,000 members per ZIP, 1 TiB decoded per ZIP and 2 MiB of inventory per file.
Bounds are implementation limits, not tested production capacities.

Stored and deflate-compressed members have bounded decoders that check the complete
compressed range, decoded size and CRC. Other compression methods, encrypted or
split archives, malformed end records and trailing archive bytes refuse. Refused
originals already retained in the output store remain available through the failed
run's evidence record; no partial successful release is produced.

Metadata reads are bounded before ZIP directory allocation. Nonseekable providers
spool once to disk; seekable providers reuse one open stream for an inspection.
Work scales with compressed/decoded bytes plus bounded directory sorting
O(M log M) for M members. Storage, admission and replay perform their own integrity
reads; there is no claim that the entire workflow reads each original only once.

The shared publisher uses opt-in `SourceNativeBlobPage` and `parse_page_stream`
interfaces. Existing byte profiles keep their original evidence bound and release
format. [Retained-file, installed-wheel and regression evidence](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-bulk-release-2026-09-15/README.md>)
records the qualification scope and limits.
