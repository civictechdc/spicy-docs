# BillTrax raw data: what the publishers actually serve

Measured 2026-09-19 against spicy-docs `ee65b33` and BillTrax read-only.
Companion sidecar: [`billtrax-raw-data-2026-09-19.json`](billtrax-raw-data-2026-09-19.json).
This extends the [legislative data map](legislative-data-map-2026-09-18.md) —
it does not repeat coverage, freshness, bulk sizes, the route comparisons or
the flow edges measured there. It measures the *bytes* the
[port plan](billtrax-port-2026-09-15.md) will move: the bill-text version
vocabulary and size distribution, the XML the tree parser must read, the bill
PDFs, the press-release feeds, the roll-call references, and the committee
report text the agency-block parser is fed.

**Scope and budget.** 278 requests: 163 keyless (GovInfo bulkdata JSON and
content, the two committee sites), 64 keyed GovInfo (`X-Api-Key` header only,
never a URL), 49 keyed Congress.gov, 2 exploratory `curl` probes of the
bulkdata listing shape. Every bounded request went through `SourceAcquirer`
subclasses built on `BoundedHttpCapture` (the `KeylessProbe` shape from
`tools/analysis/legislative_data_map.py`), paced at 0.35 s, bounded at 24 MiB
for bodies. The credential was read only with
`read_api_key(Path(".env"), "API_GOV")`; the sidecar was checked for the literal
key, for `api_key=` and for the header name before it was written, and carries
none of them.

**What this cannot see.** One Congress (the 119th) and one collection (BILLS)
for the version census; 40 XML files and 15 packages for the structural and
PDF samples, chosen to span type and size but not weighted by population; the
Senate feed at one instant. Everything below is a statement about what the
publisher served on 2026-09-19, not a guarantee about the 118th or the 120th.
Where a number is a publisher *statement* rather than a measurement it says so.

---

## 1. Bill text XML by version code: the publisher's real vocabulary

Source: `bulkdata/json/BILLS/119/{session}/{type}`, 19 listings, all entries.
**21,963 entries: 21,947 XML files totalling 490,796,565 bytes, plus 16 per-session
ZIPs; 629,046,400 bytes for the folder as listed.**
The API version name in column 2 came from `/bill/119/{type}/{n}/text` for the
smallest file carrying each code (24 requests), so the code→name map is the
publisher's own in both directions.

| code | Congress.gov `type` | files | min | median | p90 | max | largest file | BillTrax slug map | `version-kind.ts` verdict |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| ih | Introduced in House | 12,092 | 1,978 | 7,675 | 28,073 | 1,955,605 | `BILLS-119hr8870ih.xml` | yes | full_text |
| is | Introduced in Senate | 6,054 | 1,330 | 9,709 | 39,088 | 3,565,514 | `BILLS-119s5066is.xml` | yes | full_text |
| eh | Engrossed in House | 931 | 1,899 | 6,629 | 23,596 | 6,716,607 | `BILLS-119hr8800eh.xml` | yes | full_text |
| rh | Reported in House | 808 | 2,282 | 9,085 | 32,521 | 4,946,603 | `BILLS-119hr8800rh.xml` | yes | full_text |
| **rfs** | Referred in Senate | **568** | 2,354 | 7,057 | 21,489 | 967,494 | `BILLS-119hr4275rfs.xml` | **no** | full_text |
| rs | Reported to Senate | 444 | 2,593 | 15,262 | 81,022 | 4,813,567 | `BILLS-119s4784rs.xml` | yes | full_text |
| **ats** | Agreed to Senate | **431** | 1,835 | 6,076 | 11,312 | 92,203 | `BILLS-119sres94ats.xml` | **no** | full_text |
| es | Engrossed in Senate | 209 | 2,137 | 10,398 | 43,073 | 8,957,662 | `BILLS-119s2296es.xml` | yes | full_text |
| pcs | Placed on Calendar Senate | 183 | 2,262 | 6,009 | 175,385 | 2,643,986 | `BILLS-119hr7148pcs.xml` | yes | full_text |
| enr | Enrolled Bill | 145 | 2,360 | 5,544 | 104,427 | 9,359,354 | `BILLS-119s1071enr.xml` | yes | full_text |
| rds | Received in Senate | 32 | 2,256 | 3,065 | 11,675 | 34,411 | `BILLS-119hr4323rds.xml` | yes (as a code) | **unknown — size heuristic** |
| **cps** | Considered and Passed Senate | 16 | 2,078 | 6,663 | 30,975 | 76,295 | `BILLS-119s3971cps.xml` | **no** | full_text |
| eas | Engrossed Amendment Senate | 11 | 5,675 | 177,045 | 749,413 | 1,773,496 | `BILLS-119hr1eas.xml` | yes | procedural_amendments |
| eah | Engrossed Amendment House | 7 | 4,900 | 31,282 | 561,415 | 8,167,190 | `BILLS-119s1071eah.xml` | yes | procedural_amendments |
| rfh | Referred in House | 4 | 7,583 | 11,660 | 20,749 | 20,749 | `BILLS-119s1051rfh.xml` | yes | full_text |
| **rcs** | Reference Change Senate | 3 | 3,579 | 6,505 | 77,692 | 77,692 | `BILLS-119s350rcs.xml` | **no** | full_text |
| **rhuc** | Returned to the House by Unanimous Consent | 2 | 6,186 | 33,446 | 60,706 | 60,706 | `BILLS-119hr1834rhuc.xml` | **maps to `rfh` — wrong** | full_text |
| **as** | Amendment Ordered to be Printed (Senate) | 1 | 6,768 | 6,768 | 6,768 | 6,768 | `BILLS-119sres178as.xml` | **no** | procedural_amendments (name heuristic) |
| **cdh** | Committee Discharged House | 1 | 3,885 | 3,885 | 3,885 | 3,885 | `BILLS-119hr9238cdh.xml` | **no** | **unknown — size heuristic** |
| **eas2** | Engrossed Amendment Senate | 1 | 680,326 | — | — | 680,326 | `BILLS-119hr6644eas2.xml` | **maps to `eas` — wrong document** | procedural_amendments |
| **eh1s** | Engrossed in House | 1 | 6,691 | — | — | 6,691 | `BILLS-119hr3426eh1s.xml` | **maps to `eh` — wrong document** | full_text |
| **lth** | Laid on Table in House | 1 | 7,149 | — | — | 7,149 | `BILLS-119hres537lth.xml` | **no** | **unknown — size heuristic** |
| **rfs2** | Referred in Senate | 1 | 7,367 | — | — | 7,367 | `BILLS-119hr3426rfs2.xml` | **no** | full_text |
| **ris** | Referral Instructions Senate | 1 | 27,080 | — | — | 27,080 | `BILLS-119s1602ris.xml` | **no** | **unknown — size heuristic** |

