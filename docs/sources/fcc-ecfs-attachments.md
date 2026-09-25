# Capture FCC ECFS filing documents, and backfill the filings that declare them

Give SpicyDocs a `documents[]` entry from an FCC ECFS filing row. It returns
the exact bytes of the document that entry declares — one bounded file per
publisher-declared download URL — proved from the bytes themselves, or a named
refusal that says which of the host's answers it was. The filings table that
carries the entries is backfilled separately, by a driver that enumerates date
windows through the counted filing traversal. An `api.data.gov` key
(`X-Api-Key`) gates the filings API; the document hosts are keyless.

The entry's `src` is one of two publisher grammars, each validated in the
publisher's own spelling:

| Declared `src` | Serves | Identity (the dedupe key) |
| --- | --- | --- |
| `https://docs.fcc.gov/public/attachments/{filename}` | FCC-generated documents: the exact file bytes | The filename — it is the document's identity, and an entry whose declared filename disagrees with the URL's own refuses |
| `https://www.fcc.gov/ecfs/document/{id_submission}/{documentIndex}` | The viewer locator; acquisition requests its measured `/ecfs/documents/{id_submission}/{documentIndex}` byte route | The pair `(id_submission, document index)` — the pair the URL itself carries, and one filing row repeating it refuses |

An express comment declares no files (`documents` absent or `null`), which is
a different answer from a failed read. The acquisition route is
[`fcc_ecfs_attachments.py`](../../src/spicy_docs/sources/fcc_ecfs_attachments.py):
[`document_locator`](../../src/spicy_docs/sources/fcc_ecfs_attachments.py)
reads one entry's `src` and `filename` and refuses anything that is not one of
the two grammars, and
[`declared_documents`](../../src/spicy_docs/sources/fcc_ecfs_attachments.py)
reads a whole row in publisher order, refusing a repeated identity. The
filings themselves come from the `fcc_ecfs` route described in
[Publisher list pages](listings.md); the backfill driver
([`tools/analysis/fcc_ecfs_backfill.py`](../../tools/analysis/fcc_ecfs_backfill.py))
fills that table from a start date to today.

```python
from spicy_docs.sources.fcc_ecfs_attachments import (
    FccEcfsDocumentAcquirer,
    FccEcfsDocumentBudget,
    declared_documents,
)

budget = FccEcfsDocumentBudget(
    max_requests=3,  # one attempt per ladder rung
    max_bytes=16 * 1024**2,
    timeout_seconds=60,
    min_request_interval_seconds=1.0,
)
with FccEcfsDocumentAcquirer(budget=budget) as source:
    for declared in declared_documents(filing_row):
        capture = source.acquire(declared)
        print(capture.locator.subject, capture.transport, capture.request_count, capture.capture.sha256)
        # capture.capture.body is the exact bytes; retain it in caller-owned storage
```

## Capture filings and their documents with recovery

The backfill command's `--capture-documents` option connects date-window
discovery to the source-owned
[`FccCaptureJournal`](../../src/spicy_docs/sources/fcc_ecfs_capture.py):

```sh
uv run --frozen python -m tools.analysis.fcc_ecfs_backfill \
  --since 2026-09-21 --until 2026-09-22 \
  --output /path/to/fcc-capture --api-key-file /path/to/credentials.env \
  --capture-documents --max-document-attempts 20 --execute
```

Use one process per output directory. Configure the existing `ZYTE_TOKEN` or
`FIRECRAWL_API_KEY` environment variables when the public file host needs
recovery. The command reads `API_GOV` only from the explicitly named file.
Without `--execute`, it prints the date plan and makes no writes or requests.

`resume.jsonl` pins each completed window's filing rows and exact list pages.
`documents.jsonl` links each offered file to its line in the window's pinned
filings file, then records capture, requested-empty, unavailable, failed or
refused outcomes. Filings with no offered files remain observations in that
pinned file and are counted in each run's summary. Exact bytes use the existing
content-addressed blob store under `captures/<run-id>/`. This directory is
acquisition state; it is not an admitted source release.

Rerun the same command to continue. A completed window is skipped only while its
filings file matches its pinned size and digest and its retained pages replay
offline through `iter_filings` into the same records. Each successful file is
skipped only after its retained size and digest verify. Failed, unavailable and
refused requests retry; missing or corrupt successes are reacquired into a new
run's store, preserving the old evidence. An interrupted final journal row is
preserved separately before the next append. Windows pinned by earlier runs
that cannot replay are reacquired once.

A viewer shell or a redirect answers one file: it is recorded as `refused` with
its refusal kind and exact bytes, and the run continues with the next file. A
wall that exhausts every rung, a credential refusal, or a refusal in no known
shape aborts the run with exit `2`.

The file-attempt limit deliberately leaves outstanding offers pending; rerun
with the same limit to make further progress, or omit it to finish the selected
windows. Exit `0` means discovery reached terminal pages and every valid offer
has a terminal outcome; inspect the outcome counts because unavailable and
requested-empty are not downloaded content. Exit `1` means incomplete discovery,
invalid declarations, failed or refused files, or pending offers. The counted
traversal partitions a crowded day by submission time, and a crowded single
millisecond still refuses. This option does not establish an exhaustive
historical archive.

