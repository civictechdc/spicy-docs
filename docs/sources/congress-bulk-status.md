# Back-fill BILLSTATUS one Congress and one bill type at a time

Give SpicyDocs a Congress number and one bill type. It returns the exact GovInfo
bulkdata zip for that folder, every member's own bytes and digest, and either the
parsed BILLSTATUS or the reason that member was refused. No API key is required.

This is the bulk half of the bills family. [One bill at a time](congress-bills.md)
stays the route for an explicit bill and its text versions; this route exists to
fill a Congress and then be left alone, because the publisher rebuilds each zip
daily and the Congress.gov API is what carries the days since.

| Route | Required selection | What it supplies |
| --- | --- | --- |
| Folder archive | Congress and one bill type | `bulkdata/BILLSTATUS/{congress}/{type}/BILLSTATUS-{congress}-{type}.zip`, validated member by member |
| Folder listing | Congress and one bill type | `bulkdata/json/BILLSTATUS/{congress}/{type}`, every file the folder holds, the zip included, with its own last-modified stamp and size |

Bill types are the publisher's own lowercase folder names: `hr`, `s`, `hjres`,
`sjres`, `hconres`, `sconres`, `hres`, `sres`. Anything else is refused before a
request is made.

## The crawl bound this source states

The [families record](../decisions.md#congressgov-and-govinfo-collections-are-each-one-family)
requires every bulk crawl to name its bound and its byte budget before it is
built. This one is **one Congress and one bill type per call**. There is no
whole-Congress call and no collection call: eight calls cover a Congress, and a
caller that wants eight makes eight, paced by its own client. Measured on
2026-09-19, the 119th Congress costs 52,236,275 bytes over its eight zips, of
which H.R. alone is 31,656,886 bytes.

Those byte figures are one capture, not a constant: the publisher rebuilds each
zip, and the H.R. zip was 31,656,886 bytes in the morning of 2026-09-19 and
31,658,670 bytes that afternoon, over the same 10,503 members. Size a budget
with headroom and re-measure rather than pinning a folder to a byte count.

A folder that answers 404 raises `BillSourceUnavailableError` with the exact
capture: it describes that folder on that day, not the Congress. Bulk lags the
Congress.gov API by days, so a finished backfill is a floor, and the delta is an
API pass by update date, never a second zip.

## Bounds and the measurements behind them

Every bound is the caller's; these are the defaults and what they were measured
against on 2026-09-19 over the 119th Congress, the largest of the three swept
below.

| Budget field | Default | Measured basis |
| --- | --- | --- |
| `max_bytes` | required | The largest type zip is H.R. at 31,656,886 bytes and the whole Congress is 52 MB, so 64 MiB covers any one folder. Capped at 256 MiB. |
| `max_entries` | 32,768 | H.R. holds 10,503 members and the whole 119th holds 18,956. |
| `max_entry_bytes` | 24 MiB | The largest single member is `BILLSTATUS-119hr1.xml` at 1,979,603 bytes. This is the same evidence bound one bill's status capture uses. |
| `max_total_bytes` | 512 MiB | H.R. decodes to 144,870,036 bytes. Capped at 2 GiB, which is the 256 MiB zip cap at the 4.6:1 ratio BILLSTATUS deflates at. |

The four archive bounds refuse the **whole zip**, before any member is trusted:
too many entries, an entry over its own limit, a decoded total over its limit, a
repeated entry name, an unsupported compression method or a failed CRC. Those say
the response is not the archive that was asked for, so no part of it is a record.

## What each outcome means

Each member arrives in the publisher's own order as a `BulkStatusMember` with its
name, byte size and SHA-256, and exactly one of `status` or `refusal`.

- **Parsed.** `identity` is the bill the member's name declared *and* its XML
  stated; `status` is the same `BillStatus` the single-bill route returns.
- **Refused, no identity.** The name is not a bulkdata BILLSTATUS file name, so
  nothing about it is a bill. The bytes and their digest are still kept.
- **Refused, wrong folder.** The name parses but names another Congress or type.
  A member's name must rebuild the single-file locator for the requested folder
  exactly; a padded number or a foreign folder is refused, never reinterpreted.
- **Refused, XML disagrees.** The name and the XML name different bills. This is
  the check that makes the archive evidence rather than a directory listing.
- **Refused, superseded schema.** The file is BILLSTATUS 1.0.0, which spells the
  identity `<billType>`/`<billNumber>` and puts `<version>` inside `<bill>`.
  Only 3.0.0 is read, and the refusal says so by name.

A refused member never ends the read. One unreadable file out of ten thousand is
one refused row, and `parsed_count` plus `refused_count` always equals
`len(members)`, because both counts are read off the members themselves.

## The folder listing: a small request that answers "has the zip moved"

GovInfo answers a keyless JSON listing for the same folder, at
`bulkdata/json/BILLSTATUS/{congress}/{type}`, naming every file it holds — the
zip and every individual member XML the publisher also serves loose. It is a
fraction of the zip's own bytes: measured 2026-09-19, the 119th H.Res. listing
is 569,986 bytes over 1,567 entries against a 3,934,575-byte zip (14%), and
H.R., the largest folder, listed 10,504 entries in 3,744,366 bytes against a
31,656,886-byte zip (12%). `bulk_listing_locator(congress, bill_type)`
names the route and `read_bulk_listing` reads a retained response offline,
the same way `read_bulk_status_archive` replays a retained zip.
`list_archives` bounds the request by the smaller of the caller's own
`max_bytes` (sized for the zip) and `DEFAULT_MAX_LISTING_BYTES`, so a budget
built for a 64 MiB zip does not also become a 64 MiB cap on an 8 MiB-bounded
listing.

Every entry proves its own identity: its `link` must rebuild the single-file
locator `bulk_status_locator` would spell for its `name` in the requested
Congress and bill type, the same "prove it, don't reinterpret it" rule a zip
member's name is held to. An entry that fails this — another folder's file,
or a listing shape this route has never stated — refuses the **whole**
listing, because a response that cannot be proved to be this folder's own is
not evidence about this folder. A listing with no zip entry for the folder
also refuses by name: `{"files": []}` is a well-formed answer, and "empty
success is not absence."

| Field | Type | Publisher key | Notes |
| --- | --- | --- | --- |
| `name` | `str` | `name` | The file or subfolder's own name. |
| `display_label` | `str` | `displayLabel` | The name as the publisher's own UI would show it. |
| `just_file_name` | `str` | `justFileName` | Measured identical to `name` in every one of 18,964 entries checked. |
| `link` | `str` | `link` | The single-file URL; what proves the entry's identity. |
| `folder` | `bool` | `folder` | `false` for every entry this route has answered so far — a bulk status folder holds no subfolders — kept typed because a sibling listing level (`BILLSTATUS/{congress}`, no bill type) does answer `folder: true` rows. |
| `formatted_last_modified_time` | `str` | `formattedLastModifiedTime` | The publisher's own `DD-Mon-YYYY HH:MM` spelling, GMT, seconds truncated. |
| `modified_at` | `datetime` | *(parsed)* | `formatted_last_modified_time` parsed to a UTC instant, confirmed 2026-09-19 against the zip's own HTTP `Last-Modified` header to the minute. |
| `mime_type` | `str \| None` | `mimeType` | `None` on a `folder: true` row, which states no MIME type. |
| `file_extension` | `str \| None` | `fileExtension` | Same optionality as `mime_type`. |
| `formatted_size` | `str \| None` | `formattedSize` | The publisher's human-readable size (`"3.8 MB"`); same optionality. |
| `size` | `int \| None` | `size` | The byte count a caller compares; `None` on a `folder: true` row. |

All ten publisher fields were present on every one of 18,964 entries measured
2026-09-19 across all eight 119th bill-type listings; the four
file-only fields stay typed `| None` for the folder-row shape this route has
never itself answered, not because this route's own entries have been seen
missing them. `BulkListing` also carries `folder_modified: datetime | None`,
the listing response's own stamp for the whole folder when the publisher
states one — measured `None` here, since this route answers only
`{"files": [...]}` at its own top level, with no sibling of `formattedLastModifiedTime`
beside `files`.

### Skip a zip download the listing proves is unchanged

`BulkStatusAcquirer.acquire` takes an optional `unchanged_since:
BulkListingEntry | None`. Pass the zip entry retained from a prior call's
`listing_entry` (or a standalone `list_archives`), and `acquire` reads the
folder's listing first — one small request — before ever asking for the zip.
`unchanged_since` must first name the same file the listing's own zip entry
does (`name` and `link` both equal): an entry retained from a different
folder or a different call names a different file, not a stale version of
this one, and comparing its `modified_at`/`size` against this folder's zip
would risk a false skip, so a mismatch there refuses outright rather than
silently falling through to "changed." Once identity agrees, if the listing's
own zip entry also states the same `modified_at` and `size` as
`unchanged_since`, the zip download is skipped entirely: the returned
`BulkStatusAcquisition` carries `skipped_unchanged=True`, `archive` and
`capture` both `None`, and `listing_capture`/`listing_entry` set from the
listing alone. Otherwise the zip downloads exactly as it always has, and
`listing_entry` still carries the entry this call saw, for the next run's
`unchanged_since`. Without `unchanged_since`, `acquire` behaves exactly as
before: one zip request, no listing read.

The listing and the zip share this call's one `max_requests` budget rather
than each getting its own: the listing's capture never resets the client's
request count, so a listing that already spent the whole budget (retries
included) leaves none for the zip, and the zip request is refused with the
same "exhausted its total request budget" error a single over-budget request
would raise — never silently granted a second, independent allowance.
`request_count` on the returned acquisition is always the true total for the
call, the listing's request counted in it whenever one was made. The zip
capture is wrapped in `named_challenge` exactly as the listing's is, so a
401/403 bot wall on either request raises this family's own `BillSourceError`
rather than the shared client's generic credential-refusal error.

```python
from spicy_docs.sources.congress.bulk_status import BulkStatusAcquirer, BulkStatusBudget

budget = BulkStatusBudget(max_requests=2, max_bytes=64 * 1024**2, timeout_seconds=120, min_request_interval_seconds=1)
with BulkStatusAcquirer(budget=budget) as source:
    # First run: nothing retained yet, so the zip downloads; retain the listing entry it saw.
    first = source.acquire(119, "hres")
    seen = source.list_archives(119, "hres").listing.zip_entry  # Retain this in caller-owned storage.

    # A later run: skip unless the listing shows the zip has moved.
    result = source.acquire(119, "hres", unchanged_since=seen)
    if result.skipped_unchanged:
        print("unchanged since", seen.modified_at, seen.size)
    else:
        archive_zip = result.capture.body
        seen = result.listing_entry  # Retain the new entry for the next run.
```

## Use it in an application

Pure locator and archive functions need only the core package; capture needs the
`acquisition` extra (`uv sync --frozen --extra acquisition`).

```python
from spicy_docs.sources.congress.bulk_status import BulkStatusAcquirer, BulkStatusBudget

budget = BulkStatusBudget(max_requests=2, max_bytes=64 * 1024**2, timeout_seconds=120, min_request_interval_seconds=1)
with BulkStatusAcquirer(budget=budget) as source:
    result = source.acquire(119, "hres")

print(result.capture.sha256, result.capture.byte_size, result.capture.observed_at)
print(len(result.archive.members), result.archive.parsed_count, result.archive.refused_count)
for member in result.archive.members:
    if member.refusal is None:
        print(member.identity, member.status.title, member.sha256)
# Retain these exact bytes in caller-owned storage:
archive_zip = result.capture.body
```

`read_bulk_status_archive(archive_zip, congress=119, bill_type="hres")` repeats
the whole read offline from retained bytes, with no client and no network, and
returns the same outcomes. Failures carry `bulk_status_acquisition` context — the
operation, the selection, the request count and the effective budget — plus the
capture and, within bounds, `refused_response` evidence.

## Decision 4, measured

The [port plan's](../research/billtrax-port-2026-09-15.md) decision 4 asks
whether this repository's bill parser is stricter than the publisher's own data.
On the status side it was, and the measurement says exactly where.

**What was measured.** `parse_bill_status` over every member of the 119th H.R.,
H.Res. and S.Res. status zips, 12,938 files, on 2026-09-19. The H.Res. zip is the
one the [data map](../research/legislative-data-map-2026-09-18.md) compared
against the Congress.gov bill list, where 113 of its 1,566 files were refused.

**What the 113 were.** Every one hit the same rule, `bill XML requires one text
element`, but for two different reasons, and the rule was right about neither:

| Cause | H.R. | H.Res. | S.Res. | What the publisher's file actually does |
| --- | --- | --- | --- | --- |
| Summary `<text>` inside a `<cdata>` element | 810 | 110 | 64 | States the text one element deeper, as the wrapper's only child |
| An `<actions><item>` with no `<text>` | 0 | 4 | 3 | States `actionCode`, `type` and `sourceSystem` and no text at all |

H.Res. 10 is the first cause; its summary is `<cdata><text>` and the text is
there in full. One H.Res. file has both causes, which is why 110 + 4 is 113. A
third shape, an action whose `<text>` is present but blank, occurs in none of
the 12,938 files: every action either states text or omits the element.

**What the publisher says.** The
[user guide](../../tests/fixtures/billstatus_codes/guide-2026-08-03.md) lists
every child of `<actions>` as one the element "may include" and names none
required, so an action without text is optional data, not a broken file. The
guide never describes a `<cdata>` **element** at all; where it says CDATA it
means an XML CDATA section, which is a different thing and is also in play here:
the two placements escape differently. In the measured corpus all 3,000 direct
summaries hold a CDATA section and all 984 wrapped ones hold entity references.
Both forms reach this reader as the same string, because the XML parser resolves
them and this source decodes nothing of its own, so the placement is the only
question and the escaping is not. The two causes needed two different answers.

**What changed.**

- `BillAction.text` is now `str | None`. The field is optional in the publisher's
  own statement, it is absent in real files, and refusing the whole document over
  it lost those bills entirely. Every other field of such an action survives. An
  action has two states, not three: a `<text>` that is present but blank reads as
  `None` too, so no caller has to tell an empty element from a missing one.
- A summary's `<text>` is read from the `<cdata>` wrapper when that is where the
  publisher put it. This is not an optional field: the text is present, so
  nulling it would have discarded real CRS summary text, and refusing would have
  discarded the bill. The placement is not recorded on `BillSummary`, because the
  value is the same either way and the original bytes remain the record of which
  shape arrived. A summary that states text in both places is refused, because
  nothing says which would win and no measured file does it.
- Every identity check is unchanged. Congress, type, number, the root element,
  the one-`<bill>` rule, the policy-area agreement check, the exactly-once XML
  link rule and the byte bounds all refuse exactly what they refused before.

**Counts, before and after.** Over all 1,566 files of the 119th H.Res. zip:

| | Parsed | Refused |
| --- | --- | --- |
| Before | 1,453 | 113 |
| After | 1,566 | 0 |

The other two types measured the same way: S.Res. 802 → 869 parsed of 869, H.R.
9,693 → 10,503 of 10,503. Across the three, 990 of 12,938 files (7.7%) were being
refused for these two shapes and now parse; no file that parsed before parses
differently.

**What the same measurement found next.** With those two shapes read, the
reader was run over 24 zips: every bill type of the 108th, 113th and 119th
Congresses, 131 MB and 40,260 members. Exactly one member refused,
`BILLSTATUS-113hr4200.xml`, and it is not a parser gap: that file is still
BILLSTATUS 1.0.0 -- `<billNumber>`, `<billType>` and `<version>` inside
`<bill>`, the schema the pinned user guide documents -- while every other file
in all three Congresses is 3.0.0. The refusal now names the schema instead of
reporting a missing `<type>`, and the folder's other 5,884 members are
unaffected. Whether to read 1.0.0 as well is a separate question, and one file
in 40,260 is the evidence for answering it.

| Congress | Zip bytes | Members | Parsed | Refused |
| --- | --- | --- | --- | --- |
| 108th | 39,149,459 | 10,667 | 10,667 | 0 |
| 113th | 39,664,054 | 10,637 | 10,636 | 1 |
| 119th | 52,236,275 | 18,956 | 18,956 | 0 |

**What this does not settle.** Decision 4 also covers `acquire_text`'s stricter
rules on the *text* side — the exactly-once XML link, the DC-title grammar and
the spelled-out Congress. Nothing here touches them; they need their own
measurement over bill text packages.

## Decision: the bulk listing is the freshness witness for a status zip

For a maintainer to move into [`docs/decisions.md`](../decisions.md).

The folder listing, not a cheaper request against the zip's own URL, is what a
caller asks whether a retained BILLSTATUS zip is still current. This
package's transport (`transport/capture.py`) has one request shape --
`capture()` streams a complete `GET` or `POST` body, never a header-only
`HEAD` -- so there is no existing primitive that would read the zip's own
`Last-Modified`/`Content-Length` without pulling every one of its bytes; the
zip's HTTP headers, whatever they state, are not cheaper to read than the zip
itself through this client. The folder's listing already states the same two
facts, `formattedLastModifiedTime` and `size`, as one entry among the files it
holds, at a fraction of the zip's own bytes (measured 2026-09-19: the 119th
H.R. listing is 3,744,366 bytes, 12%, against its 31,656,886-byte zip).
Reusing it, rather than adding a `HEAD` capability to the transport for this
one route, is the smaller change and the one already proven against this
publisher. `bulk_listing_locator`/`read_bulk_listing` read exactly that
listing and nothing more.

Skipping is a caller's choice, not the acquirer's. `BulkStatusAcquirer.acquire`
never skips unless handed an explicit `unchanged_since`, and the decision it
made — skipped or not — is recorded on the returned `BulkStatusAcquisition`
rather than hidden as a side effect: `skipped_unchanged` says which happened,
and `listing_capture`/`listing_entry` carry the evidence either way, so a
caller can audit *why* a run skipped a zip it needed, or retain the entry for
its own next run, without re-deriving either from a separate log.

Comparison is on the two typed, parsed facts (`modified_at`, an instant;
`size`, an int), not the publisher's raw strings, because "has this changed"
should never depend on two runs restringing the same instant identically.
Nothing about the zip's own bytes is trusted from the listing: a caller that
skips is trusting that the publisher's listing and the publisher's zip agree
with each other, the same trust an HTTP `If-Modified-Since` conditional
request already places in a publisher's own headers — this is not a new kind
of trust, just one this client has no cheap way to place directly against the
zip's own URL (see above).

Identity is checked before freshness: `unchanged_since` must name the same
file (`name` and `link`) the listing's own zip entry does before its
`modified_at`/`size` are compared at all, so a caller that mixes up which
retained entry belongs to which folder gets a refusal, never a skip that
happens to be right by accident. And the listing read never grants the zip a
second, independent `max_requests` — it spends from the one budget the call
was given, so `unchanged_since` cannot let one `acquire` call spend twice its
configured request ceiling merely by first asking a question about it.

## Source shapes and evidence

The members that carry both shapes are complete, unchanged publisher files in
[`tests/fixtures/govinfo_bills/README.md`](../../tests/fixtures/govinfo_bills/README.md),
with their digests and the digest of the zip they came from. Each was also
fetched from its own single-file locator and is byte-identical there, so the
archive member and the published file are one object. The zips themselves, the
per-type counts and the full measurement stay outside this repository.
