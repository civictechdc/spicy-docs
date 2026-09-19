# GovInfo package bodies and acquisition

`GovInfoBodyAcquirer` fetches the body of one GovInfo package named by its
package id: a committee report, hearing transcript, Congressional Record issue,
congressional document, congressional directory or bill text. It reads the
package summary, then the package MODS, then the one rendition the publisher
says it offers, and returns exact bytes with every response that proved them.
Install `spicy-docs[acquisition]`.

This is a body fetch, not a crawl: the caller names the package. Discovery of
which packages exist stays with the [list routes](listings.md), and MODS field
meanings stay with the [MODS mapping](govinfo-metadata.md).

## Acquire a body

```python
from pathlib import Path

from spicy_docs.sources.govinfo.body_acquisition import GovInfoBodyAcquirer, GovInfoBodyBudget
from spicy_docs.transport.credentials import read_api_key

budget = GovInfoBodyBudget(
    max_requests=5,
    max_body_bytes=24 * 1024 * 1024,
    max_metadata_bytes=8 * 1024 * 1024,
    timeout_seconds=60,
    min_request_interval_seconds=0.5,
)
with GovInfoBodyAcquirer(budget=budget, api_key=read_api_key(Path(".env"), "API_GOV")) as client:
    result = client.acquire("CRPT-119hrpt1")  # prefer=("xml", "htm", "txt") is the default

body = result.body_capture.body
digest = result.body_capture.sha256
chosen, offered = result.format, result.offered_formats
```

`prefer` is a plain tuple of format names in the caller's order; the first one
the package offers is fetched. PDF is never fetched unless the caller names it,
because a hearing or directory PDF runs to tens of megabytes. `max_bytes` can
narrow the body allowance for one call, never raise it.

## Package ids

| Collection | Grammar | Example |
| --- | --- | --- |
| Committee reports | `CRPT-{congress}{hrpt\|srpt\|erpt}{number}` | `CRPT-119hrpt1` |
| Hearings | `CHRG-{congress}{hhrg\|shrg\|jhrg}{jacket}` | `CHRG-119hhrg64242` |
| Congressional documents | `CDOC-{congress}{hdoc\|sdoc\|tdoc}{number}` | `CDOC-119tdoc2` |
| Congressional Record | `CREC-{yyyy-mm-dd}` with optional `-v{volume}` or `-i{issue}` | `CREC-2019-01-03-v164` |
| Congressional Directory | `CDIR-{yyyy-mm-dd}` | `CDIR-2026-02-20` |
| Bill text | `BILLS-{congress}{type}{number}{version}` | `BILLS-119hr1enr` |

Congress.gov route URLs carry these ids as their file stems, so a caller
holding a route holds a package id. A Record date alone is not one: a single
date can publish two volumes, so the suffix belongs to the id and is never
inferred. Report and document numbers reject a leading zero; a hearing jacket
keeps the publisher's digits as printed. The bill-type vocabulary is the one
`sources/congress/bill_status.py` already states, imported rather than copied.

`parse_package_id` refuses anything else and names what it expected. That
includes real packages from neighboring collections that a collection-scoped
`published` walk returns anyway — `ERP-2009` states `collectionCode` `ERP` and
`GPO-J6-REPORT` states `GPO` (79 of 1,681 CDOC-scoped and 3 of 3,000
CRPT-scoped ids sampled on 2026-09-19). They have different addresses, so they
are refused rather than guessed at.

## Routes and credentials

| Request | Route | Credential |
| --- | --- | --- |
| Summary | `https://api.govinfo.gov/packages/{id}/summary` | `X-Api-Key` header |
| MODS | `https://api.govinfo.gov/packages/{id}/mods` | `X-Api-Key` header |
| Body | `https://www.govinfo.gov/content/pkg/{id}/{folder}/{id}.{extension}` | none |

