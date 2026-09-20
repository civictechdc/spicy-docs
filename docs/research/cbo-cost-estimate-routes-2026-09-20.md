# Routes to CBO cost estimates that do not depend on beating the wall

**2026-09-20.** Measured. Receipt:
`~/Work/corpora/supply-2026-09-02/receipts/cbo-routes-2026-09-20/` — 130 logged
requests, 94 retained bodies, one sidecar per probe under `probes/`.

[The PDF-family rollup](pdf-family-rollup-yield-2026-09-20.md) recorded CBO as
the one family with *no* route: `0/8`, "blocked — not obtainable, even through a
paid proxy", and a build order whose last step was "build the feed-only link
table and stop there." That verdict was about `www.cbo.gov`'s document paths,
and it survives this note unchanged. What it did not ask is whether the content
is reachable somewhere that is not `www.cbo.gov`. It is.

**The finding.** Two keyless routes together supply the whole index and most of
the text, and neither touches a walled path. GovInfo's BILLSTATUS bulk zips
carry `<cboCostEstimates>` for every bill — **1,368 of the 118th's House and
Senate bills, 1,468 estimate rows, in two requests** — and GovInfo's `CRPT`
bodies reproduce the CBO letter verbatim for the reported subset. The wall now
costs us the cost *table image* and the estimates for bills that were never
reported, not the family.

---

## The ranked routes

| # | Route | What it states | Cost | Measured | Failure mode |
| --- | --- | --- | --- | --- | --- |
| **1** | **GovInfo BILLSTATUS bulk zip** — `www.govinfo.gov/bulkdata/BILLSTATUS/{congress}/{type}/BILLSTATUS-{congress}-{type}.zip` | Per estimate: `pubDate`, `title`, `url`, `description` (the scoring stage). Keyed to the bill by construction. | **Keyless.** 2 requests for the whole 118th House + Senate; 50 MB | 973 of 10,564 `hr` and 395 of 5,649 `s` bills carry the element; 1,468 estimate rows; 1,431 distinct publication ids; **all 1,468 urls are `/publication/{id}`**, none a PDF | The element is **never emitted empty**, so "no estimate" and "not yet linked" are the same bytes. No dollar figures. |
| **2** | **GovInfo `CRPT` report body** — `www.govinfo.gov/content/pkg/{pkg}/html/{pkg}.htm` and `/pdf/{pkg}.pdf` | The CBO letter **verbatim**: the narrative, the Director's signature, the named analysts, PAYGO and mandates statements — and, when the report does *not* carry it, a sentence saying why | **Keyless.** 1–2 requests per report | Of 15 sampled bill-accompanying reports, 10 carry a CBO section and **7 carry the statutory cover recital**; of those 7, 6 carry the Director's signature. Upper bound across the 118th: **883 of 1,368 scored bills (64.5%) have any committee report at all** | The summary cost table is a **raster PNG** (`[GRAPHIC(S) NOT AVAILABLE IN TIFF FORMAT]` in the HTM). Senate bills are often reported "without written report" — 155 of 395. |
| **3** | **Congress.gov API bill detail** — `api.congress.gov/v3/bill/{c}/{t}/{n}` | Identical to route 1, field for field | **Keyed** (`API_GOV`, header only). **1 request per bill** — O(bills) | 36 keyed requests over 35 bills; 23 carry ≥1 estimate; 28 estimate rows, every one `{description, pubDate, title, url}` and every url a publication page | Same absence ambiguity as route 1, at 5,000× the request cost for a Congress. |
| **4** | **CBO's own per-Congress feed** — `www.cbo.gov/rss/{congress}congress-cost-estimates.xml` | `Title`, `Date`, `Link`, `Description`, `Bill_Number` — CBO's own spelling of the bill, which routes 1 and 3 do not give | **Keyless**, 1 request per Congress; 2 here | `200`, 432,572 B (119th) and 560,335 B (118th) today; already the pinned route in [`sources/cbo.md`](../sources/cbo.md) | Not a catalog; item order unstable inside a `Date`; no figures. |
| **5** | **CBO's sitemap** — `www.cbo.gov/sitemap.xml` + `?page=1..14` | Every publication's canonical locator and its `lastmod` | **Keyless**, 9 requests (1 index + 8 of 14 children) | `200`; 14 children; 8 walked gave **15,301 distinct `/publication/` locators** plus 698 `/budget-options/`, each with `<lastmod>` | Names locators the wall then refuses. It enumerates; it does not deliver. |
| **6** | **Internet Archive CDX** — `web.archive.org/cdx/search/cdx` | Archived copies of the walled pages and PDFs | **Keyless** | **11,037 distinct `cbo.gov/system/files/*` PDFs with crawl status 200**, 2017–2026 (909 in 2025, 234 in 2026), 1,671 on the legacy `…/costestimate/…` path; and 14,669 archived `/publication/{id}` pages with a clean locator and status 200, but **2023: 11,743 → 2026: 29** | Coverage collapses for the current year. **Whether an archived page body is the estimate or an archived challenge could not be established** — all three replays hit IA's "Temporarily Offline" 503. |
| **7** | **Zyte, rendered, US exit** | — | **6 provider calls** | **0 documents.** 5 of 6 refused; the 6th was the unwalled feed control | Zyte's own error names it: `"title":"Website Ban"`. See below. |
| — | **`US-CBO` on GitHub, `cbo.gov/data`, JSON:API, third-party mirrors** | — | — | No cost-estimate dataset found in any of them | See *what could not be established*. |

