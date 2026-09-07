# Repository instructions

spicy-docs *gets*; it does not interpret. `README.md` has the module map and the
supply-precedence ruling. This file is the rules for touching acquisition code.

```sh
uv run pytest
uv run ruff check .
```

Always through `uv run`. A bare `ruff` on `PATH` may be an old shim whose advice
inverts the pinned one's.

## Reading a publisher's answer

The core hazard of this repository: **a publisher's "nothing" and its "nothing
there" are often the same bytes.**

- **Never derive absence from an empty success.** GovInfo returns 200 with a
  well-formed empty result for things that do not exist. Four instances across
  two hosts, three nearly reported as findings about the corpus.
- **Assert on what success looks like, not on what one failure looks like.** A
  check for the absence of a known error string passed a Cloudflare challenge
  page — it passed the exact failure it existed to catch.
- **Keep asked-and-got-nothing distinct from never-asked** in whatever the run
  records, or an outage becomes a receipt that reads as coverage.
- **Never read a transport error as data.** A 502 recorded as `granuleCount 0`
  is a network fact entered as a publisher fact.
- **One success is not a route.** A gated endpoint returned 200 to a
  browser-like User-Agent and the challenge again one minute later to identical
  headers.
- **The method is part of the route.** Congress.gov answers 403 to `HEAD` and
  200 to `GET` for the same PDF, so a HEAD-based sweep reports the route dead.
- **A publisher's fence is an answer, not an obstacle.** Where a source gates
  one format and offers a credentialed API, use the API. Cheapness is the
  pressure this rule exists to resist.

## Writing a fetcher

Implemented end to end in `tools/fetch_crs_summaries.py`; its module docstring
carries the reason behind each. Read it before writing a new one.

1. **A credential refusal aborts.** 401/403 stops the run rather than being
   recorded per row and passed over.
2. **A recorded failure is retried, never skipped.** Resume re-attempts any row
   whose status is not `ok`.
3. **Every row carries its provenance** — the run id and the source it came
   from, because rows from two inputs cannot be separated afterwards.
4. **A recorded error is scrubbed before it is written** — see below.
5. **Long runs detach** (`os.setsid`) and **resume from their own output**. A
   harness has group-killed runs at 23 minutes with no exit code.

## Credentials

**An error string is a URL in disguise.** A key passed as a query parameter is
in the request URL, and `httpx.HTTPStatusError` renders that URL into its
message — so anything recording, logging, or reporting exception text from a
keyed client is a publication surface.

- Call `scrub_credential(text, api_key)`; do not re-derive it. If a second
  module needs it, move it to `src/spicy_docs/` rather than copying it.
- **Scrub before truncating.** Truncating first can cut a key in half and leave
  the front standing.
- **Mutate it when you touch it.** Both of its passes are pinned by tests
  because, when first written and green, deleting one left every test passing.
- The principle this implements is already in `README.md` and stays there.

## Receipts

A number quoted in prose cites the file holding it beside the command and inputs
that produced it. Campaign receipts live in
`~/Work/corpora/supply-2026-09-02/receipts/`, outside any repository; findings
and their stories belong there, not here.
