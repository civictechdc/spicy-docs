# GAO product pages

Capture exact HTML for named product IDs, preserving each page's one literal
publisher topic and capture metadata. This release covers those products,
not the GAO catalog or linked report files. It emits no attachment renditions.

## Scope and evidence

- The query contains only sorted, distinct `productIds`, at most 1,000.
  The [CLI](../cli.md#publish) accepts repeated `--product-id` values and requires
  `ZYTE_TOKEN` in the environment.
- Zyte raw HTTP capture is bounded to 8 MiB per HTML body and 1 GiB total HTML.
- A response must identify the requested GAO URL, have an accepted status and
  HTML content type, and contain valid UTF-8.
- HTML must declare exactly the expected canonical URL and one topic anchor
  within `views-field-field-topic`. Navigation links do not count.
- Duplicate fields, nested labels, unsafe slugs, and incomplete markup refuse
  acquisition. A missing topic is a refusal, not null or accepted-empty input.

Each deterministic ZIP contains canonical `manifest.json` and exact
`product.html`. Replay checks members, ZIP metadata, body size/digest, capture
facts, URL, and extraction, proving each requested product appears once with
no extras. Labels have HTML character references decoded and outer whitespace
trimmed; the original HTML remains inspectable.

## Read a topic and its evidence

`SourceNativeReleaseReader.iter_records()` exposes `record.publisherTopic`
(`href`, `label`, `slug`), `canonicalUrl`, `requestedUrl`, `resolvedUrl`,
`htmlSha256`, and `htmlByteLength`. Any syntactically valid topic is preserved;
there is no RefSpec membership check or allowed-topic list.

After opening a release with its expected pin and accepted verifier identity:

```python
from spicy_docs.sources.gao.native import parse_gao_product_page_response

evidence = reader.record_evidence("gao-26-107693")
if evidence is not None:
    pack = reader.read_evidence(evidence["evidenceBlobRef"])
    response = parse_gao_product_page_response(pack)
    print(response["results"][0]["publisherTopic"])
```

This reads the selected successful observation's ZIP; the parser validates its
manifest and HTML. See [reader checks and bounds](../source-native-outcomes.md#inspect-record-evidence).

The [synthetic fixtures](../../examples/fixtures/gao/README.md) cover matching,
unexpected, and missing labels. Examples report exact input digests and retained
output references:

```sh
uv run --frozen python examples/offline_release.py --case matching
uv run --frozen python examples/offline_release.py --case unexpected
uv run --frozen python examples/offline_release.py --case missing
```

The first two publish and verify. The missing case reports the expected refusal
and retained target-body reference; unrelated errors still fail the example.
These fixtures do not establish live GAO availability. A literal label alone
establishes no requirement or applicability; any catalog filter or processor
belongs to the optional sibling DocSpec [D51 example](../../../DocSpec/docs/dataset-experiments-todo.md#d51).

## Diagnose a refused response

A failed URL, status, content type, UTF-8, topic, or markup check aborts acquisition.
During publication, `failedAcquisition` points to bounded exact target bytes in
the blob store, with canonical requested URL and failure stage. Inspect them
offline using [CLI recovery](../cli.md#output-and-failures); they form no partial
release or claim of source absence.

The same 8 MiB/page and 1 GiB/acquisition bounds apply to diagnostic retention:

| Condition | Evidence result |
| --- | --- |
| Fully received empty body | Exact zero-byte evidence |
| Oversize body | `response-byte-limit` or `acquisition-byte-limit`, with observed size; no truncated capture |
| No target bytes reached the adapter | `transport-unavailable` |
| Target data reflects a known transport credential | `credential-suppressed` |
| Unsupported fetch result | No captured body |

Diagnostic context contains target bytes, source-generated requested URL, fixed
media type, stage, and capture limit. It excludes Zyte provider JSON, auth headers,
and untrusted response URL/header metadata. Direct `iter_gao_product_pages()`
calls attach `refused_response` to the original exception in memory; the shared
publisher persists it and supplies failed-run references.

## Change and check

Owners: [`native.py`](../../src/spicy_docs/sources/gao/native.py) for capture/parsing,
[`profile.py`](../../src/spicy_docs/sources/gao/profile.py) for composition,
and [`zyte.py`](../../src/spicy_docs/sources/zyte.py) for transport, with
[`transport/zyte.py`](../../src/spicy_docs/transport/zyte.py) wrapping the same
adapter for any acquirer that takes an injected `httpx` transport.

```sh
uv run --frozen pytest -q tests/test_gao_product_pages_source_native.py tests/test_gao_source_native_cli.py tests/test_gao_refused_responses.py tests/test_zyte_transport.py
uv run --frozen python examples/offline_release.py
```

Keep field-versus-navigation fixtures: an arbitrary topic link does not prove
the publisher's topic field. The offline example reads verified records and
evidence through public APIs.