### What would make each the production route

| # | What it needs before it ships | What would reverse a rejection |
| --- | --- | --- |
| 1 | A `bill ↔ cost_estimate` link contract keyed on `(congress, bill, publication_id)`, the zip's own `lastModified`/batch feed as the resume pin, and an explicit requested-empty column. Nothing else blocks it. | — it is the recommendation |
| 2 | A cover-recital gate (not a heading gate), the absence-reason sentence captured as a field, the PDF rendition preferred over the HTM, and the raster-card measurement in step 4 of the plan | — it is the recommendation for the reported subset |
| 3 | Nothing technical; it is simply 5,000× the requests of route 1 for the same fields. Keep it as the spot check. | A publisher change that puts a field in the API and not in the bulk XML |
| 4 | Already shipped in [`sources/cbo.md`](../sources/cbo.md); it needs the `publication_id` join to route 1 | — |
| 5 | Only useful once a document route exists; it names locators nothing can fetch | Any HTML path escaping the wall — re-probe on a CBO platform change |
| 6 | A measured replay: does an archived `/publication/{id}` body hold the estimate or an archived challenge? Plus a provenance rule saying the bytes are the archive's, not CBO's | A working IA replay endpoint. This is unmeasured, not rejected. |
| 7 | Rejected for now. | A new CBO host, a changed wall, or a provider capability that is not rendering — rendering with a US exit is now measured and negative |

---

---

## Route 1 — the bulk zip is the index the wall denies us, keyless

This is the result that changes the verdict, so it was checked against a
different route rather than against itself.

