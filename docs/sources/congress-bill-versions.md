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

chosen = choose_format(status.text_versions[0].formats)  # prefers xml, then html, then txt
```

```python
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
    result = acquire_bill_pdf(identity, "engrossed-in-house", acquirer=client)

pdf_bytes = result.body_capture.body
```

This ports BillTrax's `version_code` slug map, `slugify`, `chooseFormat` /
`chooseXmlFormat` / `pickVersionUrls`, and `classifyVersionKind`
(`/Users/mikewolfd/Work/spicy-stack/BillTrax`, read-only — see
`docs/research/billtrax-value-inventory-2026-09-19.md` §1a and §2.1/§2.4, and
the measurement in `docs/research/billtrax-raw-data-2026-09-19.md` §1, §3, §7).

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

## Three publisher spellings, one identity

A single GovInfo BILLS package-id suffix can appear under three different
publisher spellings, and this module records the ones it has evidence for:

1. **The package-id suffix itself** (`eh`, `rs`, `eas2`) — the only spelling
   that survives a numbered reprint, because it is what the file is named.
2. **The Congress.gov `textVersions[].type` string** ("Engrossed in House",
   "Reported to Senate") — what `version_slug()`/`slugify()` derive a slug
   from. **Not unique**: "Engrossed Amendment Senate" names both `eas` and its
   reprint `eas2`; "Engrossed in House" names both `eh` and `eh1s`. A
   name-derived slug cannot tell them apart.
3. **The document's own `@bill-stage`/`@resolution-stage` root attribute**
   (`bill_text.py` already reads three of these: `"Engrossed-in-House"`,
   `"Introduced-in-House"`, `"Enrolled-Bill"`). Measured on a 10-file sample:
   `rs`'s API type says "Reported **to** Senate"; the same file's
   `resolution-stage` says "Reported-**in**-Senate". Different words, same
   document.

**Consequence.** The package id is the identity; the other two are evidence
about it, kept in the table's `version_types` and `stage_value` fields. Name
derivation (`version_slug`, `bill_version_package_id`) is a documented
fallback, not the preferred path — see the PDF path below.

## Format choice

`choose_format(formats, prefer=("xml", "html", "txt"))` ports
`congress-api.ts chooseFormat`/`chooseXmlFormat` and `sync-govinfo.ts
pickVersionUrls` as one function. It returns the first format in `formats`
whose type matches an entry of `prefer`, in order; `prefer` takes this
module's short names (`xml`, `html`, `txt`, `pdf`, `uslm`), not Congress.gov's
`type` strings. PDF is never chosen unless a caller names it, matching
`GovInfoBodyAcquirer`'s own default preference.

**The URL-suffix fallback.** `sync-govinfo.ts:262` added a fallback for a
format item with no stated `type`: infer the format from the URL's file
extension instead of skipping the item. `choose_format` keeps it (the port
contract named in the inventory). Measured 2026-09-19: every one of 240
sampled format entries across 24 bills carried a `type`, so this fallback is
a tolerance, not a path any bill in the sample actually took.

**A fourth format.** Congress.gov offers `United States Legislative Markup`
(USLM) on enrolled bills — 10 of the 240 sampled format entries. BillTrax
never reads it; `sources.govinfo.uslm` already does. `choose_format`
recognizes `"uslm"` as a preference name; it is not in the default tuple,
matching BillTrax's own preference order, but a caller building an
enrolled-bill pipeline should ask for it explicitly.

## The PDF path

`bill_pdf.acquire_bill_pdf(identity, slug, *, acquirer, package_id=None)`
fetches one bill version's PDF through
[`GovInfoBodyAcquirer`](govinfo-bodies.md) — the same identity-first fetch
every other GovInfo package body uses. There is no second HTTP path: this
function only derives a package id and delegates to `acquirer.acquire(...,
prefer=("pdf",))`.

Measured 2026-09-19 (`docs/research/billtrax-raw-data-2026-09-19.md` §3, §7):
the congress.gov and govinfo PDF addresses for the same version serve
byte-identical files, and bill PDFs run small — median 246 KB, max 4.77 MB
across 15 packages sampled, none over the 24 MiB evidence bound. So:

- **Pass `package_id`** when the caller already has the publisher's own
  stated package id for this version (read from a BILLSTATUS or Congress.gov
  format URL via `bill_status.bill_package_id_from_url`). This is preferred:
  it is correct for a numbered reprint, which the name-derived fallback is
  not.
- **Omit it** and `acquire_bill_pdf` falls back to
  `bill_version_package_id(identity, slug)` — the ported
  `buildGovinfoPdfUrl`, minus its own HTTP call (GovInfoBodyAcquirer already
  proves identity from the package summary and MODS before spending any body
  byte, which `govinfo-pdf-fetch.ts` never did).

## Decision: the vocabulary is sealed; only additions move it

*For the maintainer to relocate into `docs/decisions.md`.*

BillTrax's SQL keys on `bill_versions.version_code` strings. Every slug this
port found in either of BillTrax's two copies of the map
(`govinfo-pdf-fetch.ts:26-58`, canonical; `validate-pdf-xml-concordance.ts:44-64`,
a private, drifted copy missing four short codes) stays in `VERSION_CODES`
under its original spelling. This module only adds slugs; it never renames or
removes one, even where the publisher's measured 119th data contradicts the
slug's own name (`referred-to-senate` really names "Received in Senate";
`reported-in-senate` really names "Reported to Senate"). The slug is a
BillTrax identifier now, not a live claim about what the publisher calls the
document — that claim lives in `version_types`.

**One correction, not a rename.** `returned-to-the-house-by-unanimous-consent`
kept its slug but had its `govinfo_suffix` corrected from `rfh` to `rhuc`.
BillTrax's canonical map deliberately collided this slug with
`referred-to-house` on `rfh`; the 119th measurement shows the publisher never
spells "Returned to the House by Unanimous Consent" that way — its real
suffix is `rhuc`, which a "Referred in House" document never uses. Leaving
`rfh` in place would have made `bill_version_package_id` build the wrong
document's package id for every bill using this slug. Outcome over rules: the
publisher wins. `rhuc` is also added as its own passthrough entry.

**The name-derived map is demoted, not deleted.** `bill_version_package_id`
and `version_slug` remain, because BillTrax's stored rows and some
acquisition paths carry only a slug or a type name, never a package id. But
`acquire_bill_pdf` prefers a stated package id when the caller has one, and
this document says why: a version-type name is not unique per version (a
numbered reprint shares its original's name), so a name-derived slug can
silently address the wrong document. The map is the fallback for when nothing
better exists, not the primary derivation.

**Left for the maintainer.** `classifyVersionKind`'s own slug lists
(`interpretation/version_kind.py`) are ported as measured, including the five
gaps the 119th census exposed (`as`, `cdh`, `lth`, `rds`, `ris`, which fall
through to the size heuristic rather than a named kind). Whether to extend
those lists from the measurement, and whether spicy-regs should store all
three spellings (suffix, type, stage) or only the suffix, are open — this
document states the evidence, not the schema decision.