The key travels in the header only, never in a URL, a request body or a
retained locator. The two routes use separate clients drawing on one request
budget: the keyed client retains no refusal body, because an api.data.gov error
can echo the key, while the keyless client retains its 401/403 body, because
there a refusal is a bot wall or an access-denied document — the publisher's
own answer. A keyed response containing the key is refused and not retained.

## Formats and how the offered set is read

| Format | Path | Media type |
| --- | --- | --- |
| `htm` | `html/{id}.htm` | `text/html` |
| `xml` | `xml/{id}.xml` | `application/xml`, `text/xml` |
| `txt` | `text/{id}.txt` | `text/plain` |
| `pdf` | `pdf/{id}.pdf` | `application/pdf` |

The folder is not the format name: text is served from `text/`, HTML from
`html/`. No package offers all four. The offered set is read from the package
MODS, from each `location/url` whose `access` is `raw object` and whose URL is
exactly this module's locator for a supported format. Measured 2026-09-19:

| Package | MODS says offered | Keyless routes answering 200 | Summary `download` body links |
| --- | --- | --- | --- |
| `CRPT-119hrpt1` | HTML, PDF | `htm`, `pdf` | none |
| `CHRG-119hhrg64242` | HTML, PDF | `htm`, `pdf` (46.6 MB) | none |
| `CDOC-119tdoc2` | HTML, PDF | `htm`, `pdf` | none |
| `CREC-2026-01-02` | PDF | `pdf` | four PDF links |
| `CDIR-2026-02-20` | PDF, Text | `pdf` (18.3 MB), `txt` | `txtLink`, `pdfLink` |
| `BILLS-119hr1enr` | HTML, PDF, XML, USLM | `htm`, `xml`, `pdf` | `xmlLink`, `txtLink`, `xhtmlLink`, `uslmLink`, `pdfLink` |

The MODS statement agreed exactly with what the routes served, in both
directions, for every package measured: each stated rendition answered 200 and
every unstated one redirected to the error page. The summary's `download`
block did not: it names no body rendition at all for CRPT, CHRG and CDOC,
which do serve HTML and PDF, and it spells the BILLS HTML rendition `txtLink`.
So the summary is read and kept — its `download_links` exactly as spelled, its
`dateIssued` and its `lastModified` are in the result — but nothing is derived
from those links and the offered set comes from MODS alone.

A stated rendition that is not one of these locators is separated by what it
means. `moved_renditions` holds `(format, url)` for a rendition of this
package in a supported file type at an address this module does not derive —
BILLS states its USLM rendition at `uslm/{id}.xml`, so that reads as `xml` in
a place this module does not fetch from, not as absence; fetching USLM is the
[USLM route's](uslm-laws.md) job. `other_renditions` holds `(displayLabel,
url)` verbatim for everything else: another package's address, another file
type, another host.

## Identity rules and why each exists

A GovInfo body carries no machine-readable package id — the CRPT-119hrpt1 HTML
body never spells `CRPT-119hrpt1` — so there is no equivalent of the Federal
Register granule's printed `[FR Doc No: ...]` marker to check. Identity is
instead four publisher statements about the one URL whose bytes were kept:

- **The summary states `packageId` and `collectionCode`.** They must equal the
  request. The summary route is also the only one that answers `404` for a
  missing package: the MODS route answers `400` and the body routes redirect.
  So it runs first, and a missing package is typed unavailable at once.
- **The MODS states `accessId`.** Every `accessId` under the package root's own
  `extension` children must equal the requested id; a constituent's `accessId`
  names a granule and is not read. This is the same rule the Federal Register
  granule route applies to its resolved `accessId`.
- **The MODS states the rendition URL.** The fetched locator must be one the
  MODS named as a `raw object` rendition of this package, so the address this
  module derives and the address the publisher publishes have to agree.
- **The response arrived at that locator.** Redirects are refused, so a 200 at
  this URL is this package's rendition or it is the error page.
- **It is not the error page.** A missing package or unoffered rendition
  redirects to `https://www.govinfo.gov/error`, which answers 200 with a
  44,165-byte "Page Not Found" page. The final URL and the `govinfo.gov/error`
  marker are both checked. This is one publisher rule with one home,
  `sources/govinfo/error_page.py`, which imports nothing from `spicy_docs` so
  a validator that needs only this rule need not import a source family. The
  two witnesses stay separable because callers interleave them differently:
  the Federal Register granule validator refuses an error-page URL, then a
  mismatched locator, then the marker, so a marker-bearing body at the wrong
  locator reports the locator. The page's byte length is its size today, not
  an identity rule.
