# Federal Register acquisition

The Federal Register profile captures API responses for an inclusive publication
date range. It publishes the records found by matching consecutive crawls and
retains the exact responses for offline replay. Its `observed-crawl` claim
describes that bounded observation; matching crawls do not establish an
authoritative complete snapshot of the publisher.

## Scope and evidence

The Python query contains exactly `publishedFrom` and `publishedThrough` as
canonical `YYYY-MM-DD` dates. The [CLI](../cli.md#publish) accepts `--since` and
`--until`. Requests use the fixed HTTPS API endpoint, the declared field set,
and bounded pages. Request parsing reconstructs the initial URL exactly; cursor
validation refuses off-host URLs, credentials, fragments, and unsafe shapes.

Acquisition starts with windows of at most 90 days. A response reporting 10,000
or more results becomes retained, excluded probe evidence. The iterator splits
that window and tries its two halves. A capped one-day window refuses the run.
Included windows must agree on counts, pagination, and the records observed.
The profile requires two adjacent matching traversals, with at most three
traversals available to find that agreement.

Response parsing rejects duplicate JSON keys, floating-point values, unknown
response fields, and malformed inventory. Classification preserves accepted
source fields and checks each record's date against its actual request window.
Exact response bytes survive even when their records are excluded or discarded
during selection.

## Identity, diagnostics, and output

Identity is the pair `(document_number, publication_date)`. The wrapper encodes
it as `number@date`; both original fields remain unchanged in the source record.
A reused number on a different date remains a separate record. Repeated
observations of one pair collapse only when their canonical record digests
agree. A substantive tie refuses publication.

Malformed Regulation Identifier Numbers (RINs) produce field diagnostics while
retaining the original value. A record that fails classification or falls outside
its request window becomes a deterministic failure-ledger row; publication can
still complete, including with zero successful records. Invalid page evidence,
unsafe cursors, or inconsistent acquisition coverage refuse the release.
The rendition index records `body-html`, `html`, and `pdf`, including
explicit null locators. These rows describe publisher locators; acquisition
does not download those bodies or attest to their bytes. The
[body-source guide](../federal-register-body-sources.md) explains later route
selection.

Acquisition policy `1.2` and requested-field policy `1.0` serve different jobs.
The deferred `correction_of` field is still outside the accepted field set.
The public-table projection also uses compound identity; see
[the decisions](../decisions.md#federal-register-identity-and-fields-version-separately)
before changing either policy.

You can stop after publishing and inspecting these metadata records. Read them
through `SourceNativeReleaseReader`, export the supported Federal Register
public table, or supply the source release to a dataset application. Downloading
the listed bodies is a separate step. See [source workflows](../source-workflows.md).

## Change and check

Source behavior lives in
[`sources/federal_register/native.py`](../../src/spicy_docs/sources/federal_register/native.py)
and [`sources/federal_register/profile.py`](../../src/spicy_docs/sources/federal_register/profile.py).
Run the acquisition and request-window tests for URL, pagination, or coverage
changes; run selection, reading, and public-table tests for identity changes:

```sh
uv run --frozen pytest -q tests/releases/test_acquisition.py tests/test_federal_register_request_window.py
uv run --frozen pytest -q tests/releases/test_selection.py tests/releases/test_reading.py tests/test_federal_register_public_table.py
```

Use a small captured or explicitly synthetic response that demonstrates the
publisher condition. Keep evidence replay independent of the live fetcher.
