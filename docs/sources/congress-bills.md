# Fetch a bill and a specific text version

Give SpicyDocs a Congress number, bill type and bill number. It returns exact
GovInfo BILLSTATUS XML, useful source fields and every stated text-version link.
Select a package explicitly to fetch its XML text. No API key is required.

Install the `acquisition` extra. From this checkout, use
`uv sync --frozen --extra acquisition`, then run this with `uv run --frozen python`:

```python
from spicy_docs.sources.congress.bill_acquisition import BillAcquirer, BillAcquisitionBudget
from spicy_docs.sources.congress.bill_status import BillIdentity

budget = BillAcquisitionBudget(
    max_requests=3,
    max_status_bytes=8 * 1024**2,
    max_text_bytes=16 * 1024**2,
    timeout_seconds=60,
    min_request_interval_seconds=0.4,
)
with BillAcquirer(budget=budget) as source:
    status = source.acquire_status(BillIdentity(119, "hr", 6028))
    for version in status.status.text_versions:
        print(version.package_id, version.type, version.date)
    text = source.acquire_text(status, package_id="BILLS-119hr6028eh")

print(status.status.title)
print(text.identity.package_id, text.capture.sha256, text.capture.byte_size)
# Retain these exact bytes in caller-owned storage:
status_xml = status.capture.body
bill_xml = text.capture.body
```

The example names a particular bill/version; live availability can change.
`max_requests` includes retries and resets for each status or text call. Pacing
continues across both. `acquire_text(..., max_bytes=remaining_allowance)` can
narrow the text limit. Timeouts bound individual transport waits, not total time.

## What to retain

Each result includes the original response bytes, requested/resolved URL, HTTP
status, content type, observation time, computed SHA-256, byte count and request
count. Keep the status capture with the text capture: it records where the chosen
link came from. These operations return captures; they do not publish a release
or write a catalog. A hash checks retained bytes, not publisher authenticity.

Parsed status fields include title, source update dates, latest action, actions,
sponsors, the separate cosponsor list, policy area, subjects, summaries, text
versions/formats, the `<committeeReports>` citations and the `<cboCostEstimates>` items. Original
XML preserves fields outside this typed subset. Source strings and summary HTML
stay intact. A status update, summary action date, text version and acquisition
time describe different events.

`congress_bills.cosponsor_count` counts the entries in `<cosponsors>`, including
entries marked withdrawn. It is independent of `<sponsors>`. Parsed XML with
no listed entries yields zero; a caller-created status whose cosponsor list
was not examined yields NULL.

`<cboCostEstimates>` is the keyless route to CBO's cost-estimate index, whose
own site is walled ([routes](../research/cbo-cost-estimate-routes-2026-09-20.md)).
Read it as **requested-empty, never absence**: the publisher never emits the
element empty — zero of the 16,213 bills in the 118th's two bulk zips does — so
a bill without it is either never scored or not yet linked and nothing in this
route tells the two apart. The publisher's own user guide is stale on this
element, documenting `rptPubDate`/`rptTitle`/`rptUrl` and no description; the
live files state `pubDate`/`title`/`url`/`description`, which is what the
Congress.gov API serves. Both spellings are read, the live one first.

## Supported input and visible failures

- Status parsing checks the requested bill identity and supported XML shape.
  It reads BILLSTATUS 3.0.0 and the 1.0.0 schema the publisher's user guide
  documents; 1.0.0 lists recorded votes once for the bill rather than on their
  actions, so its actions carry none.
- Text acquisition requires that exact package's source-stated XML link. It
  rechecks the retained status bytes before fetching; edited status fields refuse.
- Current classic Congressional `bill` and `resolution` XML are supported. The
  validator checks native bill/Congress/version evidence and body structure.
  It does not validate the full publisher DTD or interpret legal requirements.
- External DTD declarations remain inert. Internal subsets and declared entities
  refuse; external resources are never loaded. Images and other linked resources
  remain outside the text capture.
- A complete 404/410 response raises `BillSourceUnavailableError` with its
  `capture`. It describes the requested locator, not every possible source.
- Credential refusals (401/403) abort immediately. Redirects, wrong identities,
  malformed XML, misleading media types, unsupported formats and empty bodies
  refuse. Transient failures retry within the request budget. No automatic HTML
  or PDF fallback occurs; their stated links remain available to callers.

Failures carry `bill_acquisition` context and, when available within bounds,
`refused_response` evidence. Failed/truncated streams never return successful
partial captures. A missing link does not establish publisher-wide absence.

## Use the same source in other products

SpicyRegs consumes validated policy-area/subject fields for its existing tables.
Its subject table does not retain the original XML. DocSpec owns catalog mapping,
version selection, injected fetchers, processors and later runs over retained
bytes. SpicyDocs has no runtime dependency on either product.

The upstream [Bill Status guide](https://github.com/usgpo/bill-status) describes
metadata and text links. [GPO's bulk-data guides](https://github.com/usgpo/bulk-data)
describe document formats and collection listings. They are reference material;
acquisition talks directly to GovInfo. This API accepts explicit bill IDs and
versions. To fill a whole Congress instead, use the
[bulk status route](congress-bulk-status.md), which takes one Congress and one
bill type per call and states its own crawl bound, and for the text of a whole
folder of printings, the [bulk bill text route](congress-bulk-bills.md) from the
113th Congress on; separate BILLSUM acquisition has separate scope and coverage
requirements. For CFR/eCFR, reuse the
[existing sibling implementations](../source-reference.md#cfr-metadata-and-separately-acquired-xml)
and qualify the selected source format before adding acquisition here.
