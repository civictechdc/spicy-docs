# Capture SEC rulemaking comments

Give SpicyDocs rule-page URLs stated by the SEC rulemaking index. It retains
each rule page, follows the links in its received-comments field, retains the
exact sec.gov comment-listing renders and every row they state, then returns
the exact bytes of every comment file and letter-type document those
renders named, each proved from its own bytes. No key is required. sec.gov's
fair-access policy governs the route: every request carries a declared
User-Agent naming this project and a contact mailbox from
`SPICY_DOCS_CONTACT_EMAIL`. A live acquirer refuses to start with the reserved
placeholder mailbox, and an agent override must keep the declared
`name/version (purpose; contact: mailbox)` shape. Pacing stays far under the
stated ten-requests-per-second ceiling, and the shared client retries
transient failures with backoff.

| Selection | What it supplies |
| --- | --- |
| The rulemaking index | One render per page of `/rules-regulations/rulemaking-activity`, walked to its terminal page: each row's stated file number, title, status, publish instant and per-rule page link. A missing file number remains missing. |
| A rule-page URL | The exact rule render, its source statements and `comment_listing_urls` from the publisher's `field-comments-received` field. These URLs retain the stated filenames; no filename is derived from the rule's file number. |
| A stated listing URL | The listing paged to its terminal page: `h1` title, letter-type section documents, and one row per comment file — commenter name, letter type, date, absolute URL, format. |
| A file number (legacy selection) | `comment_index_url` derives `/comments/{docket}/{docket-without-dashes}.htm`; this remains available when the caller explicitly chooses the measured spelling. |
| A URL a retained listing stated | The exact file bytes: PDF magic, trailer and terminal cross-reference, checked against any linearization length; HTML's opening tag and the docket in the file's own words for HTM/HTML. |

```python
from spicy_docs.sources.sec_comments.acquisition import SecCommentsAcquirer, SecCommentsBudget
from spicy_docs.sources.sec_comments.reader import SecCommentsReader

budget = SecCommentsBudget(
    max_requests=5,  # per operation: one URL and up to four backed-off retries
    max_page_bytes=4 * 1024**2,
    max_comment_bytes=16 * 1024**2,
    timeout_seconds=60,
    min_request_interval_seconds=0.5,
)
with SecCommentsAcquirer(budget=budget) as source:
    # Select a rule URL stated by a retained rulemaking-index row.
    reader = SecCommentsReader(
        acquirer=source,
        rule_urls=["https://www.sec.gov/rules-regulations/2025/06/s7-11-23"],
    )
    for record in reader.iter_records():
        print(record["url"], record["body_sha256"], record["rule_page_sha256"])
        # Retain record["body"] in caller-owned storage.
    # reader.rule_pages and reader.listing_pages retain the exact renders the records' digests name,
    # including rule pages that offered no listing and listing pages captured before a walk failed.
    # reader.discovery_outcomes distinguishes links-stated from no-listing-link-stated.
```

The [`SecCommentsReader`](../../src/spicy_docs/sources/sec_comments/reader.py)
wraps the same walk and download for pipeline use: keys are file URLs, a
complete pass leaves exactly the captured URLs in `last_keys`, and a URL that
answered 404/410 or failed its format or identity checks lands in
`failed_keys` for the next run to retry. A 401/403, or a transport failure
that exhausts `max_requests`, raises and ends the pass instead. A resume's
`processed_keys` skips a file by URL; it does not re-read the retained bytes.
A listing that several selected rule pages state is walked once per pass.
Use `rule_urls` or the legacy `dockets` selection, never both. Publisher-stated
records include `listing_discovery`, `rule_page_url` and `rule_page_sha256` in
addition to their listing and file evidence. `acquire_rule_page(url)` and
`walk_comment_listing(url)` also expose the metadata path without downloading
files. `max_requests` bounds one acquisition operation, including retries;
`max_listing_pages` bounds a listing walk. Pacing persists across operations.

## Read the result correctly

- **A stated listing link is discovery; a derived URL is a separate selection.**
  The reader's `rule_urls` route follows only links in the received-comments
  field, including on descriptive slug pages and pages without a file number.
  A successfully captured rule page with no such link produces
  `no-listing-link-stated`; it never establishes that no comments exist.
  Missing or unusable link targets refuse instead of becoming an empty result.
  The legacy docket grammar (`S7-11-23` → `/comments/s7-11-23/s71123.htm`) was
  verified against the `S7-11-23` per-rule page's own link on 2026-09-24, but
  the locator `comment_index_url` builds is still derived. A 404 means the
  listing was not served at that spelling; it never establishes that no
  comments exist. Guessed URLs do not count as discovery.
- **Letter-type sections are documents, not continuations.** The first table
  links `{stem}-typea.htm`-style files: the form letters many commenters
  submitted. They are captured like comments and never read as pages.
  Continuation is the `?page=N` query; there is no `-1.htm` grammar on this
  route.
