# Federal Register body sources and acquisition

`FederalRegisterBodyAcquirer` prefers full-document publisher XML. If XML returns
404 or 410, it uses the chosen GovInfo HTML route and retains the unavailable XML
response. Other failures stop acquisition. Install `spicy-docs[acquisition]`.

The result contains exact bytes, checked document identity, and response facts.
Retain or process it directly without another download, release, or dataset run.
This body operation is separate from publishing Federal Register metadata.

## Acquire a body

```python
from spicy_docs.sources.federal_register.body_acquisition import (
    FederalRegisterBodyAcquirer,
    FederalRegisterBodyBudget,
)

budget = FederalRegisterBodyBudget(
    max_requests=4,
    max_body_bytes=8 * 1024 * 1024,
    max_mods_bytes=16 * 1024 * 1024,
    timeout_seconds=30,
    min_request_interval_seconds=0.4,
)
with FederalRegisterBodyAcquirer(budget=budget) as client:
    result = client.acquire(
        document_number="2026-18670",
        publication_date="2026-09-11",
    )  # format="prefer-xml" is the default

body = result.body.body
digest = result.body.sha256
identity = result.identity
```

| `format` | Behavior |
| --- | --- |
| `prefer-xml` (default) | Try publisher XML; use HTML only after a complete, bounded XML 404/410 response. |
| `xml` | Require publisher XML. No HTML fallback. |
| `html` | Request GovInfo HTML directly. |
| `txt` | Request publisher text directly, including its HTML-wrapped text rendition. |

`html_route="granule"` requests the known GovInfo document. Use
`html_route="mods-start-page", start_page=30359` when the document needs an issue
Metadata Object Description Schema (MODS) lookup. That route preserves the
original number, resolved `accessId`, and printed marker separately. It does
not run when XML succeeds.

XML validation requires a native document root (`RULE`, `PRORULE`, `NOTICE`, or
`PRESDOCU`) and one matching `FRDOC` number. Presidential documents may split the
marker across `FRDOC` and its following `FILED` field. Publication date is bound
to the exact canonical URL; the filing date is a separate fact. DTDs, declared
entities, malformed XML, ambiguous markers and wrong identities are refused.
This checks identity and XML shape, not complete publisher-schema conformance.

Text validation checks the canonical URL and `[FR Doc No: ...]` header, including
the same narrow split-number rule as GovInfo HTML. It accepts `text/plain` or
`text/html` because the text route can return an HTML `<pre>` wrapper. The result
keeps those exact bytes. Its footer's filing number/date remain separate from the
header and requested publication date. Text requests use `route="publisher-text"`
and refuse MODS/start-page options; text failures stop without a format fallback.

A 200 HTML challenge page, empty body, wrong content type, or invalid XML does
not trigger fallback. Neither do access refusal, redirect, transport failure,
exhausted retries or byte limits.

Apply these bounds:

- Every XML, text, MODS, HTML and retry attempt consumes the same `max_requests`.
  One request can suffice for XML; fallback stops if the budget is exhausted.
- Transport failures and HTTP 429/5xx retry with bounded exponential backoff.
  Except for the XML 404/410 fallback above, other status failures stop
  immediately. Identity failures stop, and redirects are refused.
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

The result names `requested_format`, actual `format` and `route`, effective
budget, attempts, identity, and complete responses: requested/final URL, status,
content type, observation time, bytes, size, and qualified SHA-256. To store a
capture, pass its `sha256`, `byte_size`,
and `[body]` to `SourceNativeBlobStore.put_blob`; retain source facts beside the
returned reference. HTML fallback also returns `unavailable_xml`: preserve that
response to explain why XML was not selected.

Try both paths offline:

```sh
uv run --frozen python examples/federal_register_body.py
uv run --frozen python examples/federal_register_body.py --case html-fallback
```

The example retains all used responses and `capture.json`, including the XML 404
in the fallback case. The JSON is an example report, not a sealed release receipt.
For installed-wheel testing, copy both `examples/fixtures/federal-register/` and
`examples/fixtures/govinfo/` beside the script.

