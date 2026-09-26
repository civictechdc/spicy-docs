# Read bill text in bulk, one Congress, session and bill type at a time

Give SpicyDocs a Congress, a session and one bill type. It returns that GovInfo
folder's listing and, when the caller asks, the folder's zip read once, keeping
the printings the caller names: each printing's exact XML bytes and digest, or
the reason that member was refused. No API key is required.

This is the bulk half of bill text, as [bulk status](congress-bulk-status.md) is
the bulk half of BILLSTATUS. [One printing at a time](congress-bills.md) stays
the route for a printing the bulk collection does not hold, which is every
printing before the 113th Congress.

| Route | Required selection | What it supplies |
| --- | --- | --- |
| Folder listing | Congress, session and one bill type | `bulkdata/json/BILLS/{congress}/{session}/{type}`: every printing the folder holds by file name, with its own stamp, size and media type, and the folder zip's entry |
| Folder archive | A listing | `bulkdata/BILLS/{congress}/{session}/{type}/BILLS-{congress}-{session}-{type}.zip`, read against that listing, member by member |

## The listing decides; the zip is read once

`BulkBillsAcquirer.list_folder` reads the listing. It answers what a caller needs
before it downloads anything:

- **Has the zip moved?** `zip_entry_unchanged(listing.zip_entry, retained)` is
  the same comparison the BILLSTATUS folders use: the same file by `name` and
  `link`, and the same `modified_at` and `size`.
- **Does it hold anything I need?** `listing.members` maps each printing's
  package id (`BILLS-119hr1ih`) to its entry. A caller whose pending printings
  are not named there has no reason to download the zip.

`BulkBillsAcquirer.acquire(listing, keep=...)` then downloads the zip once and
reads it with `read_bulk_bills_archive`, which also replays a retained zip and
listing offline. `keep` takes a package id; a member it declines is counted in
`skipped_count` and never decompressed, so a run after a handful of new
printings pays for their bytes, not the folder's.

## What each kept member is

Each kept member arrives in the publisher's order as a `BulkBillsMember` with
its name, package id, bill identity, byte size and SHA-256, and exactly one of
`body` or `refusal`. A member is read when:

- its name states a printing of the requested folder's Congress and bill type
  (a name that states none, or states another folder's, is refused whatever
  `keep` says);
- the listing names a file of that name, with the same byte count, as XML;
- its bytes are not GovInfo's error page.

Those are the per-package route's own checks -- identity by address, media type,
error page -- moved from the response onto the member. The per-package route
does not prove a printing's identity from its XML, and neither does this one: the
content-level `validate_bill_text` refuses about 8% of real printings (titles it
cannot read, `amendment-doc` roots; 3,383 of 3,600 pass in the 116th S. session-1
folder), so it would refuse printings the per-package route accepts.

`body` is a `BulkBillsBody`, the record a `BillVersionCapture.body` carries:
`requested_url`, `resolved_url` and `observed_at` are the zip's, because that is
the request that returned the bytes; `member` is the entry they were read from;
`content_type` is the listing's statement for the member, because a zip entry
carries none; `byte_size` and `sha256` are the member's own bytes.

The bytes are the per-package XML's: every member of the 119th H.R. zips equals
the `content/pkg/{id}/xml/{id}.xml` body captured for it, 3,516 of 3,516 by
SHA-256 (receipt `fork-execution-2026-09-21/bill-family-bulk-2026-09-26/partB/`
under `~/Work/corpora`).

## Coverage and cost

Measured 2026-09-26 from the publisher's listings:

| | 113th-119th Congresses |
| --- | --- |
| Folders | 112 (7 Congresses x 2 sessions x 8 types) |
| Printings | 135,395 |
| Zip bytes | 1,039,459,484 |
| Decoded bytes | 3,866,452,022 |
| Listing bytes | 46,246,397 |

The collection starts at the 113th Congress (`BULK_BILLS_FLOOR`). The largest
folder zip is 117/1/hr at 61,434,327 bytes, the most entries 8,043 (119/1/hr),
the largest decoded folder 228,149,005 bytes (116/2/hr) and the largest member
`BILLS-117hr7776eah.xml` at 10,421,178 bytes, all inside the `BulkArchiveBudget`
the BILLSTATUS folders use. The publisher rebuilds a current session's zips
about daily, and older ones occasionally (118/1/hr on 2026-07-10); the listing's
zip entry and the folder stamp its parent listing states moved together on every
119th folder checked.

A printing lives in the folder of the session it was printed in, so a bill
introduced in the first session and reported in the second has printings in
both (362 of the 119th's H.R. bills on 2026-09-26, with no printing in both
folders); a caller looking for a bill's printings reads both sessions' listings.