Live recovery on 2026-09-25, before discovery moved to `iter_filings`, selected
submission `26110077503` from exact API pages: a deliberate stop retained three files, the next run acquired the eight
outstanding files, and a completed rerun made no file requests. A copied store
with a corrupted file and then a deleted file required one request in each
case and retained all eleven successful identities. The replayable commands,
captures and receipts are in
`scraper-delivery-2026-09-25T003133Z/fcc/` under the campaign receipts directory.

## The ladder, and what was measured on it

Acquisition climbs the shared walled-fetch ladder
([`walled_fetch.py`](../../src/spicy_docs/sources/walled_fetch.py)) through
the shared acquirer's `capture_walled`, with its default rungs — DIRECT,
ZYTE_HTTP, FIRECRAWL_RAW — and no browser rung, on each locator's byte URL.
The direct rung runs first on the acquirer's own client, so an ungated file
costs exactly one request; the proxy rungs escalate past an edge that blocks
the direct client. Every attempt, proxy rungs included, is charged against the
budget's `max_requests` and paced by `min_request_interval_seconds`, and
`request_count` reports the attempts one acquisition made. A body that begins
with its format's magic is the file, even if it quotes block-page wording.
The ladder owns the wall vocabulary and the rung bookkeeping; this module owns
the grammar, the refusal kinds, the magic checks and the evidence.

Measured live 2026-09-24:

- **`docs.fcc.gov` reads cleanly on the direct rung.** A direct GET of
  `DA-26-1030A1.pdf` answered `200 application/pdf` with no wall, and the
  exact bytes — all 125,605 of them, beginning `%PDF-1.7` — are pinned in the
  firecrawl client smoke receipts
  (`supply-2026-09-02/receipts/firecrawl-client-smoke-2026-09-24`).
- **The SPA host is keyless and Akamai-gated, and that is not cosmetic.** On
  one declared SPA URL, three GETs — `spicy-docs-fcc-ecfs/1.0`, a browser
  agent, and the browser agent plus `Accept` and `Accept-Language` headers —
  all answered 403 with the same 404-byte `text/html` `Access Denied` page
  from `Server: AkamaiGHost` naming the requested URL and a per-request
  reference (`x-reference-error`), so its digest changes every time and the
  refusal kind is read from the page's own words (receipt
  `supply-2026-09-02/receipts/publisher-questions-2026-09-24/
  q1-fcc-ecfs-document-host`).
- **The proxy rungs answer the SPA locator with the viewer shell, not the
  file.** Both providers returned a ~1,374-byte `text/html` React shell
  carrying `<div id="root">` (receipts
  `supply-2026-09-02/receipts/zyte-client-smoke-2026-09-24` and
  `firecrawl-client-smoke-2026-09-24`). The current JavaScript bundle requests
  `/ecfs/documents/{id_submission}/{documentIndex}` as an array buffer.
  `FccDocumentLocator.byte_url` uses that measured route while retaining the
  singular viewer URL as the publisher's identity. Its first captured PDF
  contained 335,544 bytes (`fcc-ecfs-spa-route-2026-09-24`).
- **A complete filing and multiple formats work through the byte route.**
  The completion campaign captured all 11 declared files of submission
  `26110077503`, plus samples covering PDF, DOC, DOCX, XLSX and TXT. All 15
  captures were nonempty and passed their format checks through Zyte HTTP;
  sizes ranged from 3,071 to 2,462,478 bytes. The exact source rows, captures,
  digests and outcomes are in
  `scraper-completion-2026-09-24T235248Z/fcc-sec/fcc-files/`. This establishes
  that selected filing's coverage, not every attachment in the backfill.

## Read the result correctly

- **A clean 2xx whose body is the viewer shell is a named refusal
  (`spa-shell`), not an unrecognized one and not absence.** The shell check
  reads the bytes (`<div id="root">`, the JavaScript notice), never the media
  type, and a wall-marked body is a wall, never a shell.
- **A wall that exhausts every rung raises `client-rejected` with the
  retained wall bytes as evidence.** It speaks about the client, not the
  file; `FccEcfsDocumentRefusedError` is a `CredentialRefusedError` subclass
  on purpose, so callers that abort on a refusal keep aborting.
- **A redirect is a named refusal, not something this route follows.** The
  direct rung never follows redirects, and the proxy rungs record the URL the
  provider resolved; a clean answer whose final URL differs from its byte URL
  raises `redirected`, so a future redirect reads as a publisher answer to
  revisit, not a broken capture.
- **Neither refusal establishes absence.** Only 404/410 —
  `FccEcfsDocumentUnavailableError` — is a host saying the exact URL has
  nothing.
- **Requested-empty is recorded, not skipped.** A 200 with an empty body is a
  complete answer about a URL the filings row declared, so it returns as an
  acquisition with `requested_empty` set and no magic check — separate from a
  refusal, from a missing file, and from never having asked.

