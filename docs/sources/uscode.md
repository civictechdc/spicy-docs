# Capture the U.S. Code from its publisher

Give SpicyDocs a release point and a title, a year, an act key, or nothing at
all. It returns the exact bytes the Office of the Law Revision Counsel served,
the native identity it proved, and bounded HTTP evidence. Every route is
keyless: no API key, no account, no terms gate.

| Route | Required selection | What it supplies |
| --- | --- | --- |
| Release-point title | Release point and title code | One title's USLM zip. The document's own `docNumber` and `docPublicationName` must match the request. |
| Release-point corpus | Release point | Every title in one zip of about 108 MB, each member validated against its own bytes. |
| Annual archive | Year, 1994 onwards | One year of the Code as XHTML. Every title member states its edition, year, title and currency. |
| Popular Name Tool | None | Every popular name Congress has used, with the enacting act's Table III key and often the Code section its short title lives in. |
| Table III act | An act key | Which of the act's sections went to which Code section, and what happened to the rest. Each page also names the acts before and after it. |
| Table III bulk | None | The whole of Table III in one zip: 23,209 acts in 48,973 `<act>` fragments, and 317,590 classification records. |

OLRC's USLM is **not** GovInfo's. This publisher serves USLM 1.0 in
`http://xml.house.gov/schemas/uslm/1.0` under a `uscDoc` root, where
[`uslm-laws.md`](uslm-laws.md) covers GovInfo's USLM 2.x under `pLaw` and
`statuteCompilation`. They are different vocabularies with the same name.

## Use the wheel in an application

Pure selection, locator and reader functions need only the core package.
Acquisition needs the `acquisition` extra.

```python
from spicy_docs.sources.uscode import ReleasePoint, TitleSelection
from spicy_docs.sources.uscode.acquisition import UsCodeAcquirer, UsCodeAcquisitionBudget

budget = UsCodeAcquisitionBudget(
    max_requests=2, max_bytes=128 * 1024**2, timeout_seconds=900, min_request_interval_seconds=1.5
)
with UsCodeAcquirer(budget=budget) as source:
    title = source.acquire_title(TitleSelection(ReleasePoint(119, 103), "01"))
    act = source.acquire_table3_act("1955:360")

entry = title.result.entry
print(entry.metadata.doc_number, entry.metadata.release_point, entry.metadata.positive_law)
print(act.result.stated_key, len(act.result.records))
# Retain these exact bytes in caller-owned storage:
title_zip = title.capture.body
title_xml = title.result.xml_bytes
```

Offline, `read_title_archive`, `read_corpus_archive` and `read_annual_archive` live in
`spicy_docs.sources.uscode.archive`. The title reader returns a
`UsCodeTitleArchive` containing one `entry` and its exact `xml_bytes`.
`validate_title_xml`, `validate_annual_title_html`, `parse_popular_names`,
`parse_table3_page` and `read_table3_bulk_archive` check retained bytes against
a selection in `spicy_docs.sources.uscode`. `iter_table3_acts` streams the bulk file's 48,973 `<act>`
fragments without holding them.

## Tell which acts Table III holds

