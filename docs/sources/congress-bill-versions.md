# Bill-version codes, format choice and bill PDFs

Give SpicyDocs a bill identity and a `version_code` slug from BillTrax's sealed
vocabulary. It returns the GovInfo BILLS package id for that version, the
format it prefers among the ones a text version offers, and — with a
[GovInfo body acquirer](govinfo-bodies.md) — that version's PDF. No API key is
required for the vocabulary or format choice; the PDF fetch needs one, exactly
as every other GovInfo body fetch does.

```python
from spicy_docs.sources.congress.bill_status import BillIdentity
from spicy_docs.sources.congress.bill_versions import bill_version_package_id, choose_format

identity = BillIdentity(119, "hconres", 11)
package_id = bill_version_package_id(identity, "engrossed-in-house")  # "BILLS-119hconres11eh"

chosen = choose_format(status.text_versions[0].formats)  # xml, then html, then txt, then pdf
```

```python
from pathlib import Path

from spicy_docs.sources.congress.bill_pdf import acquire_bill_pdf
from spicy_docs.sources.govinfo.body_acquisition import GovInfoBodyAcquirer, GovInfoBodyBudget
from spicy_docs.transport.credentials import read_api_key

budget = GovInfoBodyBudget(
    max_requests=6,
    max_body_bytes=8 * 1024**2,
    max_metadata_bytes=8 * 1024**2,
    timeout_seconds=60,
    min_request_interval_seconds=0.5,
)
with GovInfoBodyAcquirer(budget=budget, api_key=read_api_key(Path(".env"), "API_GOV")) as client:
    # Prefer a stated package id when the caller has one (see "The PDF path" below).
    result = acquire_bill_pdf(identity, acquirer=client, slug="engrossed-in-house")

pdf_bytes = result.body_capture.body
```

This ports BillTrax's `version_code` slug map, `slugify`, `chooseFormat` /
`chooseXmlFormat` / `pickVersionUrls`, and `classifyVersionKind`
(`/Users/mikewolfd/Work/spicy-stack/BillTrax`, read-only — see
`docs/research/billtrax-value-inventory-2026-09-19.md` §1a and §2.1/§2.4, and
the measurement in `docs/research/billtrax-raw-data-2026-09-19.md` §1, §3, §7).
The vocabulary is also cross-checked against DeltaTrack upstream's own
authoritative govinfo code list, `tools/fetch_govinfo.py::VERSION_CODES` /
`resolve_code()` (canonical repo `https://github.com/civictechdc/DeltaTrack`,
a separate BillTrax-adjacent project this port otherwise draws nothing from) —
see "Cross-checked against DeltaTrack upstream" below.

## The vocabulary table

`sources.congress.bill_versions.VERSION_CODES` is one table: each entry names
a sealed `slug` (what `bill_versions.version_code` would store), the
`govinfo_suffix` the fallback path builds a package id from, the Congress.gov
`version_types` measured to produce that slug, the document's own
`stage_value` attribute spelling where measured, and whether the suffix
appeared in the 119th Congress's BILLS package-id census (24 distinct
suffixes across 21,947 files, all 19 `bulkdata/json/BILLS/119/{session}/{type}`
listings, measured 2026-09-19).

