# Federal Register acquisition

Capture exact API responses for inclusive publication dates, then publish the
records from two matching consecutive crawls. The `observed-crawl` claim covers
that observation, not an authoritative publisher-wide snapshot.

## Scope and evidence

- Python requires exactly `publishedFrom` and `publishedThrough`, as canonical
  `YYYY-MM-DD` dates. The [CLI](../cli.md#publish) uses `--since` and `--until`.
- Requests use the fixed HTTPS endpoint, declared fields, and bounded pages.
  Replay reconstructs the initial URL exactly. Cursor checks refuse off-host
  URLs, credentials, fragments, and unsafe shapes.
- Initial windows span at most 90 days. A response reporting at least 10,000
  results becomes retained, excluded probe evidence; acquisition splits the
  window and retries both halves. A capped one-day window refuses the run.
- Included windows must agree on counts, pagination, and observed records.
  At most three traversals are available to find two adjacent matching ones.
- Parsing rejects duplicate JSON keys, floats, unknown response fields, and
  malformed inventory. Each record's date must match its actual request window.
  Exact bytes remain available for excluded probes and discarded observations.

## Identity, diagnostics, and output

Identity is `(document_number, publication_date)`, encoded as `number@date` in
the wrapper. Original fields remain unchanged. Reused numbers on different dates
remain separate. Repeated observations collapse only when canonical record
digests agree; a substantive tie refuses publication.

| Condition | Result |
| --- | --- |
| Malformed Regulation Identifier Number (RIN) | Field diagnostic; original value retained |
| Classification failure or record outside its request window | Deterministic failure-ledger row; publication may succeed with zero accepted records |
| Invalid page evidence, unsafe cursor, or inconsistent coverage | Release refused |

Renditions list `body-html`, `html`, and `pdf`, including explicit null locators.
They describe links, not downloaded bodies. The separate
[body API](../federal-register-body-sources.md) prefers publisher XML, with direct
or MODS-resolved GovInfo HTML after XML 404/410. Callers can also require XML or
request HTML explicitly. Plain-text helpers supply locators only.
Stream admitted metadata with `SourceNativeReleaseReader` or export its public
table. See [output choices](../source-workflows.md).

Policy `1.1` introduced compound identity; current `1.2` adds observed-crawl
coverage limits. Both retain the same 22 `DOCUMENT_FIELDS`. Requests and replay
require that field set and canonical URL. `correction_of` was never added.
The public table also uses compound identity. Read the
[identity and field decision](../decisions.md#federal-register-identity-and-fields-version-separately)
before changing either.

## Change and check

Owners: [`native.py`](../../src/spicy_docs/sources/federal_register/native.py)
and [`profile.py`](../../src/spicy_docs/sources/federal_register/profile.py).
Use the first check for URL, pagination, or coverage changes; use the second for
identity changes:

```sh
uv run --frozen pytest -q tests/releases/test_acquisition.py tests/test_federal_register_request_window.py
uv run --frozen pytest -q tests/releases/test_selection.py tests/releases/test_reading.py tests/test_federal_register_public_table.py
```

Use small captured or explicitly synthetic responses. Keep replay independent
of the live fetcher.
