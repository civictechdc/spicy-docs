# Repository instructions

spicy-docs *gets*; it does not interpret. See `README.md` for the module map and
the supply-precedence ruling. This file carries only what an agent needs before
changing acquisition code, and it is short on purpose.

Run checks through the project's own runner, never a bare binary from `PATH`:

```sh
uv run pytest
uv run ruff check .
```

## Writing a fetcher

Five disciplines, each from a defect this repository actually hit. They are
implemented in `tools/fetch_crs_summaries.py`, whose module docstring carries
the same list with its reasons — read it before writing a new one.

1. **Assert on what success looks like, not on what one failure looks like.** A
   check for the absence of a known error string passed a Cloudflare challenge
   page — it passed the exact failure it existed to catch. A row counts only
   when the response parses, carries the object expected, and that object's id
   equals the id requested.
2. **A credential refusal aborts.** 401/403 stops the run rather than being
   recorded per row and passed over.
3. **A recorded failure is retried, never skipped.** Resume re-attempts any row
   whose status is not `ok`, so "asked and got nothing" stays distinct from
   "never asked".
4. **Every row carries its provenance** — the run id and the source it was drawn
   from.
5. **A recorded error is scrubbed before it is written.** Use
   `scrub_credential`; do not re-derive it.

## The credential rule, and why it is repeated here

`README.md` already states it, for the Zyte token, in the right words:
*"The credential never enters a locator, artifact, log, or error."* **It says
"or error", and a fetcher written afterwards leaked a key through an error
anyway** (2026-09-07, fixed in `947353c`).

That is the point worth carrying. The rule was not missing and was not vague —
it was stated for one credential, in one place, and nothing carried it to the
next fetcher. So this section names the **mechanism** rather than restating the
principle:

- An API that takes its key as a **query parameter** puts the key in the request
  URL, and `httpx.HTTPStatusError` renders that URL into its message. **An error
  string is a URL in disguise.** Anything that records, logs, or reports
  exception text from a keyed client is a publication surface.
- Use `scrub_credential(text, api_key)` from `tools/fetch_crs_summaries.py`.
  Two passes: a pattern for a credential you were not handed (a redirect to
  another keyed host, a URL nested in a message), and the literal key for forms
  the pattern cannot match (an error body echoing it back, a header rendered
  into a message, a key moved into the path). **Scrub before truncating** —
  truncating first can cut a key in half and leave the front standing.
- If a second module needs it, move it to `src/spicy_docs/` and import it in
  both. Do not copy it.

**Mutate the scrub when you touch it.** Both passes are pinned by tests, and
that is not decoration: when the fix was first written and green, deleting the
literal pass left every test passing. Half of it was unbacked, and only
mutation said so.

## Receipts

A number quoted in prose cites the file that holds it beside the command and
inputs that produced it. Acquisition receipts for the 2026-09 campaign live in
`~/Work/corpora/supply-2026-09-02/receipts/`, outside any repository.