`<cboCostEstimates>` is in the BILLSTATUS XML with the same four children the
Congress.gov API documents — `pubDate`, `title`, `url`, `description` — and the
[BILLSTATUS user guide](https://github.com/usgpo/bill-status/blob/master/BILLSTATUS-XML_User_User-Guide.md)
is **stale on this element**: it documents `rptPubDate`/`rptTitle`/`rptUrl` and no
description. The live files disagree with the guide and agree with the API.
Code against the files.

Two zips, 118th House and Senate:

| Zip | Bills | With `cboCostEstimates` | Estimate rows | Distinct publication ids | `url` shapes |
| --- | --- | --- | --- | --- | --- |
| `118/hr` (35.5 MB) | 10,564 | 973 | 1,062 | 1,035 | 1,062 × publication page, 0 × PDF |
| `118/s` (14.4 MB) | 5,649 | 395 | 406 | 396 | 406 × publication page, 0 × PDF |
| **Both** | 16,213 | **1,368** | **1,468** | **1,431 (union)** | **1,468 × publication page, 0 × PDF** |

The 1,431 is a union taken across both zips, not a sum of the two rows, because
a publication id can score an `hr` and an `s` bill — CBO's own `description`
field says so ("As ordered reported by the Senate Committee…" on a House bill,
16 times in `118/hr`). It happens that no id is shared here, but the count was
re-derived as a union rather than left as an assumption
[`p9-report-number-verification.json`].

**The cross-check.** The 35 bills route 3 asked the keyed API about were looked
up inside the zips: 33 were present (the two absentees are `hres`, which are not
in the `hr`/`s` zips), and **all 33 url lists are identical**, including the
duplicate rows — `hr3091` carries `publication/59168` twice and `hr4688` carries
`publication/59718` twice in both routes. Zero disagreements.
[`p6b-api-vs-bulk-crosscheck.json`]

What this cannot see: only bills the keyed probe asked about are compared, so a
bill the zip carries and the API omits would not appear. The zip-side totals
above are the other direction and are reported separately, on purpose.

**The absence trap, stated plainly.** **Zero** of the 16,213 bills in the two
zips carries an empty `<cboCostEstimates/>` — the element is present only when
populated. So a bill without it is *either* never scored *or* not yet linked,
and **nothing in this route distinguishes the two.** Any contract built on it
must record requested-empty, never absence — and no count here is a CBO
production rate.

---

## Route 2 — the committee report reproduces the letter, and says so on its cover

House Rule XIII cl. 3(c)(3) requires a committee report on a reported measure to
include "an estimate and comparison prepared by the Director of the
Congressional Budget Office under section 402 of the Congressional Budget Act of
1974 **if timely submitted** to the committee before the filing of the report"
([House Rules and Manual, H. Doc. 117-161](https://www.govinfo.gov/content/pkg/CDOC-117hdoc161/html/CDOC-117hdoc161.htm)).
The Senate obligation is statutory rather than a standing rule — CBA §402,
[2 U.S.C. §653](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title2-section653),
renumbered from §403 in 1997, which is why live Senate reports still recite
"§403". Senate Rule XXVI ¶11(a) is a *committee-made* estimate, not CBO's.

**Do not key extraction on a heading.** Twenty CRPT packages were sampled
systematically from GovInfo's own `published` listing for the 118th — not from
anything CBO states, so the measurement cannot agree with itself — and the
headings are committee-specific: `Congressional Budget Office Estimate`,
`Congressional Budget Office Cost Estimate`, `Committee Cost Estimate`,
`ESTIMATED COSTS`, `1. Cost of Legislation and the Congressional Budget Act`.

**The reliable marker is the statutory cover recital**, identical in both
chambers and required by Rule XIII cl. 3(a)(1)(B):

```
                        [To accompany H.R. 801]

      [Including cost estimate of the Congressional Budget Office]
```

Measured over 17 bodies read (3 of 20 answered `302`), [`p2b-crpt-reanalysis.json`]:

| Signal | Count |
| --- | --- |
| Bodies read | 17 |
| Reports accompanying a bill | 15 |
| **Cover recital declares the estimate is included** | **7** |
| A CBO heading appears anywhere | 10 |
| Director's signature block | 7 |
| Named staff contact | 4 |
| Bodies with a dropped graphic | 12 |

The heading count (10) exceeds the cover count (7) because three reports carry
the heading over a section that then states the estimate was **not** received —
and that sentence is itself a record:

> "Pursuant to clause 3(d)(1) of rule XIII, the Committee adopts as its own the
> cost estimate prepared by the Director of the Congressional Budget Office
> pursuant to section 402 of the Congressional Budget Act of 1974. **At the time
> this report was filed, the estimate was not available.**" — `CRPT-118hrpt18`

> "**The Committee has requested but not received** from the Director of the
> Congressional Budget Office a statement as to whether this bill contains any
> new budget authority…" — `CRPT-118hrpt111`, a fourth such report the five
> committee-specific heading patterns did not count (its heading reads "C. Cost
> Estimate Prepared by the Congressional Budget Office"), so the heading count
> of 10 is a floor

That is requested-empty with the publisher's own reason attached, which is
better evidence than either index route can produce.

When the letter *is* there it is there whole, ending in the analyst attribution
and the signature:

> "…is Jeremy Crimm. The estimate was reviewed by Chad Chirico, Deputy Director
> of Budget Analysis.
>                                          Phillip L. Swagel,
>                              Director, Congressional Budget Office." — `CRPT-118hrpt53`

### The one thing the report loses: the summary table is a picture

This is the route's real limit, and it took reading the bytes two ways to see.

In the HTM rendition the CBO summary card is emitted as
`[GRAPHIC(S) NOT AVAILABLE IN TIFF FORMAT]` — 6 of the 7 cover-declared reports
drop a graphic inside the estimate span. The first PDF pass looked only at pages
whose *text* names the CBO heading, found no fiscal-year table band, and would
have concluded the numbers were gone. That check was one-directional: it could
not see a table on a page with no text layer, which is exactly what a scanned
table is. A full page walk of the four retained PDFs [`p2d`, `p2e`] found both
shapes:

| Package | Estimate-page image | Detailed table |
| --- | --- | --- |
| `CRPT-118hrpt53` | 1321 × 2221 PNG on a page with **192 characters** — a whole raster page | none in text |
| `CRPT-118hrpt276` | 1321 × 786 PNG | none in text |
| `CRPT-118hrpt930` | 1320 × 1441 PNG | **p6, 3,662 chars of real text** — `TABLE 1.—ESTIMATED BUDGETARY EFFECTS…`, `By fiscal year, millions of dollars—`, `Estimated Authorization`, `Estimated Outlays`, seven year columns |
| `CRPT-118srpt289` | 1321 × 844 PNG | **pp. 8–9, real text** |

So the **summary card** — the boxed "Direct spending / Revenues / Deficit" band
at the head of a CBO estimate — is a raster in both renditions, while the
**detailed effects table** is real text in the PDF *and* in the HTM for the
reports that print one. The rasters are 1320–1321 px wide, which is roughly 150
dpi at page width and well within what the repository's existing
[extraction API](../extraction/pdf-extraction-api.md) backends read; **that was
not attempted here** and is the obvious next measurement.

### The ceiling: how much of the corpus a report route can ever reach

Off the same two zips, zero extra requests [`p8-crpt-coverage-ceiling.json`]:

| | Bills with a CBO estimate | Of those, with a committee-report citation | Share | No report, action says "without written report" |
| --- | --- | --- | --- | --- |
| `118/hr` | 973 | 655 | 67.3% | 39 |
| `118/s` | 395 | 228 | 57.7% | 155 |
| **Both** | **1,368** | **883** | **64.5%** | 194 |

This is an **upper bound in both directions**: a report citation does not mean
the report reproduced the estimate (see the next section — 3 of the 10 whose index named an estimate did not), and
a citation can name a report for a different stage than the one the estimate
scores. The Senate shortfall is structural, not editorial: a Senate committee
may report a bill without a written report, and then no CRPT package exists.

The stage descriptions in the index say the same thing from the other side: of
the 118th House's 1,062 estimate rows, 826 are "As ordered reported by the House
Committee…" and 110 "As reported by the House Committee…", but the tail includes
"As introduced", "As passed by the House", and "As posted on the website of the
House Committee on Rules" — Rules Committee prints have no committee report at
all.

---

## Where the index and the text cover each other

The recommendation turns on this join, over the 13 non-resolution bills that
appear in both probes [`p7-index-vs-text.json`]:

| | Report carries the estimate | Report does not |
| --- | --- | --- |
| **Index names an estimate** | **7** | **3** |
| **Index names none** | **0** | 3 |

**`text-only` is zero.** On this sample the index never under-reports relative to
the report. The index is a superset; the text is prose the index lacks. Of the
three `index-only` bills, one report states its reason verbatim; of the three
`neither`, two do. Six of the seven `both` cells have a dropped graphic in the
estimate span, which is the raster-table limit again.

Thirteen bills is a sample, not a coverage claim, and a single Congress at that.

---

## Route 7 — Zyte, and a correction to what the last measurement established

The previous receipt recorded eight bare provider `520`s and concluded that
"none of the eleven is CBO refusing Zyte — what is established is that *this
proxy could not fetch these paths*." That was the most its evidence could
support: the probe logged `f"Zyte acquisition failed with HTTP {error.code}"`
and never read the provider's error body.

This probe reads it. Six calls, each with fields the product transport cannot
send — `geolocation: "US"`, a `sessionContext`, and `browserHtml` — and five of
the six answered:

```json
{"type":"/download/temporary-error","title":"Website Ban","status":520,
 "detail":"Zyte API could not get a ban-free response in a reasonable time."}
```

| Target | Fields | Result |
| --- | --- | --- |
| `/publication/62773` | `browserHtml` + `geolocation: US` | 520 Website Ban |
| `/publication/62720` | `browserHtml` + `geolocation: US` | 520 Website Ban |
| `/publication/62773` | `browserHtml` + `geolocation` + `sessionContext` | 520 Website Ban |
| `/publication/62720` | `httpResponseBody` + `geolocation: US` | 520 Website Ban |
| `/system/files/2020-07/HR1957directspending.pdf` | `httpResponseBody` + `geolocation: US` | 520 Website Ban |
| `/rss/119congress-cost-estimates.xml` (**control**) | `httpResponseBody` + `geolocation: US` | **200, 432,572 B, `sha256 2469d266…`** |

**The control is byte-identical to the keyless capture taken in the same session
— same digest, same length.** So the wiring is right and the five refusals are
about those paths. (That digest differs from the `910aab10…` pinned in the
earlier receipt at the same byte count; that is the known item-order instability
inside a shared `Date`, already documented in [`sources/cbo.md`](../sources/cbo.md),
and it is corroboration, not drift.)

**What this establishes and what it does not.** `Website Ban` is Zyte's
*classification* of its own ban-handling exhausting, not a publisher response
this probe retained: no CBO body came back at all. So this is still not CBO's
answer in the way the census's direct `403`s were. But it is a materially
different statement from "a bare 520 is the proxy's transport failing" — the
provider names the target's ban as the cause, with rendered mode and a US exit
already applied. **Rendering is not the missing ingredient.** Do not spend on
this proxy again without new evidence.

**Terms and robots.** `https://www.cbo.gov/robots.txt` answered `403` with the
767-byte DataDome challenge on 2026-09-20, as did `/about/copyright` and
`/data`. **No robots directive could be read and no CBO terms-of-use statement
could be obtained**, so none is assumed in either direction. The archive holds
120 `200` captures of that file but the oldest recoverable one is from 2001 and
the replay endpoint was offline. The only authoritative CBO reuse statement
found is `US-CBO/cbo-data`'s `LICENSE.md` — public domain under 17 U.S.C. §105,
worldwide IP waived — which covers those GitHub materials and is not established
to cover the estimate PDFs. **Any bulk route through this wall is the owner's
call, not this note's.** Six calls answered a capability question and nothing
more.

---

## The wall is path-scoped, and the sitemap proves the shape of it

Nineteen keyless requests to `www.cbo.gov` [`p3`, `p3b`]:

| Path | Status | Body |
| --- | --- | --- |
| `/sitemap.xml`, `?page=1..8` | `200` | Drupal `simple_sitemap`; 15,301 publication locators over 8 pages, each with `lastmod` |
| `/publications/all/rss.xml` | `200` | RSS 2.0, 14,318 B — a rolling window, not an archive |
| `/rss/119congress-cost-estimates.xml`, `/rss/118…` | `200` | 432,572 B / 560,335 B |
| `/robots.txt` | `403` | DataDome, 767 B |
| `/jsonapi`, `/jsonapi/node/publication` | `403` | DataDome, 767 B |
| `/cost-estimates`, `/about/copyright`, `/data` | `403` | DataDome, 767 B |
| `/publications/cost-estimates/rss.xml` | `404` | 26,789 B Drupal page — requested-empty, not a route |
| **`/publication/{id}/html`** ×3 | **`403`** | DataDome, 767 B |
| `/publication/{id}` ×3, `/node/{id}`, `/budget-options/2022` | `403` | DataDome, 767 B |

The sitemap states CBO's canonical locator as `/publication/{id}/**html**` — a
path shape no earlier probe had tried. It is walled identically. So is the
Drupal `/node/{id}` route. **XML answers; HTML does not.** The split is by route
handler, and no HTML path found so far escapes it.

---

## Recommended plan

1. **The index comes from the BILLSTATUS bulk zips, not the keyed API.** Two
   requests per Congress-and-type, keyless. GPO's own bulkdata README states a
   four-hourly refresh for the current Congress and a completion feed at
   `govinfo.gov/rss/billstatus-batch.xml`; that is the publisher's statement,
   not something this note measured. This is a
   `bill ↔ cost_estimate` link contract keyed on `(congress, bill, publication_id)`
   with `pubDate`, `title` and the stage `description` as columns. The keyed API
   stays the per-bill spot check and the disagreement detector, not the harvest.
2. **Join CBO's own per-Congress feed on `publication_id`** for `Bill_Number` —
   CBO's own spelling of the measure, which neither GovInfo route states — and
   for the spine. [`sources/cbo.md`](../sources/cbo.md) pins the 116th–119th;
   CBO states coverage back to the 105th and a single probe of
   `/rss/105congress-cost-estimates.xml` answered `200` with 865 items, which is
   one capture and not a route. That is the feed-only link table the rollup
   recommended, now with a second, keyless, *archival* publisher agreeing on
   every row.
3. **The text comes from `CRPT`, for the 64.5% of scored bills that have a
   report.** Gate the extraction on the **cover recital**, not on a heading, and
   record the report's own "not available" / "requested but not received"
   sentence as the absence reason when the recital is missing. Prefer the PDF
   rendition: it keeps the detailed effects table as text that the HTM sometimes
   drops.
4. **Measure the raster before promising figures.** The summary card is a
   1320-px PNG in both renditions. Run the existing extraction API over those
   embedded images on a bounded sample and report the recovered-figure rate
   before any contract claims to carry cost numbers.
5. **For the ~35% with no report — and for every current-year estimate — there
   is no text route.** State it. The link contract still carries the bill, the
   stage, the date and the locator for those rows; the figures are absent and
   recorded as absent. Under the retain-value rule this is a capability with a
   measured limit, not a gap to hide.
6. **Treat the Internet Archive as a backfill candidate, not a route, until the
   replay is measured.** 11,037 archived PDFs is a real number and the legacy
   `…/costestimate/…` path is 1,671 of them, but whether an archived
   `/publication/{id}` body is the estimate or an archived challenge is
   unestablished. One afternoon with IA up settles it.
7. **Do not spend on the proxy again** without new evidence — a new host, a
   changed wall, or a provider feature that is not rendering. Rendering with a
   US exit was the hypothesis and it is now measured and negative.
8. **Re-probe `/publication/{id}/html`, `/jsonapi` and `robots.txt` on any CBO
   platform change.** The XML/HTML split is a route-handler configuration, not a
   law; the day it moves, an HTML route may open.

---

## What could not be established

- **The heading-pattern set is a floor.** Five committee-specific heading
  patterns were matched; `CRPT-118hrpt111`'s heading matched none, so the
  heading count undercounts and a gate on headings would too. One more reason
  the gate is the cover recital.

- **Whether an archived CBO publication page replays as the estimate.** All
  three replay attempts and one CDX query hit the Internet Archive's
  "Temporarily Offline" `503`. A transport failure is not a record, so route 6's
  usability is **unmeasured**, not negative. The CDX index itself answered.
- **`robots.txt` and CBO's terms of use.** Both `403` behind the wall today; the
  archive's recoverable captures are from 2001. No directive is quoted here
  because none could be read, and none is assumed.
- **Whether the raster summary card is OCR-recoverable.** Not attempted. The
  images are 1320–1321 px wide PNGs; that is a measurement, not a guess to make.
- **Whether a CBO cost-estimate roll-up dataset exists.** None found in the 33
  repositories of [`US-CBO`](https://github.com/US-CBO) — `cbo-data` holds 13
  budget and economic datasets and no estimates — nor on Kaggle, Hugging Face,
  Zenodo or ICPSR. The pages that would say so (`/cost-estimates/faqs`,
  `/about/products`) are walled. Absence of search evidence is not evidence of
  absence.
- **Whether `/jsonapi/node/publication` exists behind the wall.** The sitemap
  proves the site is Drupal; the endpoint's `403` says nothing about whether the
  module is enabled.
- **ProPublica's July 2024 Congress API snapshot.** Its bill objects carried a
  `cbo_estimates` field; the API is retired and a partial archival snapshot is
  offered. Not checked, and route 1 makes it unnecessary except as an
  independent cross-check.
- **Whether the `200`s hold.** Every `www.cbo.gov` row is one request on one day
  from one host and one IP. A gated endpoint can change its answer to identical
  requests, and the earlier CRS "wall" that did not reproduce is the standing
  reminder.
- **Coverage beyond the 118th.** Every count here is 118th-Congress House and
  Senate bills, one sample of 20 reports and one of 35 bills.
- **One label in `p5-zyte-rendered-capability.json` is coarse:** the feed control
  is classified `estimate-page` because its bytes match the estimate-shape
  pattern. It is the feed, as its URL, byte count and digest show. The sidecar is
  left as the probe produced it.

## Request counts

| Class | Host | Requests |
| --- | --- | --- |
| keyed | `api.congress.gov` | 36 (cap 40) |
| keyed | `api.govinfo.gov` | 2 (cap 6) |
| keyless | `www.govinfo.gov` | 46 (caps 60 + 4 + 2) |
| keyless | `www.cbo.gov` | 27 (caps 24 + 10) |
| keyless | `web.archive.org` | 13 (caps 8+4, 4+2, 2+3) |
| zyte | `www.cbo.gov` | 6 (cap 6) |
| **Total** | | **130** |

No probe exceeded its stated cap. Both credentials were read through
`spicy_docs.transport.credentials.read_api_key` and sent as headers only;
`scrub_credential` ran over every recorded string before truncation, and a
literal search of the receipt and of `docs/` for both values returns no hits
(`verify_no_credentials.py` in the receipt).

## Sources

- [Congress.gov API bill endpoint documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/BillEndpoint.md)
- [BILLSTATUS XML user guide](https://github.com/usgpo/bill-status/blob/master/BILLSTATUS-XML_User_User-Guide.md) — stale on `cboCostEstimates`; the live files govern
- [GovInfo BILLSTATUS bulk data](https://www.govinfo.gov/bulkdata/BILLSTATUS)
- [House Rules and Manual, H. Doc. 117-161](https://www.govinfo.gov/content/pkg/CDOC-117hdoc161/html/CDOC-117hdoc161.htm) — Rule XIII cl. 3(a)(1)(B), 3(c)(3)
- [2 U.S.C. §653](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title2-section653) — CBA §402, formerly §403
- [Senate Manual, S. Doc. 113-1](https://www.govinfo.gov/content/pkg/CDOC-113sdoc1/html/CDOC-113sdoc1.htm) — Rule XXVI ¶11(a), the committee-made estimate
- [CBO's Cost Estimates Explained](https://www.govinfo.gov/content/pkg/GOVPUB-Y10-PURL-gpo138646/pdf/GOVPUB-Y10-PURL-gpo138646.pdf) — "most estimates are for bills that have been ordered reported by a full committee"
- [`US-CBO` on GitHub](https://github.com/US-CBO) and [`US-CBO/cbo-data`](https://github.com/US-CBO/cbo-data)
- [Zyte API ban responses](https://docs.zyte.com/zyte-api/usage/errors.html#ban-responses)
- This repository: [`sources/cbo.md`](../sources/cbo.md),
  [`transport/zyte.py`](../../src/spicy_docs/transport/zyte.py),
  [`pdf-family-rollup-yield-2026-09-20.md`](pdf-family-rollup-yield-2026-09-20.md),
  [`pdf-yield-mods-recheck-2026-09-20.md`](pdf-yield-mods-recheck-2026-09-20.md)
