# Capture public laws and statute compilations

Give SpicyDocs a law's Congress, kind and number, or a compilation's file
identifier. It returns the exact GovInfo bulkdata XML, the native identity it
proved, and bounded HTTP evidence. Both collections are keyless and use United
States Legislative Markup (USLM), which the publisher labels beta.

This module is PLAW and COMPS only. A BILLS package's own USLM rendition
(`uslm/{id}.xml`, a bill's own text before it becomes law) is a different
route with a different identity shape — its root varies by bill type where a
law or compilation each has exactly one fixed root — and is fetched through
`sources/govinfo/bodies.py::PACKAGE_BODY_FORMATS["uslm"]` instead; see
[GovInfo package bodies](govinfo-bodies.md).

| Route | Required selection | What it supplies |
| --- | --- | --- |
| Public law | Congress, `public` or `private`, law number | One law's USLM XML. Native Congress, kind, number and citable form must match the request. |
| Statute compilation | Compilation file identifier | One act with its amendments folded in. The native `fileId` must match; the compiler's currency statement is kept as written. |
| Public law archive | Congress and kind | The publisher's zip for that folder. Every entry is validated against the identity its own file name declares. |
| Statute compilations archive | None | The whole-collection zip (about 81 MB), validated entry by entry. |

A compilation is the statutory counterpart of eCFR: the current text of an act
by its name. A law is the text as signed; most laws amend other laws, so their
text reads as instructions. Compilations state their own currency in
`currentThroughPublicLaw`, per act and in varied forms; an unamended act and a
stale compilation look alike there, and the enacted-law list is what tells
them apart. One compilation (`COMPS-3101`) has an empty body and points to the
U.S. Code from its preface; `body_present` reports that.

## Capture one source

From the checkout, install acquisition dependencies with
`uv sync --frozen --extra acquisition`. Each output directory must be new.

```sh
uv run --frozen python -m examples.uslm_capture public-law \
  --congress 119 --number 1 --max-bytes 33554432 --output /tmp/plaw-capture

uv run --frozen python -m examples.uslm_capture statute-compilation \
  --file-id 10542 --max-bytes 33554432 --output /tmp/comps-capture

uv run --frozen python -m examples.uslm_capture public-law-archive \
  --congress 119 --kind public --max-bytes 67108864 --output /tmp/plaw-119-capture

uv run --frozen python -m examples.uslm_capture statute-compilations-archive \
  --max-bytes 134217728 --output /tmp/comps-archive-capture
```

The example writes `receipt.json` and the original `response.xml` or
`response.zip`. Archive captures also write `entries.json`: every entry's name,
size, hash and validated metadata. Failures retain a receipt and bounded refused
bytes when available. The defaults are two requests, a 60-second transport
timeout and one second between request starts within a client.

## Use the wheel in an application

Pure selection, locator and validation functions need only the core package.
Acquisition needs the `acquisition` extra.

```python
from spicy_docs.sources.govinfo.uslm import PublicLawSelection, StatuteCompilationSelection
from spicy_docs.sources.govinfo.uslm_acquisition import UslmAcquirer, UslmAcquisitionBudget

budget = UslmAcquisitionBudget(
    max_requests=2, max_bytes=32 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1
)
with UslmAcquirer(budget=budget) as source:
    law = source.acquire_public_law(PublicLawSelection(119, "public", 1))
    act = source.acquire_statute_compilation(StatuteCompilationSelection(10542))

print(law.metadata.citable_as, law.capture.sha256)
print(act.metadata.title, act.metadata.current_through_public_law)
# Retain these exact bytes in caller-owned storage:
law_xml = law.capture.body
```

Offline, `validate_public_law_xml` and `validate_statute_compilation_xml` check
retained bytes against a selection and the locator they came from;
`read_public_law_archive` and `read_statute_compilations_archive` check a
retained zip. All of them refuse a wrong root, a nested root, a missing or
repeated identity field, an identity that differs from the request, a body
larger than `max_bytes`, and any DOCTYPE or entity declaration.

## Read the result correctly

- `metadata` holds publisher spellings. Citations use an en dash
  (`Public Law 119–1`); the citation check tolerates a hyphen but stores the
  original. `current_through_public_law` is a tuple in document order; three
  compilations state two values and 75 state none.
- `identity_basis` names which facts the body proved. Every field listed is
  native; the request URL supplies nothing the body did not confirm.
- A 404 or 410 raises `UslmSourceUnavailableError` with the exact capture. The
  publisher offers private-law folders for only some Congresses; that absence
  is a fact about the route, not about the laws.
- A 200 that is not XML or not a zip is refused with its bytes attached. The
  bulkdata host has served HTML error pages with status 200.
- Listing times are not act currency. Many compilations show a 2021 file time
  while the collection folder shows the latest refresh.

## Source shapes and evidence

Complete publisher fixtures with hashes are in
[`tests/fixtures/uslm/README.md`](../../tests/fixtures/uslm/README.md). The
pinned zips, every folder listing, both-direction listing checks and the
qualification of these validators against all 2,155 laws and 2,681
compilations are in
`corpora/supply-2026-09-02/receipts/comps-plaw-pin-2026-09-14/`.
The schema is the `proposed` branch of
[`usgpo/uslm`](https://github.com/usgpo/uslm/tree/proposed), which the
publisher's bulkdata readme names for the beta period.