- **A page's own statements prove it.** The pager's current item must name the
  page requested, and every file link must stay inside the listing's
  `/comments/{docket}/` route with a known extension (`.htm`, `.html`,
  `.pdf`; both two-number stems like `s71123-279699-683202.pdf` and
  single-number `s71123-542242.htm` occur). Docket comparison ignores case
  because SEC's `S7-08-23` listing states an uppercase directory in one PDF
  link; the captured URL keeps that exact spelling. A present-but-empty table
  is an observation, never a refusal and never source absence.
- **A row without a file number is still a row.** Multi-release rulemakings
  leave the file-number cell empty and are addressed by a slug; that cell does
  not establish whether comments exist. Every row still has a stable, enumerable
  `docket_key`: a file number a row states keys on it (`S7-11-23`), an empty
  cell keys on `slug:<path-segment>` of the row's rule page URL
  (`slug:33-11438`) — the prefix names the namespace and the empty cell is
  retained on the row, never replaced by a derived value. One file number can
  also appear on several rows, and a row's status link can point at a family
  slug rather than the file number's own page.
- **The walk refuses to end early or wander.** A repeated continuation, a
  continuation that changes more than the start URL's `page` parameter, a page
  bound reached with a next page outstanding, or a pager disagreeing with the
  page requested each raise; only a walk that returns reached the publisher's
  terminal page of the route it started on.

## What is refused

A 200 that is not the page asked for is refused with its bytes retained. A
comment file must match the media type its extension names and begin as
that format. Every PDF must end with `startxref` and `%%EOF`, with a nonzero
pointer to a cross-reference table or stream inside that capture. A linearized
PDF shorter than its `/L` is truncated and refused. Incremental PDF revisions
leave the original `/L` unchanged, so a PDF longer than its `/L` is read as an
appended revision, and its final pointer must sit at or beyond `/L`. The `/L`
is retained as observed metadata, not treated as the current file length. This
follows [ISO 32000-1, table F.1](https://developer.adobe.com/document-services/docs/assets/35e4369068f86065372c18787171a17e/PDF_ISO_32000-1.pdf).
A capture cut exactly at an earlier revision's end is that complete earlier
file and cannot be told apart. These bounded acquisition checks do not perform
full PDF semantic validation.
For HTML, the docket the URL names must appear in the file's own words (the initial shapes say
`File No. S7-11-23`). The final URL must equal the locator. A 401/403 raises
`SecCommentsRefusedError` with the refused body retained — a bot wall proves
nothing about the files. A 404/410 records that the exact requested locator
was unavailable.

Byte bounds come from what was measured: index renders of 247-258 KB and
listing renders of 85-104 KB on 2026-09-24 sit well under the 4 MiB page
default. The complete docket measurement below reached 16,574,487 bytes for
one file, just below the 16 MiB default. Larger captures need an explicit
budget; the 512 MiB cap is a runaway guard, not a publisher population
measurement. `min_request_interval_seconds=0.5` keeps one walk an order of
magnitude under sec.gov's stated ten-requests-per-second ceiling.

## Coverage limits

The completion campaign walked all four pages of `S7-11-23`, captured all 106
distinct files totaling 22,560,592 bytes (including letter-type documents), and replayed their retained
bytes. Nineteen PDFs exposed the stale-linearization bug; after its correction,
resume retried exactly those failed files. A final resume fetched listing pages
and made zero file requests. See receipts
`scraper-completion-2026-09-24T235248Z/fcc-sec/sec-full/` and `sec-resume/`.
This qualifies that selected docket, not all SEC comment populations.

The delivery campaign followed the index-stated descriptive rule-page slug
for `S7-08-23`, then its received-comments link and both listing pages. It
captured all 51 distinct files totaling 5,158,954 bytes, replayed every retained
file, and verified that an all-success resume made no file requests. The
initial bounded pass retained 45 successful files; resume acquired the remaining
six. This qualifies publisher-stated discovery for that slug shape and selected
docket. A separately retained rule page without a file number offered no
listing link; its full and trimmed parses preserve that observation. See
`scraper-delivery-2026-09-25T003133Z/sec/` for input pins, methods, timestamps,
the exact bodies and resume evidence.

The rulemaking index is the entry point: `/comments/` itself answers
`Index No Browsing`, so dockets cannot be enumerated from the comments host,
and this source captures only what the index and the listings state. The
reader follows each selected rule page's stated listing links. Coverage of
SRO rule pages and other unmeasured layouts remains open; a refused or missing
guessed URL cannot resolve that scope. Linked releases
and the index's status/division/year filters are outside its walk. Comment-file URLs are never
built from a docket: only a retained listing's own link is fetched.

## Evidence

The reduced fixtures, the complete-response digests they were cut from, and
the page-shape findings above are in
[`tests/fixtures/sec_comments/README.md`](../../tests/fixtures/sec_comments/README.md).