Files by folder type: hr 12,534 · s 5,997 · hres 1,669 · sjres 296 · hjres 280 ·
sres 945 · hconres 170 · sconres 56 (plus one ZIP per type per session).

**Measured drift, both directions.** The publisher used **24** version codes in
the 119th. BillTrax's canonical slug map (`govinfo-pdf-fetch.ts:26-58`) reaches
**12** of them correctly. Twelve codes have no short-code entry — `as`, `ats`,
`cdh`, `cps`, `eas2`, `eh1s`, `lth`, `rcs`, `rfs`, `rfs2`, `rhuc`, `ris` —
covering **1,027 files (4.7 %)**, of which `rfs` alone is 568. Three codes map
to the *wrong* code through the long-name path: `rhuc` →`rfh` (a plain error),
and `eas2`/`eh1s` → `eas`/`eh` because the Congress.gov `type` string is
**identical for a version and its numbered reprint** — "Engrossed Amendment
Senate" names both `eas` and `eas2`. A slug derived from the type name
therefore cannot address the reprint, and the built URL fetches the earlier
document with no error. The other direction: BillTrax carries `pch` and `hds`,
which the publisher did not use once in the 119th. `version-kind.ts` misses
five of the 24 (`as`, `cdh`, `lth`, `rds`, `ris`); `cdh` misses only because
BillTrax spells it `committee-discharge-house` while the publisher says
"Committee Discharged House". It carries 29 slugs the 119th never produced.