| slug | govinfo suffix | measured 119th | files (119th) | note |
| --- | --- | --- | --- | --- |
| `introduced-in-house` | `ih` | yes | 12,092 | |
| `introduced-in-senate` | `is` | yes | 6,054 | |
| `engrossed-in-house` | `eh` | yes | 931 | |
| `reported-in-house` | `rh` | yes | 808 | |
| `referred-to-senate` (→ `rds`) | `rds` | yes | 32 | BillTrax's own name says "referred"; the publisher's measured `type` is "Received in Senate" |
| `reported-in-senate` (→ `rs`) | `rs` | yes | 444 | three spellings for one suffix: API `type` "Reported to Senate", XML `resolution-stage="Reported-in-Senate"` |
| `engrossed-in-senate` | `es` | yes | 209 | |
| `placed-on-calendar-senate` | `pcs` | yes | 183 | |
| `enrolled-bill` | `enr` | yes | 145 | |
| `public-law` (→ `enr`) | `enr` | no (unconfirmed) | — | deliberate collision with `enrolled-bill`; every sampled `enr` file's API `type` read "Enrolled Bill", never "Public Law" |
| `referred-to-house` | `rfh` | yes | 4 | |
| `engrossed-amendment-senate` | `eas` | yes | 11 | |
| `engrossed-amendment-house` | `eah` | yes | 7 | |
| `returned-to-the-house-by-unanimous-consent` | `rhuc` **(corrected)** | yes | 2 | BillTrax mapped this to `rfh`; the publisher never once spells it that way — see Decision below |
| `placed-on-calendar-house` | `pch` | **no** | 0 | BillTrax knew it; the 119th never produced it |
| `held-at-desk-senate` | `hds` | **no** | 0 | BillTrax knew it; the 119th never produced it |
| `rfs` *(addition)* | `rfs` | yes | **568** | the single largest gap in BillTrax's map — 2.6% of the corpus |
| `ats` *(addition)* | `ats` | yes | 431 | "Agreed to Senate" |
| `cps` *(addition)* | `cps` | yes | 16 | "Considered and Passed Senate" |
| `rcs` *(addition)* | `rcs` | yes | 3 | "Reference Change Senate" |
| `as` *(addition)* | `as` | yes | 1 | "Amendment Ordered to be Printed (Senate)" |
| `cdh` *(addition)* | `cdh` | yes | 1 | BillTrax's `committee-discharge-house` slug does not match — the publisher's `type` is "Committee Discharged House", not "Committee Discharge House" |
| `lth` *(addition)* | `lth` | yes | 1 | "Laid on Table in House" |
| `ris` *(addition)* | `ris` | yes | 1 | "Referral Instructions Senate" |
| `eas2` *(addition)* | `eas2` | yes | 1 | a numbered reprint of `eas`; same API `type` string as `eas` |
| `eh1s` *(addition)* | `eh1s` | yes | 1 | a numbered reprint of `eh`; same API `type` string as `eh` |
| `rfs2` *(addition)* | `rfs2` | yes | 1 | a numbered reprint of `rfs`; same API `type` string as `rfs` |

The full table, including every passthrough short code, lives in
`sources/congress/bill_versions.py` alongside the evidence for each entry.
**24 distinct suffixes were measured; BillTrax's original map reached 12 of
them correctly, had no entry for 12 more (1,027 files, 4.7% of the corpus,
`rfs` alone 568), and resolved one suffix (`rfh`) from two colliding slugs,
one of which was wrong.** `version-kind.ts`'s own classification list misses
5 of the 24 (`as`, `cdh`, `lth`, `rds`, `ris`) and falls through to its size
heuristic for them; `cdh` misses only because its slug does not match the
publisher's own spelling of the type name.

## Cross-checked against DeltaTrack upstream

DeltaTrack's own `tools/fetch_govinfo.py::VERSION_CODES` / `resolve_code()`
(https://github.com/civictechdc/DeltaTrack, read only, not otherwise a source
for this port) carries govinfo's full authoritative 53-code list
(govinfo.gov/help/bills) with its own display names and a documented
longest-known-prefix fallback for a numbered reprint (`eas2 -> eas`). All 24
codes this port measured in the 119th resolve there — the three reprints
(`eas2`, `eh1s`, `rfs2`) through that same fallback, the other 21 as direct
entries — with two purely cosmetic spelling differences, both recorded on
their entries: `rs`'s measured API type is "Reported to Senate" against
upstream's canonical "Reported in Senate", and `as`'s measured type carries
parenthesized "(Senate)" where upstream's does not (both slugify identically,
so neither disagreement changes resolution).

The **30** codes upstream carries that neither BillTrax nor this port's own
119th measurement produced (`ash`, `sas`, `sc`, `rdh`, `rch`, `rth`, `rts`,
`rih`, `rah`, `ras`, `hdh`, `cds`, `oph`, `ops`, `pp`, `pav`, `reah`, `res`,
`eph`, `cph`, `ath`, `fah`, `fph`, `fps`, `iph`, `ips`, `lts`, `pwah`, `renr`,
`pap`) are added as unmeasured passthrough entries, `measured_119th=False`,
each citing DeltaTrack upstream as its source, so the vocabulary does not
silently lack a real govinfo code for want of a 119th sighting. `VERSION_CODES`
now holds 72 entries in total. DeltaTrack's separate `version_stems.py`
resolves on-disk filename ordinals for a locally cached bill folder — a
different concern entirely, and not a source for this table.