## What is refused

The media type is advisory and the magic is the gate. Publishers state
`application/pdf` or `application/octet-stream` for the same file, so each
extension accepts the generic download types beside its canonical one, and
`text/html` is never accepted as a document's media type — the viewer shell is
named by its own check before the media gate sees it, and the wall's answer
never reaches a clean result. The bytes decide: `pdf` additionally proves its
trailer through [`pdf_bytes.py`](../../src/spicy_docs/reading/pdf_bytes.py),
and the other extensions must begin with the magic their filename declares,
because extensions lie there too (three files named `.xlsx` began with the
OLE2 signature of a legacy `.xls`). The final URL must equal the byte URL, and
the filename must agree with its URL.

The 16 MiB default covers the bounded measurements above and the earlier
docs.fcc.gov sample (`fcc-ecfs-bounds-2026-09-24`). The 640 MiB construction
cap remains inherited from the regulations.gov route; these small samples
do not establish an FCC population maximum. The publisher declares no size
for a document, so there is no declared byte count to check.

## The backfill driver

[`tools/analysis/fcc_ecfs_backfill.py`](../../tools/analysis/fcc_ecfs_backfill.py)
plans and executes the `fcc_filings` date-window slices from a start date to
today, one window at a time, with pacing, an append-only resume file and
per-slice outcome rows. Each window is enumerated by the
[counted filing iterator](listings.md#enumerate-fcc-filings-for-a-mirror), which
checks the publisher's count and partitions a crowded window by submission time
below the result ceiling. Applications with their own mirror state use that
iterator and the document acquirer directly.

**It is a dry run by default.** Without `--execute` it prints the slice plan
and makes no request and no write. A slice is the resume unit, not a ceiling
workaround; `--slice-days` sets its width.

- **`resume.jsonl` beside the slice files holds one row per window; the
  latest row per `(start, end)` wins.** A `done` row settles a window only
  while its expected filings file matches the retained byte count and digest.
  Missing, unreadable, changed or unpinned legacy outputs are reacquired.
  Every unsuccessful window is retried on the next run and remains incomplete
  until it succeeds. A 401/403 aborts the run: a refusal is not a bad slice.
  Messages are scrubbed through `scrub_credential` before they are written.
- **A window's output is staged until its traversal finishes.** A refusal after
  earlier rows were read leaves no filings file for that window.
- **Pacing** keeps at least `--min-interval-seconds` (default 3.7) between
  page requests and `--pause-seconds` (default 5) between windows.
- **Windows are inclusive calendar days sent through `filings_url`**, which
  spells an inclusive end day as the following midnight, so adjacent slices
  can share all filings stamped at their common boundary;
  identity settles downstream on `id_submission` where the filings table
  merges.

Run it from the repository root — first the dry run, then the fetch:

```sh
uv run --frozen python -m tools.analysis.fcc_ecfs_backfill --since 1996-01-02 --output DIR
uv run --frozen python -m tools.analysis.fcc_ecfs_backfill --since 1996-01-02 --output DIR --api-key-file ENV --execute
```

The `--since` date is the same scoping decision spicy-regs' `FCC_SINCE`
environment override carries for its own deeper backfills: a backfill beyond
the bounded first run is expected to run scoped to a date window, not as an
unbounded full walk of the API. Choose the archive's start for a complete
backfill, or a later date to fill forward from the table's current end.

## Coverage limits

The document route captures only what a filings row's `documents[]` declares:
one bounded file per URL, whatever format its filename names. Viewer locators
resolve through the measured byte-route spelling without executing JavaScript.
The filings driver enumerates only the
windows it is given, and a crowded single millisecond refuses rather than being
guessed at.

## Open questions

- **The document size distribution.** The retained samples justify the current
  default for those files. A broader bounded campaign must measure large files
  and additional formats before making population claims.

## Evidence

The measurements cited above are retained outside this repository, in the
campaign receipts: the docs.fcc.gov direct answer and the SPA shell in
`supply-2026-09-02/receipts/firecrawl-client-smoke-2026-09-24` and
`zyte-client-smoke-2026-09-24`, and the Akamai wall measurement in
`supply-2026-09-02/receipts/publisher-questions-2026-09-24/
q1-fcc-ecfs-document-host`. The module and the driver are covered by their own
test modules ([`test_fcc_ecfs_attachments.py`](../../tests/test_fcc_ecfs_attachments.py),
[`test_fcc_ecfs_capture.py`](../../tests/test_fcc_ecfs_capture.py),
[`test_fcc_ecfs_filings.py`](../../tests/test_fcc_ecfs_filings.py),
[`test_fcc_ecfs_backfill_tool.py`](../../tests/test_fcc_ecfs_backfill_tool.py)).

```sh
uv run --frozen pytest -q tests/test_fcc_ecfs_attachments.py tests/test_fcc_ecfs_capture.py \
  tests/test_fcc_ecfs_filings.py tests/test_fcc_ecfs_backfill_tool.py
```
