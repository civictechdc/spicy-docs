# Capture CFR and eCFR XML

Choose a source and explicit scope. SpicyDocs returns validated XML, the exact
HTTP payload, and the native identity and dates it found. It does not choose an
edition, switch routes after failure, or infer that the publisher is complete.

| Route | Required selection | What it supplies |
| --- | --- | --- |
| eCFR API | Title and date; optional part and section | XML for that requested snapshot and scope. A section also requires an explicit part. |
| Annual CFR | Year, title and volume; optional section | GovInfo volume or section XML. Requested year and printed revision remain separate. |
| Annual CFR metadata | Year, title and volume | Mapped GovInfo MODS package and constituent records, publication type and exact XML. |
| GovInfo bulk eCFR | Title | Latest-route XML in its original bulk wrapper. No historical date selector. |
| eCFR title index | None | JSON roster with separate amendment, issue and currency dates, plus processing status. |

Title 35 is reserved. Part and section numbers are independent publisher
coordinates: for example, Title 14 Part 241 contains section `19-8.1`.

## Capture one source

From the checkout, install acquisition dependencies with
`uv sync --frozen --extra acquisition`. Each output directory must be new.

```sh
uv run --frozen python -m examples.cfr_capture ecfr \
  --title 1 --date 2026-07-31 --part 18 --section 18.1 \
  --max-bytes 2097152 --output /tmp/cfr-section-capture

uv run --frozen python -m examples.cfr_capture annual \
  --year 2025 --title 1 --volume 1 \
  --max-bytes 2097152 --output /tmp/cfr-annual-capture

uv run --frozen python -m examples.cfr_capture annual-edition \
  --year 2025 --title 1 --volume 1 \
  --max-bytes 2097152 --output /tmp/cfr-edition-capture

uv run --frozen python -m examples.cfr_capture ecfr-bulk \
  --title 1 --max-bytes 2097152 --output /tmp/ecfr-bulk-capture

uv run --frozen python -m examples.cfr_capture ecfr-titles \
  --max-bytes 65536 --output /tmp/ecfr-titles-capture
```

The example writes `receipt.json` and original XML or JSON. The eCFR API requires
compression: for gzip responses it retains both `response.xml.gz` (received
payload) and `response.xml` (decoded XML), with separate hashes and byte counts.
The `annual-edition` route also writes `metadata.json`: the complete mapped
source record, with a file hash and original-input hash in the receipt.
Failures retain a receipt and bounded refused bytes when available.

The example defaults to two requests, a 20-second transport timeout, and one
second between request starts within a client. Set `--max-requests`,
`--timeout-seconds` and `--min-request-interval-seconds` to change them.

## Use the wheel in an application

Install SpicyDocs with its `acquisition` extra; see [installation](../installation.md).
Pure selection, locator and validation functions need only the core package.

```python
from spicy_docs.sources.cfr import EcfrSelection
from spicy_docs.sources.cfr.acquisition import CfrAcquirer, CfrAcquisitionBudget

budget = CfrAcquisitionBudget(
    max_requests=2,
    max_bytes=2 * 1024 * 1024,
    timeout_seconds=20,
    min_request_interval_seconds=1,
)
with CfrAcquirer(budget=budget) as source:
    result = source.acquire_ecfr(EcfrSelection(1, "2026-07-31", part="18", section="18.1"))

xml = result.xml  # Decoded, validated XML bytes.
payload = result.capture.body  # Exact HTTP payload; may be gzip.
encoding = result.capture.content_encoding
native_fields = result.identity  # Printed facts and identity basis.
requested_scope = result.selection
```

Use `acquire_annual(AnnualCfrSelection(...))`, `acquire_ecfr_bulk(title)` or
`acquire_ecfr_titles()` for the other routes. Pure validators accept retained
XML plus the expected selection and final URL for offline checks.

## Place annual sections under their parts

`scan_annual_cfr_sections(xml, max_bytes=...)` reads one acquired annual
volume (`CFRDOC`) in a single streaming pass and returns every SECTION in
document order. Its part is the number in the innermost enclosing `PART`
heading, because neither the printed section number nor the GovInfo granule id
establishes it: Title 43 numbers sections by subpart (§ 1601.0-1 is in Part
1600), Title 41's compound parts contain a hyphen (`50-201`) and Title 14 Part
241 prints `19-8.1`. The running head is kept for diagnostics only; some are
wrong. A section under a PART that prints no heading, or outside every PART,
has no part.

Look a granule up by its token (`granule`) among the `canonical` sections, and
never filter on `nested`, `wrapped` or `revised`: none of them means "not
current". Unclosed publisher elements swallow the parts that follow them, so in
15 CFR vol 1 every part after 6 prints inside § 6.5's revised text, and one
wrapper section holds 41 CFR vol 4. In the published table 4,022 section
granules match only a nested copy and 2,512 only a revised one. `wrapped` marks
a section with a PART between it and its enclosing section; the canonical copy
of a token is the one with the lowest (nested, revised, position), and
`repeated` marks numbers printed twice outside nesting. Three content granules
carry a GovInfo `-id` suffix (`sec849-504-id915`); strip it to reach the same
canonical copy.

`split_annual_cfr_section(number, part, subpart)` gives the `section` and, for
one citable section, its printed `citation`: Title 43's subpart-numbered
sections cite as printed while their part stays the heading's. Ranges,
publisher typos (`§ 206.253` under `PART 1206`) and unprefixed forms such as
`Sec. 1-1` have none. `citation_joins` is false for the 1,496 citations that
keep parentheses (`1.401(k)-1`), because the Federal Register side's key reads
`26 CFR 1.401(k)-1` as `26-1.401`; set `cfr_ref` NULL for those until the
shared citation grammar decides one spelling.