## Three publisher spellings, one identity

A single GovInfo BILLS package-id suffix can appear under three different
publisher spellings, and this module records the ones it has evidence for:

1. **The package-id suffix itself** (`eh`, `rs`, `eas2`) — the only spelling
   that survives a numbered reprint, because it is what the file is named.
2. **The Congress.gov `textVersions[].type` string** ("Engrossed in House",
   "Reported to Senate") — what `version_slug()` resolves back to a sealed
   slug. **Not unique**: "Engrossed Amendment Senate" names both `eas` and its
   reprint `eas2`, "Engrossed in House" names both `eh` and `eh1s`, and
   "Referred in Senate" names both `rfs` and `rfs2`. A name-derived slug
   cannot tell a reprint from its original.
3. **The document's own `@bill-stage`/`@resolution-stage` root attribute**
   (`bill_text.py` already reads three of these: `"Engrossed-in-House"`,
   `"Introduced-in-House"`, `"Enrolled-Bill"`). Measured on a 10-file sample:
   `rs`'s API type says "Reported **to** Senate"; the same file's
   `resolution-stage` says "Reported-**in**-Senate". Different words, same
   document.

`version_slug(version_type)` resolves a measured or cited type string to the
sealed slug that actually claims it — not necessarily `slugify(version_type)`
itself. BillTrax's own name for `rds` is `referred-to-senate`, but the
publisher's measured type for that suffix is "Received in Senate"
(`slugify` alone gives `received-in-senate`, which names nothing);
`version_slug` redirects it to the sealed slug. When more than one sealed
slug claims the identical type name — the three reprint pairs above —
`version_slug` always resolves to the earliest-declared (earliest-printed)
one, and **does not hide that it did**: `version_slug_reprints(version_type)`
returns the other slug(s) that share the name, empty when there is no
ambiguity (including for a same-suffix alias pair like
`returned-to-the-house-by-unanimous-consent`/`rhuc`, which name one document
twice — aliasing, not ambiguity).

**Consequence.** The package id is the identity; the other two are evidence
about it, kept in the table's `version_types` and `stage_value` fields. Name
derivation (`version_slug`, `bill_version_package_id`) is a documented
fallback, not the preferred path — see the PDF path below. A caller that
cares whether a name-derived slug might be wrong should check
`version_slug_reprints` before trusting it.

## Format choice