**Three publisher spellings, one code.** The document states its own version a
third way, on the root element: `@bill-stage="Introduced-in-House"`,
`@resolution-stage="Agreed-to-Senate"`. For `rs` the XML says
`Reported-in-Senate` while the API says "Reported to Senate" — which is why
BillTrax's slug map keys `reported-in-senate` (the document's spelling) and
`version-kind.ts` keys `reported-to-senate` (the API's), and both are right
about different sources. For `rds` the API says "Received in Senate" and
BillTrax's map keys `referred-to-senate`, which matches neither. A port that
keys on the code, not on any name, is immune to all three.

**Consequence for the port.** The version vocabulary is a *publisher* fact and
must be captured from the package id, never re-derived from a display name: the
sealed identity is the code in `BILLS-119hr6644eas2`, and the name
"Engrossed Amendment Senate" is a non-unique label. The port should carry the
code verbatim into the manifest (the port contract already names `version_code`
as keyed into BillTrax SQL), treat an unknown code as data rather than a gap,
and derive any kind classification from a table keyed on the code, with the
name kept only as evidence. Acquisition bounds: one Congress of BILLS XML is
21,947 files and 491 MB (median 8,129 bytes, p90 32,277, p99 211,689), but the
tail reaches 9.36 MB — a
per-file bound below 16 MiB would refuse real documents, so 24 MiB is the right
evidence bound and the crawl bound is a Congress-and-type pair, as the families
record already settled for status. Two ZIPs per type sit in the same folder as
the XML and must be filtered by name, not assumed away.

---

## 2. Bill XML structure: what the tree parser will meet

40 files, five per bill type (smallest, lower quartile, median, p90, largest),
all fetched keyless from bulkdata and parsed with
`spicy_docs.reading.xml.parse_xml(..., allow_external_doctype=True)`.

| fact | result |
|---|---|
| root element / DOCTYPE name | `bill` 10 · `resolution` 29 · `amendment-doc` 1 (root tag equals DOCTYPE name in every file) |
| DOCTYPE identifiers | 40/40 carry both: PUBLIC `-//US Congress//DTDs/{bill,res,amend}.dtd//EN` and a **relative** SYSTEM id (`bill.dtd` 10, `res.dtd` 29, `amend.dtd` 1) |
| version stated on the root element | `@bill-stage` 10 · `@resolution-stage` 29 · absent on `amendment-doc` — values like `Introduced-in-House`, `Agreed-to-Senate` |
| other root attributes | bill: `bill-stage`, `bill-type`, `dms-id`, `key`, `public-private`; resolution: `resolution-stage`, `resolution-type`, `star-print`, `dms-id`, `public-private` |
| `<?xml-stylesheet ?>` | 40/40 |
| `<![CDATA[` | 0/40 |
| BOM (`EF BB BF`) | 0/40 |
| `\ufeff` anywhere in the body | 0/40 |
| body element | `legis-body` 10 · `resolution-body` 29 · none 1 (`amendment-doc`) |
| `findBillBody` / `find_bill_body` succeeds | **11/40** |
| distinct elements, union of the sample | **100** |
| distinct elements per file | 19 (smallest `is`) … 72 (`BILLS-119hr8800eh`) |

Elements the two tree parsers name, and where they appear (files out of 10
`bill`, 29 `resolution`, 1 `amendment-doc`):

| element | total occurrences | bill | resolution | amendment-doc |
|---|---:|---:|---:|---:|
| `enum` | 41,178 | 10 | 23 | 1 |
| `text` | 37,362 | 10 | 29 | 1 |
| `header` | 14,879 | 10 | 10 | 1 |
| `paragraph` | 14,836 | 6 | 15 | 1 |
| `subsection` | 7,213 | 8 | 7 | 1 |
| `section` | 2,905 | 10 | 29 | 1 |
| `quoted-block` | 1,356 | 4 | 3 | 0 |
| `subtitle` | 241 | 2 | 2 | 1 |
| `title` | 142 | 3 | 4 | 1 |
| `toc` | 134 | 2 | 4 | 1 |
| `subchapter` | 29 | 2 | 1 | 0 |
| `chapter` | 23 | 2 | 0 | 0 |
| `division` | 13 | 2 | 0 | 0 |
| `legis-body` | 10 | 10 | 0 | 0 |
| `resolution-body` | 29 | 0 | 29 | 0 |
| `appropriations-major` / `-intermediate` / `-small` | 8 / 6 / 5 | 0 | 1 | 0 |
| `part` / `subpart` | 1 / 1 | 1 | 0 | 0 |
| `amendment` · `amendment-block` · `engrossed-amendment-body` | 1 each | 0 | 0 | 1 |

**The decisive fact for decision 7.** Every one of the 29 resolution files in
the sample carries `resolution-body` and **no** `legis-body`, so
`bill-tree.ts:90-101` and `bill_tree.py:find_bill_body` throw on all of them and
fall back to `normalizeBodyText` over plain text. Resolutions are **3,416 of the
21,947 XML files in the 119th (15.6 %)** — H.Res., S.Res., H.J.Res., S.J.Res.,
H.Con.Res. and S.Con.Res. — and they are structurally ordinary: the largest,
`BILLS-119hres1299ih.xml`, holds 67 sections, 245 subsections, 12 titles, 90
quoted blocks and a `toc`. The appropriations-specific elements appeared in a
*resolution* (`BILLS-119hjres143ih.xml`, a joint resolution making continuing
appropriations, 8 `appropriations-major`, 6 `-intermediate`, 5 `-small`), not in
any bill in the sample, so the appropriations walker — the reason `bill_tree.py`
exists — is reachable in this sample only through `resolution-body`. Resolutions
also introduce `preamble` (10 files) and `whereas` (176 occurrences in 10 files),
which neither parser names.

**Field set the publisher offers versus what BillTrax reads.** The two parsers
between them name 18 elements. The union of the sample is **100**, so **82
elements are discarded** — including everything that carries the document's
own identity (`congress`, `session`, `legis-num`, `legis-type`,
`current-chamber`, `official-title`, `short-title`, the whole `dublinCore`
block, 39/40 files each), its provenance (`sponsor` 32, `cosponsor` 86,
`committee-name` 94, `action`/`action-date`/`action-desc`, `calendar`,
`associated-doc`, `distribution-code`), its cross-references
(`external-xref` 2,704, `internal-xref` 72, `term` 1,425), and all table markup
(`table`, `tgroup`, `thead`, `tbody`, `row`, `entry` 37,829 occurrences,
`colspec`, `ttitle`). The full per-element counts and the per-element attribute
inventory are in the sidecar under `sources.billXmlStructure`.

**Consequence for the port.** The tree extractor must accept `resolution-body`
as a body — refusing it discards a sixth of the corpus and, with it, the only
appropriations-structured document in the sample. Bound the parse at 24 MiB
with a depth limit (the deepest file nests to `subclause`), and refuse the external
DTD (every file names a *relative* SYSTEM id — `bill.dtd` beside the document —
so a resolving parser would issue an unbudgeted request per file;
`parse_xml(..., allow_external_doctype=True)` accepts the declaration without
fetching it, which is exactly the needed behavior), and stop carrying the CDATA and BOM special cases as *expected*
shapes — neither occurred once; keep them as tolerances, not as branches with
behavior the goldens assert. Most importantly, the capture must retain the whole
document, not the 18 elements the tree walks: identity, sponsors, committees,
cross-references and tables are all in the bytes today and all thrown away, and
re-deriving them later means re-fetching 491 MB.

---

## 3. Bill PDFs

15 packages spanning the size-ordered XML sample, each through
`package_summary_locator` and `package_mods_locator` (keyed) then the keyless
`package_body_locator(..., "pdf")`, bounded at 24 MiB. A second, small-end
sample of 15 is in the sidecar.

| package | XML bytes | PDF bytes | pages (summary) | pages (MODS `extent`) | pages (decoded) | magic | `%%EOF` |
|---|---:|---:|---:|---|---:|---|---|
| `BILLS-119hconres11eh` | 2,177 | 112,378 | 4 | 4 p. | 4 | `%PDF-1.5` | yes |
| `BILLS-119s515is` | 1,330 | 223,358 | 1 | 1 p. | 1 | `%PDF-1.4` | yes |
| `BILLS-119hr4727ih` | 1,978 | 223,439 | 1 | 1 p. | 1 | `%PDF-1.4` | yes |
| `BILLS-119hres426rh` | 6,514 | 228,624 | 4 | 4 p. | 4 | `%PDF-1.4` | yes |
| `BILLS-119hjres174ih` | 3,027 | 243,057 | 2 | 2 p. | 2 | `%PDF-1.4` | yes |
| `BILLS-119sjres141is` | 2,671 | 243,243 | 2 | 2 p. | 2 | `%PDF-1.4` | yes |
| `BILLS-119sres660ats` | 5,017 | 244,650 | 3 | 3 p. | 3 | `%PDF-1.4` | yes |
| `BILLS-119sjres104is` | 6,035 | 245,976 | 4 | 4 p. | 4 | `%PDF-1.4` | yes |
| `BILLS-119hr9499rh` | 4,856 | 247,316 | 4 | 4 p. | 4 | `%PDF-1.4` | yes |
| `BILLS-119s218is` | 11,044 | 249,002 | 5 | 5 p. | 5 | `%PDF-1.4` | yes |
| `BILLS-119hconres26ih` | 16,580 | 255,446 | 10 | 10 p. | 10 | `%PDF-1.4` | yes |
| `BILLS-119s3612is` | 46,148 | 277,605 | 24 | 24 p. | 24 | `%PDF-1.4` | yes |
| `BILLS-119sres94rs` | 92,292 | 307,436 | 54 | 54 p. | 54 | `%PDF-1.4` | yes |
| `BILLS-119sconres39pcs` | 216,526 | 307,812 | 70 | 70 p. | 70 | `%PDF-1.4` | yes |
| `BILLS-119s1071enr` | 9,359,354 | 4,772,801 | 1,259 | 1,259 p. | 1,259 | `%PDF-1.5` | yes |

Distribution: min 112,378 · median 245,976 · p90 307,812 · max 4,772,801 bytes.
**0 of 15 exceeded the 24 MiB evidence bound**, and the largest is 19 % of it.
Every body answered `Content-Type: application/pdf`, started `%PDF-`, and ended
`%%EOF`.

**What the publisher states, and what it does not.** Neither the summary JSON
(59 field paths) nor the MODS (59 distinct elements) states a byte size
anywhere — the only size-like statements are the summary's `pages` integer and
the MODS `physicalDescription/extent` string, and those two agreed with each
other and with a pymupdf decode on **15/15**. So the byte size in the table is
measured, not quoted; a port that wants to bound a fetch before making it has
only the page count to go on, and pages do not predict bytes: the 4-page
`BILLS-119hconres11eh` (112,378 bytes, `%PDF-1.5`) is *smaller* than the 1-page
`BILLS-119s515is` (223,358 bytes, `%PDF-1.4`), because a GPO bill PDF carries a
roughly 220 KB floor of embedded fonts and the two producers differ. Only
beyond ~50 pages does size track length.
The MODS states the offered renditions as `location/url access="raw object"`
(HTML, PDF, XML for BILLS), which is what `bodies.py` already reads; the summary
`download` block spells the HTML rendition `txtLink` and points at
`api.govinfo.gov`, a different host from the one the bytes come from.

**Fields BillTrax ignores.** `govinfo-pdf-fetch.ts` reads no publisher metadata
at all: it builds a URL from a slug, downloads, and persists text. The summary's
61 other fields — `members[]` with bioguide ids, `committees[]` with authority
ids, `references[]` to the U.S. Code sections the bill touches,
`isAppropriation`, `suDocClassNumber`, `governmentAuthor1/2`, `lastModified`,
`otherIdentifier.*` — and the MODS's `congMember`, `congCommittee`,
`classification`, `USCode`, `searchTitle`, `recordChangeDate` are all in the two
documents the fetch already pays for. Full lists in the sidecar under
`fieldInventories`.

**Consequence for the port.** Decision 1 (PDF success semantics) can be settled
on measured ground: content type plus `%PDF-` magic plus a `%%EOF` trailer plus
the MODS `raw object` rendition URL plus the page count stated twice and
decodable — five publisher statements about one URL, which is stronger than the
FEC `download.py` precedent and needs no structural identity proof. Bound bodies
at 24 MiB and record the refusal when a body exceeds it rather than raising the
bound. And since the summary and MODS are fetched anyway to prove the rendition,
the capture should keep them whole: BillTrax's PDF row today carries less
metadata than the two requests that produced it already returned.

---

## 4. Press-release feeds: all four BillTrax spellings are dead

| spelling | where it lives in BillTrax | status | content type | bytes | verdict |
|---|---|---|---|---:|---|
| `appropriations.house.gov/news/press-releases.rss` | `press-releases.ts:6` (lib) | **404** | `text/html` | — | gone |
| `appropriations.house.gov/rss/` | `sync-press-releases.ts:20` (script) | **404** | `text/html` | — | gone |
| `www.appropriations.senate.gov/news/press-releases.rss` | `press-releases.ts:10` (lib) | **410 Gone** | `text/html` | — | gone |
| `www.appropriations.senate.gov/rss/` | `sync-press-releases.ts:24` (script) | **200** | `text/html` | 606 | ColdFusion error page — a 200 that is not the object |
| `appropriations.house.gov/rss.xml` | — (the site's own link) | 200 | `application/rss+xml` | 13,808 | **canonical, House** |
| `www.appropriations.senate.gov/rss/feeds/?type=press` | — (the CMS route) | 200 | `text/xml` | 9,011 | **canonical, Senate** |
| `www.appropriations.senate.gov/rss/feeds/?type=allitems` | — | 200 | `text/xml` | 9,005 | same items, different channel title |

Neither site declares a feed with `<link rel="alternate">`. The House URL is the
only RSS-like `href` on `appropriations.house.gov/` and on its `/news` page;
the Senate declares nothing at all, and its feed lives at the senate.gov CMS
route, found by probing that CMS's known shape.

| fact | House `rss.xml` | Senate `rss/feeds/` |
|---|---|---|
| root element / namespace | `rss`, **no namespace**, `version="2.0"` | `rss`, **no namespace**, `version="2.0"` |
| dialect | RSS 2.0 (never Atom) | RSS 2.0 (never Atom) |
| items | 10 | 15 |
| channel fields | `title`, `link`, `description`, `language` | `title`, `link`, `description`, `language`, `copyright`, `docs`, `lastBuildDate`, `ttl`, `skipDays`, `skipHours` |
| item fields | `title`, `link`, `description`, `pubDate`, `dc:creator`, `guid` | `title`, `link`, `author`, `pubDate`, `guid` — **no `description`** |
| GUID | yes, `isPermaLink="false"`, value `"14637 at http://appropriations.house.gov"` — not a URL | yes, no attributes, value **identical to `<link>`** |
| date format | RFC 822 with offset: `Wed, 16 Sep 2026 14:04:21 +0000` | RFC 822 with abbreviation: `Wed, 16 Sep 2026 11:11:00 EST` — **"EST" in September** |
| link scheme | `http://` (not https) | `http://` (not https) |
| CDATA / BOM / stylesheet | none | none |

The Senate `?type=` parameter changes the channel title and, for some values,
the item set; `?type=nonexistenttype` returns **byte-identical** content to
`?type=majority` and `?type=minority` (`sha256:999e9250…`), so a misspelled type
answers 200 with a default feed rather than failing.

**Consequence for the port.** Decision 5 has no answer among the four spellings
BillTrax holds — the correct ruling is that **both are wrong and both must be
replaced**, with the canonical pair above, and the 410 recorded as the
publisher's own statement that the old Senate address is permanently gone. The
RSS source must treat a 200 with `text/html` as a refusal with its bytes
retained (the `/rss/` ColdFusion page is exactly the "200 that is not the
requested object" shape `bodies.py` already documents for GovInfo), must not
look for Atom (neither publisher serves it, so the single-item-Atom crash in
`press-releases.ts:102` is a bug against a dialect that does not exist here —
fix the list-collapse anyway, since fast-xml-parser collapses a one-item
`<item>` list on RSS too), and must tolerate a Senate item with no
`<description>` at all, which makes BillTrax's `excerpt` permanently empty on
that feed and silently reduces `matchReleasesToBills` to title-only matching.
Capture the fields BillTrax drops: `dc:creator` is a named staffer's mail.house.gov
address, `guid` is not a URL on the House feed, and the Senate's `ttl`,
`skipDays`, `skipHours` and `lastBuildDate` are the publisher's own polling
contract.

---

## 5. Roll-call references on bill actions

20 bills drawn from `/house-vote/119?limit=250`, then `/bill/119/{type}/{n}/actions`
for each. **58 `recordedVotes` entries across 58 voted actions — exactly one per action.**

| `recordedVotes` field | present | example |
|---|---:|---|
| `chamber` | 58/58 | `"House"` / `"Senate"` |
| `congress` | 58/58 | `119` |
| `date` | 58/58 | `"2025-09-08T22:56:43Z"` |
| `rollNumber` | 58/58 | `240` |
| `sessionNumber` | 58/58 | `1` |
| `url` | 58/58 | `https://clerk.house.gov/evs/2025/roll240.xml` |

| URL host | entries |
|---|---:|
| `clerk.house.gov` (`/evs/{year}/roll{NNN}.xml`) | 49 |
| `www.senate.gov` (`/legislative/LIS/roll_call_votes/vote{CCC}{S}/vote_{CCC}_{S}_{NNNNN}.xml`) | 9 |

The shape is exactly six fields, always all six, two hosts. The enclosing
action carries `actionCode`, `actionDate`, `actionTime`, `calendarNumber`,
`committees`, `recordedVotes`, `sourceSystem`, `text`, `type`; voted actions
carry seven of those nine. Actions per bill ranged 12–35.

**Consequence for the port.** The reference is a stable, complete six-field
record and needs no tolerance for missing fields — but BillTrax's declared type
at `sync-roll-call-votes.ts:64-72` includes a `fullActionName` field that the
API emitted **0 times in 58**, and marks `date` and `url` optional when they are
not; the port should seal the six and drop the phantom. Three live defects
confirmed against the measurement: the script sends the credential as
`api_key=` in the query string (`sync-roll-call-votes.ts:37`), against this
repo's header-only rule; it caps `actions?limit=50` where the observed maximum
is 35 but nothing bounds it; and its 429 handler recurses without a bound
(ledger item 4). Both vote-detail hosts are keyless and already sampled in the
data map (`clerk-vote`, `senate-vote`), so the reference resolves inside the
existing keyless family with no new credential.

---

## 6. Committee reports: what the agency-block parser is actually fed

`report-parser.ts` has **no test** in the BillTrax tree (the port plan's
"and its test" does not exist — `src/lib/` has 14 `.test.ts` files and none
names it) and BillTrax holds no uploaded reports, so the input shape comes
from its one call site and from real publisher documents. `api/reports/route.ts:29-34`
runs `pdf(buffer)` from `pdf-parse` and passes `parsed.text` **straight** to
`parseAgencyBlocks` — it never calls `normalizePdfText`. The grammar
`parseAgencyBlocks` expects is a line-oriented split: a line 5–100 characters
long that matches one of 12 `DEPARTMENT OF …` / `OFFICE OF …` / `FEDERAL …
(AGENCY|COMMISSION|BOARD|AUTHORITY)` patterns, **or** any all-caps line of two
or more words, starts a new block; everything until the next such line is its
body.

Three real reports, fetched keyless as GovInfo package bodies and decoded with
pymupdf. The first two are genuine appropriations committee reports, named by
the Congress.gov `committee/{chamber}/{code}/reports` route for the House and
Senate Appropriations committees; the third is the report a sampled bill names
in its own `<associated-doc>`.

| package | title | pages (stated / decoded) | bytes | text chars | blocks parsed | median block body | shortest block |
|---|---|---|---:|---:|---:|---:|---:|
| `CRPT-113hrpt135` | Energy and Water Development Appropriations Bill, 2014 | 229 / 229 | 3,233,438 | 514,002 | 182 | 1,764 | 4 |
| `CRPT-113srpt77` | Department of Homeland Security Appropriations Bill, 2014 | 190 / 190 | 531,055 | 615,516 | 382 | 878 | 4 |
| `CRPT-119hrpt105` | Providing for consideration of S.J. Res. 13 … | 3 / 3 | 199,803 | 7,116 | 9 | 207 | 4 |

| artifact | `CRPT-113hrpt135` | `CRPT-113srpt77` | `CRPT-119hrpt105` |
|---|---:|---:|---:|
| `detectLineNumbered` | false (0.14 % of lines) | false (0.45 %) | false (1.7 %) |
| `VerDate …` GPO footer lines | 229 (one per page) | 0 | 3 |
| header lines the parser fires on | 221 | 413 | 11 |
| of those, hyphen line-wrap fragments | 1 | 0 | 2 |

The heuristic is not an agency detector: on these documents it fires on
`REPORT`, `HOUSE OF REPRESENTATIVES`, `R E P O R T`, `C O N T E N T S`,
`INTRODUCTION`, `COMMITTEE VOTES`, `HURRICANE SANDY` and on the tail halves of
hyphenated line wraps — `"MENT OF THE TREASURY RELATING TO THE REVIEW OF
APPLICATIONS"` (the previous line ends `"… OF THE DEPART-"`) and
`"PORTED FROM THE COMMITTEE ON RULES"` (previous line ends `"… RESOLUTIONS RE-"`).
It does find the real ones too — `DEPARTMENT OF THE ARMY`, `OFFICE OF THE
SECRETARY AND EXECUTIVE MANAGEMENT` — but 182 blocks in a 229-page report and
382 in a 190-page one are heading counts, not agency counts, and the shortest
body in all three is 4 characters.

No keyless *agency* report (an agency's own report to Congress) was needed: the
parser's only call site creates a row in `committee_reports` with a
house/senate/conference chamber, so its real input is a committee report, and
the two appropriations reports above are that input at full size. Agency names
appear *inside* those reports as headings, which is what the parser splits on.

**Consequence for the port.** Port `parseAgencyBlocks` as a heading splitter and
name it one; the "agency" claim is not supported by its behavior on real
documents. It must be fed **normalized** text — the measured hyphen-wrap
fragments are a direct consequence of `reports/route.ts` skipping
`normalizePdfText`, which is the same defect Phase 2 already plans to fix by
routing the upload wrapper through a shared `extractNormalizedPdfText`; the
measurement says do it before porting the parser, not after. The normalizer is
safe to apply here: `detectLineNumbered` is false on all three reports, so its
line-number branch stays off, while its `VerDate` filter would remove 229 real
footer lines from one of them. Bound the extraction at 24 MiB and per-page
(3.2 MB and 615 k characters for one report); a 229-page appropriations report
is the working size, not the exception.

---

## 7. Found while reading the code

**The publisher states the PDF URL BillTrax reconstructs, and they agree.**
`/bill/119/{type}/{n}/text` returns `textVersions[]` with exactly three fields —
`date`, `formats`, `type` — and each `formats[]` entry carries a `type` and a
`url` on `www.congress.gov`. For `BILLS-119hr4727ih` and `BILLS-119hr9499rh` the
congress.gov PDF and the govinfo `content/pkg/…` PDF are **byte-identical**
(same sha256, 2/2). So the slug map exists only to rebuild an address the API
already gives; the port can follow the stated URL and delete the reconstruction,
which removes the `rhuc`/`eas2`/`eh1s` class of error at its root (§1).

**`formats[]` always carried a `type`** — 240 format entries across 24 code
samples (20 distinct bills: `hconres11`, `hres1274` and `hr3426` are each the
sample for two or three codes, so a bill's entries are counted once per
pinning code here), 0 without. The URL-suffix fallback at `sync-govinfo.ts:262`
is defensive against a shape the 119th did not produce; keep it, but do not
treat it as a live path.

**A fourth format exists that BillTrax does not read.** Format types observed:
`Formatted Text` 78, `PDF` 78, `Formatted XML` 74, **`United States Legislative
Markup` 10** — USLM; deduplicated across the 20 distinct bills these are 9
distinct entries (`hconres11` is counted twice, pinned by both `enr` and
`rds`): 5 BILLS enrolled packages and 4 PLAW-collection packages (the
`Public Law` version on a bill's `/text` endpoint). On the one version
matched by file name it was the enrolled bill (`BILLS-119hconres11enr`); all
five BILLS packages were fetched and parsed 2026-09-19
(`tests/fixtures/govinfo_bills/uslm-renditions-2026-09-19.json`, corpus
receipt `uslm-bill-rendition-2026-09-19`). spicy-docs already has
`sources/govinfo/uslm.py` and `uslm_acquisition.py`; BillTrax looks only for
XML/PDF/HTM and drops it. Four versions offer text and PDF but no `Formatted
XML`, so an XML-only acquisition path has real gaps.

**`committee/{chamber}/{systemCode}/reports` ignores `sort`.** Asking
`sort=updateDate+desc` returned the identical order to the default on both
`hsap00` and `ssap00` — a Table-A-style fact for the route table Phase 4 builds.
Worse for the port: both committees' report lists stop at the **113th**
Congress (the Senate list also holds 109th entries), so this route is not a path to
current appropriations reports and the report→package edge must come from the
bill's own `<associated-doc>` or from the committee-report listing by Congress.

**The bulkdata type folder mixes granularities.** `BILLS/119/{session}/{type}`
contains the per-session ZIP (`BILLS-119-1-hr.zip`) beside the XML files, with
the same `files[]` entry shape; a crawler that takes "every non-folder entry"
will try to parse a ZIP as XML. Measured the hard way: seven of the first forty
sample fetches hit ZIPs, two of which exceeded the byte bound before the
content-type check could refuse them.

**Consequence for the port.** Three of these change plans already written: the
PDF capture mode should follow the publisher's stated rendition URL rather than
a slug map (Phase 5 and ledger item 3 both shrink to "delete the map"); USLM
belongs in the format preference list since spicy-docs already reads it; and the
Phase 4 route table needs `committee/{chamber}/{code}/reports` marked as
sort-ignoring *and* coverage-limited, so no one builds a current-reports path on
it.

---

## Ten facts to carry forward

1. The 119th used **24** bill-text version codes; BillTrax's slug map reaches 12
   correctly, misses 12 codes covering 1,027 files, and maps three to the wrong
   document.
2. `eas2`/`eh1s` prove the Congress.gov `type` **name is not unique** per
   version — only the package-id code is — so a name-derived slug silently
   fetches the earlier printing.
3. **29 of 40** sampled files (and 3,416 of 21,947 in the 119th) use
   `resolution-body`, where both tree parsers throw; decision 7 is "support it".
4. The bill XML sample holds **100 distinct elements**; the tree parsers name
   18, so 82 — identity, sponsors, committees, cross-references, all tables —
   are discarded on a corpus that costs 491 MB to re-fetch.
5. Bill PDFs: median 246 KB, max 4.77 MB (1,259 pages), **0 of 15 over the
   24 MiB bound**; the publisher states the **page count twice** and agrees with
   a decode 15/15, and states **no byte size anywhere**.
6. **All four** press-release URLs BillTrax holds are dead (404, 404, 410, and a
   200 ColdFusion error page); the canonical pair is
   `appropriations.house.gov/rss.xml` and
   `www.appropriations.senate.gov/rss/feeds/?type=press`.
7. Both feeds are **RSS 2.0 with no namespace and no Atom anywhere**; the Senate
   item has **no `<description>`**, so BillTrax's excerpt is permanently empty
   there, and its `pubDate` says "EST" in September.
8. `recordedVotes` is exactly six always-present fields across 58 entries on two
   keyless hosts; BillTrax's declared `fullActionName` field does not exist.
9. The report upload path feeds **un-normalized** `pdf-parse` text to
   `parseAgencyBlocks`, and the measured result is block labels that are the
   tail halves of hyphenated line wraps; the splitter finds 182 and 382 "agency"
   blocks in two appropriations reports, so it is a heading splitter.
10. The congress.gov and govinfo PDF addresses serve **byte-identical** files,
    so the slug map can be deleted rather than repaired.
