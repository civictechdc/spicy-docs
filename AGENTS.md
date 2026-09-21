# Repository instructions

SpicyDocs acquires source facts and evidence. Downstream applications interpret
them. Read [the source workflow](docs/source-workflows.md) before changing that
boundary.

## Checks

```sh
./scripts/check
# Focused checks:
uv run --frozen pytest
uv run --frozen ruff check .
```

Always run Python tools through `uv run`; a bare executable may use another version.

## Point, don't count

Prose in docs, docstrings and instructions must not hard-code counts that decay
every commit (file counts, test counts, table sizes). Point instead: `see
filemap.tsv`, `see <dir>/`, `see <module>`. Numbers that justify a rule or a
measured bound stay, with their citation.

## Read the publisher's answer correctly

- **Empty success is not absence.** GovInfo can return `200` with an empty result
  for a nonexistent item. Record requested-empty separately from never-requested.
- **Check the expected success shape.** A challenge page can lack known error text.
- **Transport failures are not records.** A `502` cannot establish a zero count.
- **One success does not establish a reliable route.** Gated endpoints can change
  their answer to identical requests.
- **Preserve the method.** Congress.gov can refuse `HEAD` while serving `GET`.
- **Respect access requirements.** Use the supported credentialed API for a gated format.

## Write recoverable fetchers

1. Abort on credential refusal (`401`/`403`); do not skip it as a bad row.
2. Retry every previously unsuccessful row on resume.
3. Retain run and input-source provenance for every row.
4. Scrub errors before writing or logging them.
5. Detach long runs with `os.setsid` and resume from their own output.

Reuse the credential and resume patterns in
[`crs_summaries.py`](src/spicy_docs/sources/congress/crs_summaries.py).

## Keep credentials out of evidence

Request URLs and exception messages can contain keys. Reuse `read_api_key` and
`scrub_credential` from `spicy_docs.transport.credentials`.

- Scrub **before** truncating, or a key prefix can survive.
- Keep both scrub passes covered. When changing them, mutation-check that the
  tests fail if either pass is removed.
- Never put credentials in locators, artifacts, logs or reported errors.

## Retain evidence and reasons

Keep unusual rules and their reason beside the code; follow
[documentation maintenance](docs/documentation.md).
Measurements need input pins, the command and its retained receipt.
Campaign receipts belong in `~/Work/corpora/supply-2026-09-02/receipts/`, outside
this repository. Commit only bounded fixtures and reusable guidance.
