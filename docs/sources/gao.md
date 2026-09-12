# GAO product pages

The GAO profile captures exact HTML for an explicitly named set of product IDs.
It preserves the publisher's one topic field and capture metadata in each
source record. The release covers those products; it makes no claim to enumerate
the GAO catalog or interpret a topic's meaning.

## Scope and evidence

The query contains only a sorted, distinct `productIds` list, with at most
1,000 IDs. The [CLI](../cli.md#publish) accepts repeated `--product-id` values
and requires `ZYTE_TOKEN` in the process environment. Live acquisition uses
Zyte raw HTTP with an 8 MiB limit per HTML body and a 1 GiB total HTML bound.

Each response must identify the requested GAO URL, return an accepted status
and HTML content type, and contain valid UTF-8. The HTML must declare exactly
the expected canonical URL and exactly one topic anchor inside the publisher's
`views-field-field-topic` field. Topic links in navigation or elsewhere on the
page do not count. Duplicate fields, nested topic labels, unsafe topic slugs,
and incomplete markup are refused.

The evidence ZIP contains canonical `manifest.json` and exact `product.html`
bytes with deterministic ZIP metadata. Replay checks the member set, metadata,
body digest and size, capture declarations, canonical URL, and topic extraction.
The profile proves that every requested product appears once and that no extra
product entered the capture.

The record retains the source URL, literal topic link and slug, topic label,
and capture details. HTML character references are decoded and outer label
whitespace is trimmed; the original HTML remains available to inspect that
extraction. This profile emits no attachment rendition rows.

## Read a topic and its evidence

`SourceNativeReleaseReader.iter_records()` exposes `record.publisherTopic` as
`href`, `label`, and `slug`, alongside `canonicalUrl`, `requestedUrl`,
`resolvedUrl`, `htmlSha256`, and `htmlByteLength`. A syntactically valid topic is
preserved even if it is unexpected by a downstream application. There is no
RefSpec membership check or allowed-topic list. A missing topic refuses source
acquisition; it does not become a null topic or an empty accepted release.

After opening the release under its expected pin and accepted verifier identity,
use the public reader to inspect the selected record's evidence:

```python
from spicy_docs.sources.gao.native import parse_gao_product_page_response

evidence = reader.record_evidence("gao-26-107693")
if evidence is not None:
    pack = reader.read_evidence(evidence["evidenceBlobRef"])
    response = parse_gao_product_page_response(pack)
    print(response["results"][0]["publisherTopic"])
```

`record_evidence()` returns the selected successful observation's existing
references, not every discarded observation. `read_evidence()` returns the
exact admitted ZIP after checking its role, size and digest; the GAO parser
validates that ZIP's manifest and original `product.html`. See
[evidence access and bounds](../source-native-outcomes.md#inspect-record-evidence).

The [retained topic inputs](../../examples/fixtures/gao/README.md) demonstrate a
matching label, an unexpected label, and a missing publisher field. They are
explicitly synthetic HTML, not live GAO captures. Each example reports its exact
input digest and retained output references:

```sh
uv run --frozen python examples/offline_release.py --case matching
uv run --frozen python examples/offline_release.py --case unexpected
uv run --frozen python examples/offline_release.py --case missing
```

The first two cases publish and verify a source release. The missing case reports
the expected refusal and retained target-body reference without publishing a
release. An unrelated error still fails the example. You can stop at those
source results. The [D51 example](../../../DocSpec/docs/dataset-experiments-todo.md#d51)
in an optional neighboring DocSpec checkout owns any catalog filter or processor
using them; that link requires the sibling checkout, but these source examples
do not. A literal label alone establishes
no requirements or applicability.

## Diagnose a refused response

A response that fails URL identity, status, content type, UTF-8, topic, or markup
checks still aborts acquisition. During publication, failed-run reporting
references the exact refused target bytes in the selected blob store; the CLI
includes the diagnostic references in `failedAcquisition`. These bytes are
separate from admitted records and do not produce a partial source release.
The report identifies the canonical requested product URL and the failure
stage. Retained HTML can be inspected offline to diagnose the original source
check without fetching the product again.

The same 8 MiB per-response and 1 GiB acquisition bounds apply to diagnostic
retention. A fully received empty body is exact zero-byte evidence. An oversized
body is not truncated and saved as though complete: the failure instead records
`response-byte-limit` or `acquisition-byte-limit`, with the observed body size.
When fetching fails before GAO receives target bytes, `transport-unavailable`
records that limitation. Zyte suppresses retention when target data contains a
known transport credential and reports `credential-suppressed`. An unsupported
fetch result carries no body.
Transport and source refusals remain errors, never evidence of source absence.

The diagnostic context retains only target bytes, a source-generated requested
URL, fixed media type, stage, and capture limitation. It carries no Zyte provider
JSON, authentication headers, or untrusted response URL/header metadata. Calling
`iter_gao_product_pages()` directly attaches this context to the original
exception as `refused_response`; the iterator does not persist it. The shared
publisher owns storage and discoverable failed-run references.

## Change and check

Acquisition and HTML parsing live in
[`sources/gao/native.py`](../../src/spicy_docs/sources/gao/native.py),
profile composition in
[`sources/gao/profile.py`](../../src/spicy_docs/sources/gao/profile.py), and
transport in [`sources/zyte.py`](../../src/spicy_docs/sources/zyte.py).

```sh
uv run --frozen pytest -q tests/test_gao_product_pages_source_native.py tests/test_gao_source_native_cli.py tests/test_gao_refused_responses.py tests/test_zyte_transport.py
uv run --frozen python examples/offline_release.py
```

The offline example supplies synthetic HTML and reads the preserved record and
evidence through public APIs after verification. Keep field-versus-navigation fixtures when changing the parser;
an arbitrary topic anchor is insufficient evidence of the publisher's topic.
