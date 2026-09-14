# GAO report files

Name one GAO product; capture the report file the publisher stores for it.
This route is keyless. It is the file behind a product, not the product page
([GAO product pages](gao.md), captured through Zyte) and not the listing
([GAO reports feed](listings.md)).

## Two hosts, one publisher

`www.gao.gov` refuses non-browser clients. Probed on 2026-09-14 with a plain
client, `https://www.gao.gov/products/gao-26-107693` and
`https://www.gao.gov/assets/gao-26-107693.pdf` both answered `403 Access
Denied` from an Akamai edge. The file host answered every request:

| Locator | Answer on 2026-09-14 |
| --- | --- |
| `https://files.gao.gov/assets/{product-id}.pdf` | `200`, `application/octet-stream`, `%PDF-1.7` |
| `https://files.gao.gov/assets/{product-id}-highlights.pdf` | `200`, `application/octet-stream`, `%PDF-1.7` |
| `https://files.gao.gov/reports/{PRODUCT-ID}/index.html` | `200`, `text/html`, for products with an online report |

Each host spells the product its own way, and the file host is case-sensitive:
the report directory is uppercase (`GAO-26-107693`) and the asset filename is
lowercase (`gao-26-107693.pdf`). The other case answers `403` on both. The
selection key stays the lowercase product ID that `gao_product_url` validates,
so one identifier drives the feed, the product page and the file.

## The PDF is the file every product has

Of the 47 GAO product pages retained on 2026-08-22, **47 link
`/assets/{product-id}.pdf`**, 27 link `-highlights.pdf`, and **26 link the
`files.gao.gov` index**. Requesting the index for a product whose page omits it
answered `403`, so the online report genuinely does not exist for those
products rather than merely going unlinked. `acquire_report_pdf` is therefore
the route that always applies; `acquire_report_file` reads the online report
first and is only for products that have one.

## A 403 from the file host is not absence

`files.gao.gov` is an S3 origin behind CloudFront. It answers the same
`AccessDenied` document for an object that does not exist, for a path spelled
in the wrong case, and for anything else it will not serve. The shared
transport turns any `401`/`403` into `CredentialRefusedError`, aborts, and
retains no bytes. Record it as a refusal that ended the operation. It is never
a zero, an absence, or a reason to try another spelling.

`404` and `410` raise `GaoReportFileUnavailableError` with the capture
attached, as elsewhere in SpicyDocs. This host was not observed answering
either.

## Identity comes from the bytes

The file host states `application/octet-stream` for PDF bytes, so the media
type alone proves nothing; it is checked against
`application/pdf, application/octet-stream` and the bytes carry the proof:

- the body begins `%PDF-` and its version is kept as the publisher wrote it;
- `%%EOF` appears in the last 1,024 bytes, which ISO 32000-1 requires of a
  complete file and a truncated capture cannot satisfy;
- the final URL equals the locator, and `Content-Length` agrees with what
  arrived.

Any `200` that fails one of these is refused with its exact bytes attached to
the error as `refused_response` — an HTML challenge page, an HTML index served
where a PDF was requested, or a body cut short.

The online report proves its own identity before its bytes are trusted: it must
link the report PDF at the locator this module builds, and it must link its
canonical product page at `https://www.gao.gov/products/{product-id}`. All four
retained indexes do both, and each carries a `<title>` beginning with the
uppercase product ID; the title is preserved as the publisher wrote it, with
character references decoded and outer whitespace trimmed, and is not used as
an identity check.

## Use the route

```python
from spicy_docs.sources.gao.files import GaoReportFileAcquirer, GaoReportFileBudget

budget = GaoReportFileBudget(
    max_requests=3,
    max_index_bytes=8 * 1024**2,
    max_pdf_bytes=32 * 1024**2,
    timeout_seconds=60,
    min_request_interval_seconds=1.5,
)

with GaoReportFileAcquirer(budget=budget) as source:
    result = source.acquire_report_pdf("gao-26-107693")
    print(result.pdf.pdf_version, result.pdf_capture.byte_size, result.pdf_capture.sha256)
    # result.pdf_capture.body is the exact PDF; retain it in caller-owned storage.

    summary = source.acquire_report_pdf("gao-26-107693", rendition="highlights")
    online = source.acquire_report_file("gao-26-108641")
    print(online.index.title, online.index.pdf_url, online.request_count)
```

The byte bounds are explicit and each capture may only narrow them; the largest
of the four PDFs pinned on 2026-09-14 was 5,020,419 bytes, which says nothing
about the largest GAO publishes. Request counts reset per operation and
pacing persists for the life of the acquirer, as with every `SourceAcquirer`.
The acquirer takes an injected `httpx` transport, the way the product-page
source takes an injected fetcher, so the whole route is testable without the
network.

## Change and check

Owner: [`files.py`](../../src/spicy_docs/sources/gao/files.py).

```sh
uv run --frozen pytest -q tests/test_gao_files.py tests/test_gao_rss.py
```

Pinned bytes and their reductions are in
[`tests/fixtures/gao_files/README.md`](../../tests/fixtures/gao_files/README.md).
Every probe, its headers, and the parser run over the four complete retained
index bodies are in
`corpora/supply-2026-09-02/receipts/port-P04-gao-files-2026-09-14/`.