## Read the printed List of Subjects

The core wheel provides `spicy_docs.sources.federal_register.list_of_subjects`:

```python
from spicy_docs.sources.federal_register.list_of_subjects import (
    extract_blocks_from_xml_body,
    inspect_text_body,
    split_printed_atoms,
)

blocks = extract_blocks_from_xml_body(xml_text)
text_blocks, printed_headings = inspect_text_body(publisher_text)
atoms = [split_printed_atoms(block) for block in blocks]
```

Pass decoded retained text; acquisition and identity validation stay separate.
XML reading takes term paragraphs inside `LSTSUB`, excluding headings. Text reading
handles the observed fused headings, wrapped lists, agency labels and page breaks.
Results preserve paragraph order and repeated blocks. They normalize whitespace
and markup; keep the original body, encoding and source identity alongside them.
The reader returns strings, not exact source offsets or vocabulary concept IDs.

Each text heading scans at most 200 paragraphs and 120,000 characters. The separate
heading scan uses `SUBHEADING_SCAN_GAP=2`. `unread_subheading_candidate` flags more
printed CFR headings than recovered blocks; empty parts can also trigger it.
Headings omitting `CFR` are outside that diagnostic. These inherited bounds and
known limits are preserved by the transferred SpicySearch regression cases.

`split_printed_atoms` separates commas/semicolons, removes list conjunctions and
stops at the sentence boundary while preserving known abbreviation shapes. Atoms
are not resolved terms: a vocabulary label may contain commas. SpicySearch owns
joining those atoms against its vocabulary, spelling folds and fidelity scoring.

## Refused evidence

Errors preserve the source exception and attach `refused_response` (`RefusedResponse`):

| Condition | Retained response |
| --- | --- |
| Complete bounded body fails identity, MODS, or ordinary HTTP status check | Exact bytes, including empty bytes |
| Oversize, unsupported transport, credential refusal, or exhausted retries | May have no captured body |
| Request skipped because total budget is exhausted | `before-request` / `request-budget-exhausted`; no attempted fetch implied |

The same error's `body_acquisition` retains route, original arguments, budget,
and consumed attempts. Its `unavailableXml` holds the XML capture if a subsequent
HTML operation failed. The caller owns persistence. Context identifies the active
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
- **Prefer XML while keeping failures visible.** The caller's format preference
  selects XML before HTML; only explicit XML 404/410 permits fallback. This source
  operation stays usable independently. DocSpec chooses dataset items and processing.
- **Keep text-agreement checks in SpicySearch Validation.** Recovered-term agreement
  between publisher text and GovInfo does not establish acquisition identity.
- **Use current caller bounds and shared storage.** Historical 0.4-second,
  three-worker tuning and ad hoc ledgers were campaign choices. Meter request
  starts; retain bounds and source facts without restoring weaker duplicate
  download/publication loops.

## Bounds and handoff

The pure `body_sources`, `body_xml` and `body_text` helpers make no network requests or file
writes. For URL length `U`, body bytes `B`, and MODS bytes `M`:

| Operation | Time | Auxiliary/output space |
| --- | --- | --- |
| Locator derivation | `O(U)` | `O(U)` output |
| Granule validation | `O(B)` | `O(U)` auxiliary |
| Publisher XML validation | `O(B)` | XML depth plus retained `FRDOC`/`FILED` text; no document tree |
| MODS resolution | `O(M)` | `O(D + A)` auxiliary: XML depth `D`, largest retained `start`/`accessId` value `A` |

Byte parsers reject payloads beyond caller-supplied positive bounds.

DocSpec D44 still owns its adapter: dataset candidate choice, experiment bounds,
passing captured bytes into its fetch stream, and retaining identity/MODS proof. Current
fetcher metadata has no general slot for those proof facts; that integration
must qualify their retention. S19 supplies the source operation, not D44 adoption.
