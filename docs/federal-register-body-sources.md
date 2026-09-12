# Federal Register body sources and acquisition

SpicyDocs can acquire and check an explicitly selected GovInfo Federal Register
body. `spicy_docs.sources.federal_register.body_acquisition` returns exact bytes,
observed response facts and the source identities that those bytes support.
The caller can retain or process them without downloading them again. Install
`spicy-docs[acquisition]` to use this HTTPX-based API.

The standard-library-only `body_sources` module also derives publisher XML/text
locators and checks already fetched GovInfo bytes. Publisher XML/text acquisition
is not yet qualified here. A caller selects a route; DocSpec owns preference
among candidates when building a dataset.

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

For an ordinary known GovInfo granule, select `route="granule"` and omit
`start_page`. That route makes one request before any retries. The explicit
`mods-start-page` route first reads the issue's Metadata Object Description
Schema (MODS) XML, resolves one constituent by start page, and fetches its
granule. It returns both complete captures and keeps the FederalRegister.gov
number, GovInfo access ID and actual printed document marker separate. A
failed direct lookup never automatically starts a MODS or publisher fallback.

Every attempt, including retries and both MODS/body requests, counts against
`max_requests`. The client retries transport failures and HTTP 429/5xx using
the shared bounded exponential backoff. Other statuses and source identity
failures stop immediately. Redirects are refused without following them.
HTTP 401/403 raises the shared `CredentialRefusedError`; the caller must stop
its operation rather than continue with another route or record.

The required request-start interval applies across sequential acquisitions on
the same client, including retries. A zero interval explicitly disables this
pacing. The timeout bounds transport waits; it is not a total operation
deadline. These are caller choices, not a statement of GovInfo's current
rate policy. Use one client sequentially and close it, normally with `with`.
Injected HTTPX transports support offline operation; they must preserve the
streaming interface and must not add hidden requests or authentication.

Each response has a required positive byte bound, at most 24 MiB. Acquisition
requests identity content encoding, rejects other encodings, checks any stated
length, and bounds its accumulated bytes while reading through EOF. HTTPX's
chunking may obtain more bytes from a transport to detect overflow; the bound
describes retained response bytes, not wire traffic or transport buffering.
No partial body is returned as exact evidence. Response streams close on both
success and refusal.

The result contains route, effective budget, attempt count, source identity,
and complete response values with requested/final URL, status, content type,
observation time, exact bytes, byte length and qualified SHA-256. It does not
publish a source-native release or start a dataset run. You may stop with this
source-only result. To retain bytes, pass each capture's `sha256`, `byte_size`
and `[body]` to `SourceNativeBlobStore.put_blob` and retain its source facts
alongside the stored references.

Run `uv run python examples/govinfo_body.py` for a network-free example that
retains synthetic MODS and body bytes plus `capture.json`. Its two requests go
to an injected local transport. The JSON is an example report, not a sealed
release receipt. When copying the script for installed-wheel testing, copy
`examples/fixtures/govinfo/` beside it too.

## Refused evidence

Errors preserve their source exception and carry `refused_response`, the
existing `RefusedResponse` value. A complete bounded body that fails an
identity, MODS or ordinary HTTP status check remains available as exact bytes,
including an exact empty response. Oversize, unsupported transport, credential
refusal and exhausted retry cases can have no captured body. A request skipped
because its total budget is exhausted is explicitly `before-request` with
`request-budget-exhausted`; it is not represented as an attempted fetch.

`body_acquisition` on the same error records selected route, original source
arguments, budget and consumed attempts. These values remain in caller memory;
the caller decides how to store a failed run. They retain the active offending
response rather than a history of all retry bodies, and a failed granule request
does not mislabel previously successful MODS bytes as the refused response.
No release or success result is returned after refusal.

## Why each rule survived or did not

| Prior behavior | Decision | Why |
| --- | --- | --- |
| Derive publisher XML and text siblings from `body_html_url` | Retain, with stricter identity checks | The publisher exposes real sibling paths, and the pre-2000 corpus showed that XML absence did not mean body absence. The old global string replacement could derive a plausible URL from the wrong record; the new helper requires the host, path, date, and document number to agree first. |
| Derive a govinfo FR granule from publication date and document number | Retain | This is a stable source-addressing rule and recovered a measured publisher gap. The helper emits the candidate without ranking it. |
| Treat a 44,165-byte response as a govinfo soft 404 | Do not retain as an invariant | That size described one observed error-page version. A later valid document could have the same size, and a changed error template would bypass the check. The durable checks are the final URL, error-page marker, and printed FR document marker. |
| Require `[FR Doc No: ...]` in a govinfo body | Retain and strengthen | govinfo can return HTTP 200 for a missing granule. The marker binds the bytes to the requested identity. A MODS-resolved alternate must now print the resolved `accessId`; the old alternate branch checked only that it was not the known error page. |
| Accept the base marker for a split number such as `97-26440-2` | Retain narrowly | FederalRegister.gov created a disambiguation suffix while the printed document kept the unsuffixed number. The new rule accepts a base only for the measured three-part numeric shape, not for every string ending in digits. |
| Resolve a synthetic `X` number by matching `start_page` in the issue MODS | Retain and strengthen | This preserves a real cross-source identity difference. The streaming parser keeps the FederalRegister.gov number separate from the govinfo `accessId` and refuses zero, multiple, malformed, oversized, or DTD-bearing evidence instead of taking the first regex match. |
| Use `.xml` then `.txt` then govinfo as a fixed runtime cascade | Leave selection to DocSpec policy | The availability observation is valuable, but candidate preference is a DocSpec decision. SpicyDocs exposes locators without ranking them and acquires the explicitly selected, supported GovInfo route. |
| Prove publisher text and govinfo agreement | Keep in SpicySearch Validation | Agreement measures whether two carriers yield the same recovered terms; it does not establish source acquisition identity and must not become a runtime shortcut. Copying the check here would create a second validation implementation. |
| Sleep 0.4 seconds with three workers | Do not retain as source semantics | The useful performance lesson is to meter request starts rather than add response latency to a post-request sleep. The exact interval and worker count came from one host/client campaign and can drift. A future DocSpec transport policy must state and receipt its own current bounds. |
| Append failures and digests to ad hoc ledgers, rescan output directories, and write manifests directly | Do not retain | The code arose from a resumable research campaign. SpicyDocs' shared acquisition and publication path provides immutable members, exact digests, bounded reads, and explicit failures. Restoring the loop would duplicate those mechanisms with weaker arrival evidence. |

## Bounds and handoff

For URL length `U`, granule bytes `B`, and MODS bytes `M`:

- locator derivation takes `O(U)` time and `O(U)` output space;
- granule validation takes `O(B)` time and `O(U)` auxiliary space;
- MODS resolution takes `O(M)` time and `O(D + A)` auxiliary space, where
  `D` is XML nesting depth and `A` is the largest retained `start` or
  `accessId` value;
- byte parsers reject a payload beyond the caller-supplied positive bound;
- every helper performs zero network requests and zero filesystem writes.

DocSpec D44 still owns its fetcher adapter: selecting a candidate, setting an
experiment's bounds, passing these already captured body bytes into its existing
fetch stream, and retaining source identity plus MODS proof. Its current fetcher
metadata has no general slot for those extra proof facts, so that integration
must choose and qualify their supported retention. S19 supplies the source
operation; it does not claim D44 adoption or require a second download or a
second SpicyDocs publication before use.
