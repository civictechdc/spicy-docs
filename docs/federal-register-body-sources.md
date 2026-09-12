# Federal Register body sources and acquisition

`spicy_docs.sources.federal_register.body_acquisition` acquires an explicitly
selected GovInfo body, checks identity, and returns exact bytes plus observed
response facts. Install `spicy-docs[acquisition]`. You can retain or process the
result directly without a second download, source release, or dataset run.

Standard-library `body_sources` derives publisher XML/text locators and validates
already fetched GovInfo bytes. Publisher XML/text acquisition remains unqualified.
The caller selects a route; DocSpec owns dataset candidate preference.

## Acquire a selected GovInfo body

```python
from spicy_docs.sources.federal_register.body_acquisition import (
    GovInfoBodyAcquirer,
    GovInfoBodyBudget,
)

budget = GovInfoBodyBudget(
    max_requests=4,
    max_body_bytes=8 * 1024 * 1024,
    max_mods_bytes=16 * 1024 * 1024,
    timeout_seconds=30,
    min_request_interval_seconds=0.4,
)
with GovInfoBodyAcquirer(budget=budget) as client:
    result = client.acquire(
        document_number="X98-10603",
        publication_date="1998-06-03",
        route="mods-start-page",
        start_page=30359,
    )

body = result.body.body
digest = result.body.sha256
identity = result.identity
```

| Route | Requests before retries | Identity retained |
| --- | --- | --- |
| `granule` (omit `start_page`) | One known granule | Requested identity and printed document marker |
| `mods-start-page` | Issue Metadata Object Description Schema (MODS) XML, then the unique granule matching `start_page` | FederalRegister.gov number, resolved GovInfo `accessId`, and actual printed marker, kept separate; both captures returned |

A failed route never automatically starts another. Apply these bounds:

- Every attempt, including retries and MODS/body requests, consumes `max_requests`.
- Transport failures and HTTP 429/5xx retry with bounded exponential backoff.
  Other statuses and identity failures stop immediately; redirects are refused.
- HTTP 401/403 raises `CredentialRefusedError`. Stop the operation rather than
  continuing with another route or record.
- Request-start pacing applies across sequential acquisitions and retries on one
  client. Zero disables it. Timeout bounds transport waits, not total duration.
  These caller settings are not GovInfo rate-policy claims.
- Use one client sequentially and close it. Injected HTTPX transports must preserve
  streaming and add no hidden requests or authentication.
- Each response bound must be positive and at most 24 MiB. Acquisition requests
  identity encoding, refuses other encodings, checks stated length, and bounds
  accumulated bytes through EOF. HTTPX may obtain extra transport bytes to detect
  overflow; this limits retained bytes, not wire traffic or transport buffering.
- No partial body becomes exact evidence. Streams close on success and refusal.

The result includes route, effective budget, attempts, identity, and complete
responses: requested/final URL, status, content type, observation time, bytes,
size, and qualified SHA-256. To store a capture, pass its `sha256`, `byte_size`,
and `[body]` to `SourceNativeBlobStore.put_blob`; retain source facts beside the
returned reference.

`uv run python examples/govinfo_body.py` uses an injected local transport for two
synthetic requests, retaining MODS/body bytes and `capture.json`. The JSON is an
example report, not a sealed release receipt. For installed-wheel testing, copy
`examples/fixtures/govinfo/` beside the script.

## Refused evidence

Errors preserve the source exception and attach `refused_response` (`RefusedResponse`):

| Condition | Retained response |
| --- | --- |
| Complete bounded body fails identity, MODS, or ordinary HTTP status check | Exact bytes, including empty bytes |
| Oversize, unsupported transport, credential refusal, or exhausted retries | May have no captured body |
| Request skipped because total budget is exhausted | `before-request` / `request-budget-exhausted`; no attempted fetch implied |

The same error's `body_acquisition` retains route, original arguments, budget,
and consumed attempts. The caller owns persistence. Context identifies the active
offending response, not all retry bodies; a failed granule never labels earlier
successful MODS as the refused response. Refusal returns no release or success result.

## Why each rule survived or did not

- **Check identity before deriving sibling URLs from `body_html_url`.** XML/text siblings
  require the expected host, path, date, and document number. Global replacement
  could derive a plausible link for the wrong record. Pre-2000 XML absence did
  not establish body absence.
- **Use date and document number for GovInfo granule addresses.** This source
  rule recovered a measured publisher gap; the helper emits an unranked candidate.
- **Validate final URL, error-page marker, and `[FR Doc No: ...]`.** GovInfo can
  return 200 for missing granules. The old 44,165-byte error size was one template
  observation, not an identity rule. MODS alternates must print the resolved `accessId`.
- **Accept split-number bases narrowly.** A number such as `97-26440-2` may print
  its unsuffixed base. This exception covers the measured three-part numeric
  shape, not arbitrary trailing digits.
- **Resolve synthetic `X` numbers through MODS start pages.** Preserve the
  original number and separate `accessId`. Refuse zero/multiple matches,
  malformed/oversized XML, and DTD-bearing evidence.
- **Keep candidate selection in DocSpec.** A fixed XML → text → GovInfo cascade
  would turn an availability observation into runtime policy. SpicyDocs acquires
  only the explicitly selected supported route.
- **Keep text-agreement checks in SpicySearch Validation.** Recovered-term agreement
  between publisher text and GovInfo does not establish acquisition identity.
- **Use current caller bounds and shared storage.** Historical 0.4-second,
  three-worker tuning and ad hoc ledgers were campaign choices. Meter request
  starts; retain bounds and source facts without restoring weaker duplicate
  download/publication loops.

## Bounds and handoff

The pure `body_sources` helpers make zero network requests and filesystem writes.
For URL length `U`, granule bytes `B`, and MODS bytes `M`:

| Operation | Time | Auxiliary/output space |
| --- | --- | --- |
| Locator derivation | `O(U)` | `O(U)` output |
| Granule validation | `O(B)` | `O(U)` auxiliary |
| MODS resolution | `O(M)` | `O(D + A)` auxiliary: XML depth `D`, largest retained `start`/`accessId` value `A` |

Byte parsers reject payloads beyond caller-supplied positive bounds.

DocSpec D44 still owns its adapter: candidate choice, experiment bounds, passing
captured bytes into its fetch stream, and retaining identity/MODS proof. Current
fetcher metadata has no general slot for those proof facts; that integration
must qualify their retention. S19 supplies the source operation, not D44 adoption.