Read the bulk file. It lists every act the table holds, so an act it does not
list is absent from the table at the release point its member names. A single
act's page cannot say so: an act without a page answers with the first 16 KB
of the site template and a dropped connection, which is also the start of every
served page (see [below](#read-the-result-correctly)). Each page does name the
act before and after it (`Table3Page.prior_act`, `next_act`), and those links
skip exactly the acts with no page: `119-12` names `119-18` next, and `119-13`
to `119-17` answer only the template. On 2026-09-26 `118-273` named `119-1`,
so the links cross Congresses too (receipt
`corpora/fork-execution-2026-09-21/open-work-investigation-2026-09-26/congress-documents.md`,
section 2b). The per-Congress index (`congress119th.htm`, linked from every
page) is not read by this package.

spicy-regs walked those links one page at a time until 2026-09-26. A walk from
the highest held act never went back: it missed 119-30 and 119-53, which the
bulk file lists, and a Congress whose first act has no page could not start.
The walker, `iter_table3_chain`, was removed in the release that followed.

To parse the retained content, use the [structure and annual section readers](uscode-structure.md)
and [reference and source-credit readers](uscode-references.md). They preserve
literal source observations; applications save those results and apply their own
citation or legal-status rules.

## Process a retained corpus

`read_corpus_archive` calls `on_entry` in ZIP order, after checking each member's
name, bytes and native identity. A corpus must contain at least one title;
a directory-only ZIP is refused. Its result holds metadata only. This avoids
collecting every title body in memory or reopening the ZIP to recover XML that
the reader already checked.

```python
from spicy_docs.sources.uscode import ReleasePoint
from spicy_docs.sources.uscode.archive import read_corpus_archive

members = []


def record_member(entry, xml_bytes):
    # Parse or stage this member here; retain bytes only when needed.
    members.append((entry.name, entry.sha256, len(xml_bytes)))


corpus = read_corpus_archive(
    retained_zip,
    release_point=ReleasePoint(119, 102),
    max_total_bytes=1024**3,
    on_entry=record_member,
)
# Publish staged results only after the entire call succeeds.
```

Callbacks are provisional: a later member can refuse the archive. A callback
exception stops the scan and propagates unchanged. Acquisition has no callback;
callers can separately process its retained capture.

`read_annual_archive` provides the same `on_entry(entry, html_bytes)` callback in
ZIP order, including supporting files whose `entry.metadata` is `None`. Its
result still separates `entries` and `others` and reports `carried_forward`
members. A title's stated year remains source data, even when the archive
reissues an earlier year's appendix. The caller decides which members to process.

The compressed input is held as bytes and must fit `max_bytes`. Each member must
fit `max_entry_bytes`. `max_total_bytes` checks aggregate declared expansion
before the existing CRC scan; its default is `max_entries * max_entry_bytes`.
The CRC preflight decompresses entries before they are read for validation.
These source-size bounds do not promise a CPU or total-memory ceiling.

## Choose a budget the route can actually meet

A single title zip is 42 KB and arrives in about 11 seconds. Three routes are
much larger or much slower, and one budget will not fit them all:

| Route | Observed 2026-09-14 | Suggested `max_bytes` / `timeout_seconds` |
| --- | --- | --- |
| Title zip | 42 KB, 11 s | 128 MiB / 120 |
| Corpus zip | 108.6 MB, 243 s | 192 MiB / 900 |
| Annual archive | 52–88 MB, 32–172 s | 128 MiB / 900 |
| Popular Name Tool | 11.1 MB, **435 s** | 32 MiB / 900 |
| Table III act page | 16–118 KB, 7–15 s; an act without a page holds the connection 11–16 s before dropping it | 32 MiB / 120 |
| Table III bulk | 15.0 MB, about 260 s with retries | 64 MiB / 900 |

The Popular Name Tool is assembled per request, which is why 11 MB takes seven
minutes. On 2026-09-26 the Table III bulk zip arrived in 22 seconds on one
request, byte-identical to the 2026-09-14 capture at the same release point.
Neither `GET` nor `HEAD` states `Last-Modified`, `ETag` or `Content-Length` for
it, so only its bytes can show it is unchanged (receipt
`corpora/fork-execution-2026-09-21/table3-bulk-2026-09-26/`). Be polite: about
1.5 seconds between request starts.

## Read the result correctly

- **Identity comes from the bytes, never the name.** The publisher's own names
  disagree with each other: `xml_usc05a@119-103.zip` carries `usc05A.xml`, while
  `11a`, `18a` and `28a` stay lower case. `docNumber` and `docPublicationName`
  are what a title proves itself with, and `identifier` is a second witness
  where the document states one. `usc50A.xml`, the eliminated Title 50
  Appendix, states none; it was converted in 2015 and reissued unchanged since.
- **An act without a page answers 200 and a dropped connection.** OLRC sends
  the first 16,134 bytes of its site template, or 16,209 when the request
  carries the session cookie. It then drops the connection (`RemoteProtocolError:
  … incomplete chunked read`). All 44 retained answers of this kind dropped
  and none ended cleanly. They carry no rows, no `</html>` and no act key, so
  re-read bytes are refused rather than recorded as "this act classified
  nothing".
- **Those bytes are a served page's first 16 KB, so they never establish
  absence.** On served pages the site menu (`<div id="subMenu">`) opens at
  2,251 or 2,339 bytes and the content (`<div id="content"`) at 27,199 or
  27,947. Session id aside, each answer is a byte-exact prefix of every served
  page with the same session state, in all 1,331 pairs checked. A served page
  dropped anywhere between those two points is therefore indistinguishable
  from an act without a page. The acquirer treats the answer as the transport failure it is: it
  retries it and then raises with the last attempt's bytes as
  `response-incomplete` evidence (`refused_response`). Absence is read from
  [the bulk file](#tell-which-acts-table-iii-holds). Other routes keep no bytes
  from a drop; the download page and the bulk zip have dropped mid-way too.
  The receipt is `~/Work/corpora/fork-execution-2026-09-21/table3-walk-2026-09-24/`
  (the walk, and `spicy-docs/` for these measurements), with the drift
  audit's probes in `drift-audit-2026-09-24/laws/`.
- **A listed title the publisher does not serve answers 302**, to
  `/docnotfound.xhtml`. Title 53 is reserved, is linked from the download page,
  and answers that way. A redirect establishes neither data nor absence; it is
  refused with its status and its capture. Only a real 404 or 410 raises
  `UsCodeSourceUnavailableError`.
- **The download routes send no `Content-Type` and no `Content-Length`.** The
  acquirer allows the absent header explicitly and proves the shape from the
  bytes instead: a zip local file header, a CRC check, then every member's
  native identity.
- **An annual archive carries more than titles.** Twenty-five years ship
  `usc.css`, thirteen ship `index.html`, and 2010 through 2013 ship extra
  tables. They are kept by name, size and digest under `others` and claim no
  title identity. A member that is *not* routed as a title but states
  `AUTHORITIES-USC-TITLE-ENUM` refuses the whole archive, so the routing cannot
  quietly skip a title.
- **Two annual members state another year.** `2016usc50a.htm` and
  `2017usc50a.htm` both state 2015. They appear in `carried_forward`, not in a
  refusal: it is the publisher reissuing an eliminated appendix unchanged.
- **Table III lags the Code.** On 2026-09-14 the Code stood at release point
  119-103 and Table III at 119-73. Each states its own, so neither has to be
  assumed.
- **Publisher spellings are kept.** A Table III page spells a public law with an
  en dash (`111–226`) where its own URL spells a hyphen (`111_226.htm`); the
  identity check tolerates the difference and `stated_key` keeps what the page
  said. The Popular Name Tool's `content_type` vocabulary — `cite`, `see`,
  `also-known-as`, `renamed`, `short-title-ref` — is kept verbatim, because the
  difference between "this act is" and "this name means" is the difference
  between an identity and a redirect. Resolving a `see` to its target is
  interpretation and belongs downstream; `stated` carries the text as written.
- **The file name of a Table III page is read, not guessed.** Each popular-name
  `cite` links its act's own page, and `table3_href` carries that link. Where
  the page states no link, `table3_file_name` applies the rule the publisher's
  own `table3years.htm` script applies. On the 2026-09-14 capture the two agree
  on all 13,012 links the page states.
- **The Statutes at Large place is stated twice.** A `cite` gives it once as a
  `statviewer.htm?volume=&page=` query and once as prose. The query is read
  first because it is the machine-stated fact and carries a volume the prose can
  omit; `statutes_at_large_witness` says which statement supplied the value, and
  a disagreement is reported rather than resolved. On release point 119-103,
  12,994 cites state both and none disagree.
- **Nothing readable is dropped in silence.** A popular-name entry with no name,
  a paragraph with no `content-type`, and a `usckey` that is not `title:section`
  (the appendix titles state `18A:1`) each produce a defect record with its
  reason and the refused value.
- **The bulk file splits an act across `<act>` fragments.** It holds 23,209
  acts in 48,973 fragments, most of ten records or fewer and none above 20;
  4,151 acts span more than one. A fragment states its own date and volume (87-845 prints one record in
  76 and the rest in 76A), and a record's `sequence` restarts or repeats within
  70 acts and runs out of order in 5, so a record's position in its act is its
  place in the file. Over the 38 acts spicy-regs had published from their
  pages, the fragments state the same 2,981 records in page order, field for
  field; the file spells the act-level context its own way (`119`,
  `2025-01-29`, `139`, `119-4`) where a page prints `119th Cong.`,
  `Jan. 29, 2025`, `139 Stat.` and `119–4` (receipt
  `corpora/fork-execution-2026-09-21/table3-bulk-2026-09-26/`).
- **The bulk file's whole vocabulary is carried, and a new name stops the
  read.** Every attribute and child element `<act>` and `<record>` state across
  all 48,973 fragments and 317,590 records has a field: the act's `id`, `sequence`,
  `insertion`, `format`, `print_in_supplement`, `include_in_online_release_point`
  and its `public_law` — the session public-law number a pre-1957 chapter act
  carries, stated by 10,406 acts — and the record's `id`, `sequence`, `usc_key`
  and `print_in_supplement`. A name outside those sets refuses and names itself,
  because a vocabulary this reader has not seen is a reason to stop rather than
  to drop a fact quietly. Two records state an empty `id` or `usckey`, so those
  two fields are optional; every other required field holds on all 317,590.
- **The member's name and shape have changed, and only today's is read.** The
  eight releases the Wayback Machine archived from 2020 to 2025 name the member
  `<timestamp>_<release point>.xml` (`20200730083344_116-150.xml`) and wrap the
  acts in one `<t3edit>` root; the 2025-08 member is `table3_xml_bulk.xml`,
  which names no release point; today's is `fulldump@119-73.xml`, a bare
  sequence of `<act>` elements. The reader accepts only the last and refuses
  the others by name, so a rename stops a caller's read rather than being
  misread; a caller should treat that refusal as a signal to update this
  package. Across those releases, from 116-150 to 119-73, the table only grew:
  no act was ever dropped (receipt
  `corpora/fork-execution-2026-09-21/table3-bulk-2026-09-26/wayback/`).

## Source shapes and evidence

Complete and reduced publisher fixtures with hashes are in
[`tests/fixtures/uscode/README.md`](../../tests/fixtures/uscode/README.md). The
live pins, the offline qualification of every validator against RefSpec's
retained 108 MB corpus zip and all 31 annual archives, and the timing
measurements quoted above are in
`corpora/supply-2026-09-02/receipts/port-P01-uscode-2026-09-14/`. The Table III
template and chain measurements of 2026-09-24 are in
`corpora/fork-execution-2026-09-21/table3-walk-2026-09-24/spicy-docs/`.