`choose_format(formats, prefer=DEFAULT_FORMAT_PREFERENCE)` is one function
carrying BillTrax's `congress-api.ts chooseFormat` and `sync-govinfo.ts
pickVersionUrls`'s fallback for a format item with no stated `type`. `prefer`
takes this module's short names (`xml`, `html`, `txt`, `pdf`, `uslm`), not
Congress.gov's `type` strings.

`DEFAULT_FORMAT_PREFERENCE` is `("xml", "html", "txt", "pdf")`: the sealed
[`BODY_PREFERENCE`](govinfo-bodies.md#the-preference-rule) spelled in this
module's own names, where the GovInfo rendition `htm` is `html`. There is one
order for both, and a test pins them equal, so a version chosen here is
fetched there. It keeps BillTrax's own XML-then-text-then-PDF order and adds
HTML where the sealed order puts it, between XML and text. PDF stays the last
*default* rather than being left out — bill PDFs measured small (median
246 KB, see "The PDF path" below), and a version a publisher offers only as
PDF is chosen rather than refused, which is the point of keeping it last
instead of dropping it.

**The fallback is folder-based, not extension-based, and it is the only live
path today.** `BillTextFormat` is built in exactly one place on `main`,
`bill_status.py`'s `_text_version`, from BILLSTATUS `<formats><item>` XML —
which carries `<url>` only, **never** `<type>`, confirmed on every fixture in
`tests/fixtures/govinfo_bills`. So `item.type` is always `None` for every
`BillTextFormat` this repository actually builds, and `choose_format`'s
type-string table (`FORMAT_TYPE_NAMES`, for a Congress.gov REST producer this
repository does not build yet) is dead code against real data; the fallback
is what runs. It names a format from the GovInfo rendition *folder* in the
URL path (`xml/`, `html/`, `text/`, `pdf/`, `uslm/` —
`sources.govinfo.bodies.PACKAGE_BODY_FORMATS`'s own folder names), not the
file extension: BILLS states its USLM rendition at `uslm/{id}.xml`, which no
extension check can tell apart from `xml/{id}.xml`. The "every one of 240
sampled format entries carried a `type`" measurement
(docs/research/billtrax-raw-data-2026-09-19.md §7) was of the Congress.gov
REST route, a different producer than BILLSTATUS — it says nothing about
whether the fallback fires against the data parsed here, and it does, always.

**A fourth format, not yet acquirable.** Congress.gov's REST route offers
`United States Legislative Markup` (USLM) on enrolled bills — 10 of the 240
sampled REST format entries — and BILLS states its own USLM rendition at
`uslm/{id}.xml` in its MODS. `choose_format` recognizes `"uslm"` by name and
by folder; it stays out of `DEFAULT_FORMAT_PREFERENCE`, matching BillTrax's
own order and the sealed `BODY_PREFERENCE`, neither of which names it. But
it is **not yet fetchable**: `GovInfoBodyAcquirer`'s
`PACKAGE_BODY_FORMATS` supports only `htm`/`xml`/`txt`/`pdf`, and
`sources.govinfo.uslm` reads the separate PLAW and COMPS collections (public
laws and statute compilations), not a BILLS package's own USLM rendition. A
caller that asks `acquire_bill_pdf`'s underlying acquirer to prefer `"uslm"`
gets a `ValueError` naming it unsupported, not a silent wrong fetch.

## The PDF path

`bill_pdf.acquire_bill_pdf(identity, *, acquirer, slug=None, package_id=None)`
fetches one bill version's PDF through
[`GovInfoBodyAcquirer`](govinfo-bodies.md) — the same identity-first fetch
every other GovInfo package body uses. There is no second HTTP path: this
function only derives a package id and delegates to `acquirer.acquire(...,
prefer=("pdf",))`. **Exactly one** of `slug` and `package_id` must be given;
`slug` is keyword-only precisely so it cannot sit unused beside a
`package_id` a caller already trusts more.

Measured 2026-09-19 (`docs/research/billtrax-raw-data-2026-09-19.md` §3, §7):
the congress.gov and govinfo PDF addresses for the same version serve
byte-identical files, and bill PDFs run small — median 246 KB, max 4.77 MB
across 15 packages sampled, none over the 24 MiB evidence bound. So:

- **Pass `package_id`** when the caller already has the publisher's own
  stated package id for this version (read from a BILLSTATUS or Congress.gov
  format URL via `bill_status.bill_package_id_from_url`). It is used exactly
  as given, with **no cross-check against `slug`**: a numbered reprint's real
  package id (`BILLS-119hr6644eas2`) legitimately disagrees with the slug its
  shared type name derives (`version_slug("Engrossed Amendment Senate")` is
  `engrossed-amendment-senate`, which names `eas`, not `eas2` —
  `version_slug_reprints` says so). Rejecting that disagreement would block
  the exact case a stated package id exists to fix, so callers pass one or
  the other, never both.
- **Pass `slug`** when no stated package id exists, and `acquire_bill_pdf`
  falls back to `bill_version_package_id(identity, slug)` — the ported
  `buildGovinfoPdfUrl`, minus its own HTTP call (GovInfoBodyAcquirer already
  proves identity from the package summary and MODS before spending any body
  byte, which `govinfo-pdf-fetch.ts` never did). It cannot tell a numbered
  reprint from its original by name alone.

## Decision: the vocabulary is sealed; only additions move it

See ["Bill-version codes are a sealed, additions-only
vocabulary"](../decisions.md#bill-version-codes-are-a-sealed-additions-only-vocabulary)
in `docs/decisions.md`; the package-id-as-identity rule for the PDF path is
also now part of ["GovInfo package bodies are fetched by package id, never
crawled"](../decisions.md#govinfo-package-bodies-are-fetched-by-package-id-never-crawled)
there.

**Left for the maintainer.** `classifyVersionKind`'s own slug lists
(`interpretation/version_kind.py`) are ported as measured, including the five
gaps the 119th census exposed (`as`, `cdh`, `lth`, `rds`, `ris`, which fall
through to the size heuristic rather than a named kind). Whether to extend
those lists from the measurement (now 72 sealed entries deep, most never
classified), and whether spicy-regs should store all three spellings
(suffix, type, stage) or only the suffix, are open — this document states
the evidence, not the schema decision.
