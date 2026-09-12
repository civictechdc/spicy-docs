# Capture CFR and eCFR XML

Choose a source and explicit scope. SpicyDocs returns validated XML, the exact
HTTP payload, and the native identity and dates it found. It does not choose an
edition, switch routes after failure, or infer that the publisher is complete.

| Route | Required selection | What it supplies |
| --- | --- | --- |
| eCFR API | Title and date; optional part and section | XML for that requested snapshot and scope. A section also requires an explicit part. |
| Annual CFR | Year, title and volume; optional section | GovInfo volume or section XML. Requested year and printed revision remain separate. |
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

uv run --frozen python -m examples.cfr_capture ecfr-bulk \
  --title 1 --max-bytes 2097152 --output /tmp/ecfr-bulk-capture

uv run --frozen python -m examples.cfr_capture ecfr-titles \
  --max-bytes 65536 --output /tmp/ecfr-titles-capture
```

The example writes `receipt.json` and original XML or JSON. The eCFR API requires
compression: for gzip responses it retains both `response.xml.gz` (received
payload) and `response.xml` (decoded XML), with separate hashes and byte counts.
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
native_fields = result.identity  # Printed facts, warnings and identity basis.
requested_scope = result.selection
```

Use `acquire_annual(AnnualCfrSelection(...))`, `acquire_ecfr_bulk(title)` or
`acquire_ecfr_titles()` for the other routes. Pure validators accept retained
XML plus the expected selection and final URL for offline checks.

## Read dates and identity honestly

`identity_basis` identifies native XML fields and fields supported only by the
exact response URL. A subset may omit its title; an annual volume may omit its
volume number. Those native fields remain `None`.

The requested API date is not an amendment date. Likewise, an annual URL year
does not prove the body's printed revision. A recognized front-matter revision
year that differs from the request emits
`requested-edition-differs-from-printed-revision`. Both values remain available;
the capture alone cannot explain the discrepancy.

For example, on September 12, 2026, the annual Title 1 volume returned 2023
front matter and running headers through the 2025 route. The 2023 and 2025 bulk
URLs returned byte-identical XML. SpicyDocs preserves that observation and does
not label it a verified 2025 edition. Amendment dates alone trigger no warning.

## Bounds and downstream work

- Every operation requires a byte allowance, capped at 256 MiB. For gzip,
  received and decoded bytes each obey that allowance. Per-call `max_bytes`
  can narrow the client allowance.
- Whole-title validation scans XML without building a full tree. It refuses
  entities, DTDs, excessive nesting, malformed XML and contradictory requested
  identity. A timeout limits transport waits, not total operation duration.
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