- **The media type matches the format, the body is not empty, and a PDF begins
  with `%PDF-`.** A 200 that is not the requested format is a refusal with its
  bytes retained, never data and never absence.

## Bounds and measured basis

- Every summary, MODS, body request and retry spends the same `max_requests`.
  The two clients share it: whatever is left bounds the next call, including
  its retries. A skipped request is refused as `request-budget-exhausted`
  without implying a fetch was attempted.
- `max_body_bytes` and `max_metadata_bytes` must each be positive and at most
  24 MiB. Acquisition requests identity encoding, refuses other encodings,
  checks the stated length and bounds accumulated bytes through EOF. No partial
  body becomes evidence. Bodies above the bound refuse: the CHRG-119hhrg64242
  PDF (46.6 MB) is one, which is why the default preference is text-first.
- Transport failures and HTTP 429/5xx retry with bounded exponential backoff.
  Request-start pacing applies across retries and successive acquisitions, and
  meters the keyed and keyless hosts separately, as they answer separately;
  zero disables it. The timeout bounds transport waits, not total elapsed time.
  These caller settings are not GovInfo rate-policy claims.
- Use one client sequentially and close it. Injected HTTPX transports must
  preserve streaming and add no hidden requests or authentication.
- The measured basis for every rule above is recorded in
  `tests/fixtures/govinfo_bodies/README.md` with the routes, dates and digests.

## What each refusal means

| Refusal | Meaning |
| --- | --- |
| `GovInfoPackageUnavailableError` | The exact locator said the object is not there: 404/410 on a keyed route, or a redirect on a body route. It carries that capture. It is not a statement about other formats or other packages. |
| `GovInfoFormatNotOfferedError` | The package stated its renditions and none was preferred. It carries `offered_formats`; no body request was made. |
| `GovInfoBodySourceError` | Identity or shape failed: a `packageId`, `collectionCode` or `accessId` that differs, a final URL that differs, a wrong media type, an empty body, a PDF without its magic, or a bound exceeded. |
| `GovInfoRenditionAddressError` | The package states a preferred format at an address this module does not derive. The publisher's own URL is on the error. Disagreement, not absence; no body request was made. |
| `GovInfoBodySourceError` naming the error page | The publisher's error page arrived as a 200. Its bytes are retained; it is a refusal, never absence. |
| `CredentialRefusedError` | HTTP 401/403, or a keyed response echoing the key. Stop the operation; do not continue with another route or package. |

Every refusal attaches `refused_response` (`RefusedResponse`) with the exact
bytes where they exist, and `govinfo_body_acquisition` with the package id,
collection, stage (`summary`, `mods` or `body`), preference, offered formats,
chosen format, consumed requests and effective budget. The context names the
active offending response: a failed body never labels the earlier successful
MODS as the refused one. A refusal returns no partial result.

## Result

`GovInfoPackageBody` is frozen and holds the parsed `identity`, the `format`
chosen, the `preference` asked for, `offered_formats`, the validated `summary`
(with its `download_links` as evidence), the validated `mods` (with
`moved_renditions` and `other_renditions`) and `body` identities, the three
captures in request order, the consumed `request_count` and the effective
`budget`. Each capture carries its requested
and final URL, status, content type, observation time, exact bytes, byte size
and qualified SHA-256. To store one, pass its `sha256`, `byte_size` and
`[body]` to `SourceNativeBlobStore.put_blob` and keep the source facts beside
the returned reference.