Pass `max_bytes` explicitly. The largest retained 2025 volume (40 CFR vol 20)
is 12,576,481 bytes, so the 16 MiB default leaves only 1.33× headroom; 64 MiB
is a reasonable cap within the 256 MiB maximum.

Over the 262 retained 2025–2026 volumes, an independent lxml tree scan finds
the same printed number, nesting and innermost PART heading for every section.
It reuses the heading pattern, so it confirms the streaming traversal, not the
pattern; the survey checked the pattern's changed parts against eCFR and MODS.
The receipt is in
`corpora/supply-2026-09-02/receipts/cfr-section-ancestry-2026-09-23/`.

## Read dates and identity honestly

`identity_basis` identifies native XML fields and fields supported only by the
exact response URL. A subset may omit its title; an annual volume may omit its
volume number. Those native fields remain `None`.

The requested API date is not an amendment date. An annual edition can also
carry an older printed revision. Keep both dates; their difference produces no
warning and does not establish the publication type.

Use `acquire_annual_edition(AnnualCfrSelection(2025, 1, 1))` to obtain that type
from GovInfo's MODS (Metadata Object Description Schema) package XML. This is a
separate, explicit request; body acquisition does not fetch metadata implicitly.
The result supplies `.edition`, mapped `.metadata` and the exact `.capture`. Section selections are
rejected because this metadata describes the whole volume.

| `edition.edition_type` | Publisher evidence |
| --- | --- |
| `cover-only` | `isCoverOnly=true`: this annual publication carries forward the previous volume. It can still supply the complete regulation XML. |
| `not-cover-only` | `isCoverOnly=false`: no claim about how much text changed. |
| `unknown` | The publisher omitted the flag. A malformed flag is refused. |

The type is derived from `.is_cover_only`; `.date_issued` and
`.original_date_issued` remain independent. The example receipt includes all
three. For 2025 Title 1, GovInfo explicitly states `isCoverOnly=true`,
`dateIssued=2025-01-01`, and `originalDateIssued=2023-01-01`. The identical 2023
and 2025 body XML is consistent with that publication practice. See the
[native metadata](https://www.govinfo.gov/metadata/pkg/CFR-2025-title1-vol1/mods.xml)
and [GPO's explanation](https://bookstore.gpo.gov/products/cfr-title-1-cvr-code-federal-regulations-2025).

The API also exposes the literal title, edition identifier, current-edition flag
and fallback-title flag. Status flags describe the publisher's answer at capture
time; they do not select another edition. The complete mapped MODS includes
constituent identifiers, parent relationships, rendition links and citation hints.
Those advertised links do not establish acquired bodies. Nested
constituent fields cannot replace the package's identity or edition facts.

In the retained 2025 Title 1 metadata, 401 constituent entries include 288 section
entries and 400 parent links. They advertise 391 XML and 400 PDF renditions;
some structural nodes offer only PDF. Literal authority/history notes and
structured citation hints are also available. This inventory can supply DocSpec
catalog selection without downloading each body first. SpicyDocs exposes these
source records in `result.metadata.constituents`; the
[metadata guide](govinfo-metadata.md) maps published field definitions to the API.
Reference hints still need checking: Chapter VI is labeled as a `part` in
the 2025 metadata and as a `chapter` in the 2023 metadata.

## Bounds and downstream work

- Every operation requires a byte allowance, capped at 256 MiB. For gzip,
  received and decoded bytes each obey that allowance. Per-call `max_bytes`
  can narrow the client allowance.
- Whole-title validation scans XML without building a full tree. It refuses
  entities, DTDs, excessive nesting, malformed XML and contradictory requested
  identity. A timeout limits transport waits, not total operation duration.
- Metadata mapping builds one bounded tree: up to 100,000 elements and depth 64,
  within the acquisition byte allowance. Unknown fields, repeated values and
  namespace context remain available; selected edition facts have separate checks.
- `401`/`403` stops acquisition. Only an exact `404`/`410` produces
  `CfrSourceUnavailableError`; it establishes no publisher-wide absence.
- Graphics and table structure remain in the XML. Linked assets are not fetched.
  Annual section locator syntax is deliberately limited to supported explicit
  section numbers; a constructed URL does not prove availability.
- These captures do not publish a source release. Existing release admission
  remains capped at 24 MiB. Dataset selection, storage, recovery and processing
  belong to the caller or DocSpec.

RefSpec already reads retained eCFR API XML into text and native addresses.
Pass it decoded `result.xml`, retaining the original payload alongside it.
Its current reader does not accept annual CFR or the GovInfo bulk wrapper;
subset XML can also lack the title needed for addresses. Preserve those limits
instead of stripping wrappers or inventing coordinates. The
[reuse inventory](../source-reference.md#cfr-metadata-and-separately-acquired-xml)
lists existing owners and consumers.

The installed-wheel handoff is qualified with Title 1. RefSpec's current address
reader also rejects some valid numbering, including Part 241 / section `19-8.1`
in Title 14. Successful source validation does not promise that every downstream
reader can address every section.

The September 12 qualification returned 274 Title 1 addresses and reported 14
unsupported combined-range addresses. Those issues remain visible. All seven
source request shapes succeeded in bounded live captures, and offline source
validation passed all 49 nonreserved titles in the retained August 24 snapshot
(810,674,584 bytes). That replay does not establish current coverage.

Publisher references: [eCFR API](https://www.ecfr.gov/developers/documentation/api/v1),
[annual CFR XML guide](https://github.com/usgpo/bulk-data/blob/main/CFR-XML_User-Guide.md),
[bulk eCFR XML guide](https://github.com/usgpo/bulk-data/blob/main/ECFR-XML-User-Guide.md).
