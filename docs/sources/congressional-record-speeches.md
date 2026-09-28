# Read speech turns from a Congressional Record granule

Give SpicyDocs one retained GovInfo CREC granule HTML body and a MODS that
describes it: the granule's own, or its issue's package MODS. It returns the
granule's items -- speech turns, recorder and clerk lines, titles, rules -- each
with its speaker, the bioguide id the MODS states for that speaker, its exact
text and the source lines it came from. It reads
retained bytes offline; acquiring them is the [GovInfo body
routes'](govinfo-bodies.md) job.

The parser is [`congressionalrecord`](https://github.com/unitedstates/congressional-record),
the @unitedstates project's Record parser. SpicyDocs depends on it at a pinned
fork commit; it does not contain a copy of it.

Install the `record-speeches` extra. From this checkout, use
`uv sync --frozen --extra record-speeches`, then run this with
`uv run --frozen python`:

```python
from spicy_docs.sources.congress.record_speeches import parse_record_speeches

document = parse_record_speeches(
    granule_html_bytes,
    granule_mods_bytes,
    "CREC-2026-09-16-pt1-PgH5835-8",
    max_html_bytes=1024 * 1024,
    max_mods_bytes=1024 * 1024,
)

print(document.package_id, document.parse_status, document.chamber, document.pages)
for item in document.items:
    print(item.item_index, item.kind, item.turn, item.speaker, item.speaker_bioguide, item.line_start, item.line_end)
```

**Each granule's own MODS is the small-document path**: one document of a few
kilobytes per granule, the one `acquire_granule` retains, read as above.
**The issue's package MODS is the batch path**: parse it once with
`read_record_issue(mods, max_mods_bytes=...)` and read each granule with
`issue.speeches(granule_html, granule_id, max_html_bytes=...)`. Upstream parses
a MODS with BeautifulSoup (0.4-0.7 s and about 55 MB retained for the 3.6 MB
CREC-2026-09-16 package MODS, measured 2026-09-28) and indexes its accessIds in
the same pass, so each granule is a dictionary lookup plus its own lines, and a
whole issue costs one read of its MODS, linear in its elements, plus its
granules' lines. Measured at the pin over the review's 523 real granules of
four issues against their package MODS: 1.81 s to read and index the four
MODS, then a median of 0.59 ms a granule, against 6.11 ms when upstream
scanned the whole MODS per granule (`measurements.txt` in
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/pin-3715651a/`).

Without the extra, the module still imports; `parser_available()` answers
whether it is installed, and every reading refuses with the install command.

## Input shape

- **The granule body**: the HTML rendition exactly as GovInfo serves it, at
  `content/pkg/{package_id}/html/{granule_id}.htm`;
  `GovInfoBodyAcquirer.acquire_granule(...).body_capture.body` retains it.
- **The MODS**, in either shape, told apart from the document itself:
  - *the granule's own*, as `acquire_granule(...).mods_capture.body` retains it
    (keyed, `packages/{package_id}/granules/{granule_id}/mods`) or as GovInfo
    serves it keyless at `https://www.govinfo.gov/metadata/granule/{package_id}/{granule_id}/mods.xml`.
    Its root states the granule and a `relatedItem type="host"` states the
    package. It reads only that granule; another refuses by name.
  - *the issue's package MODS*, as `acquire(package_id).mods_capture.body`
    retains it or keyless at `https://www.govinfo.gov/metadata/pkg/{package_id}/mods.xml`.
    It has no host, and its root states the package.

  Either way the stated package must be a CREC issue; it becomes `package_id`,
  the column `record_issues.package_id` joins on. The granule id must begin
  `CREC-{issue date}-`, the date `parse_package_id` reads from the package id,
  and not with the package id itself: GovInfo spells a granule id without its
  package's `-v{N}`/`-i{N}` suffix (package CREC-2025-03-11-i46 holds
  CREC-2025-03-11-pt1-PgS1677-4, a fixture), and one granule id can belong to
  two packages (CREC-2025-03-11-pt1-PgS-FrontMatter is in CREC-2025-03-11 and in
  CREC-2025-03-11-i46). So the prefix checks only the date, and membership is
  the MODS's: a granule's own MODS names its host, and upstream finds the
  granule's accessId in a package MODS or refuses. The two routes serialize the
  same granule MODS differently (for CREC-2026-09-16-pt1-PgH5835-8, 6,432 bytes
  keyless and 7,833 keyed, equal apart from whitespace and namespace-declaration
  order), and both read alike.
- **Byte bounds** are required keyword arguments, checked with the shared
  `check_payload` rule before either input is parsed.
- **The MODS is read by [the MODS mapping](govinfo-metadata.md) first**, the
  bounded reader that refuses entity declarations, and its accessIds are read
  the way the [GovInfo body routes](govinfo-bodies.md) read them, before
  upstream's own parser sees it.

Upstream reads both files from disk, in text mode with the locale's encoding.
The adapter decodes each input as UTF-8, writes it into a temporary directory in
upstream's layout in the locale's encoding, and reads it back through the same
`open()` call upstream makes. Input that is not UTF-8, that the locale cannot
encode, or that would not read back unchanged -- a carriage return, which
universal newlines fold -- refuses rather than reaching upstream as different
text. So what upstream reads is the retained bytes decoded as UTF-8, exactly;
the check does not require ASCII. The review's retained real Record on
2026-09-28 -- 1,076 files, the bodies, granule MODS and package MODS of 535
granules from six issues, 1996-2026 -- all decode as UTF-8 and none holds a
carriage return, so none of these refusals has been seen on publisher bytes.
Four hold U+FFFD, the replacement character, as published (the body of
CREC-1996-03-28-pt1-PgD293-3, a granule MODS and two package MODS); under a
UTF-8 locale all four read back unchanged, and every granule read against them
parses complete (receipt `review-fixes/real-replay/` under
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/`).

Upstream looks up the granule's accessId and reads the record around it, so
the granule's own MODS and the package MODS give it the same record. Measured
2026-09-28, the adapter's documents from the two are equal apart from
`mods_sha256` on every one of those 535 granules (`real-replay/`) and for
CREC-2026-09-16-pt1-PgH5835-8 on both granule-MODS routes, and upstream's are
equal for CREC-2026-09-18-pt1-PgS4837-4.

## Output

`RecordSpeechDocument` carries the granule and package ids, `parse_status`,
`parse_error`, `lines_exhausted`, upstream's `header` (read through `vol`, `num`,
`chamber`, `pages` and `extension`), `title`, `doc_title`, the related bills,
laws, U.S. Code sections and Statutes at Large pages upstream read from the
granule's MODS record, unmodified, the items, `source_lines`,
`unaccounted_lines`, both inputs' `sha256:` digests and `parser_pin`.

Each `RecordSpeechItem` carries upstream's `kind`, `speaker` exactly as upstream
spelled it, `speaker_bioguide`, `text`, `turn` (speech items only), the line
span and `source_item`, the whole item upstream emitted as a read-only mapping.
An item no line kind matched has kind and speaker `"Unknown"`; a kind that
names no speaker (a rule, a title) has speaker `None`, and an absent bioguide
id or unmatched search title is `None`, as upstream returns them.

### Line spans

Upstream records no source position, so the adapter locates each item.
`source_lines` is the granule's `<pre>` text as upstream's own reader split it,
up to the last line it read; that reader first folds a line-leading `<bullet>`
and the whitespace around it into one space. `line_start` and `line_end` are 0-based, inclusive
indexes into it.

- The first item starts on the line where upstream's title scan stopped,
  observed from upstream's own run, not inferred.
- Every later line is found in order and never backtracking, passing over only
  the lines upstream drops from an item's text: whitespace-only lines, `{time}`
  stamps and `[[Page]]` markers. A span therefore contains the item's lines and
  any dropped lines between them.
- An item whose lines are not found that way is `unlocated`, with both
  coordinates `None`, and so is every item after it. A span is never guessed.

On every fixture every item is located, the spans tile the text after the
title, and each span's lines less the dropped ones join to the item's text; the
test checks this with its own line rule, not upstream's patterns.

### Lines nothing accounts for

The same coverage is checked on every read, and reported rather than refused,
so a partial parse keeps its items. `unaccounted_lines` is the 0-based indexes
into `source_lines` of every line that is none of:

- a header line (upstream refuses a header it cannot read);
- a blank or title line its title scan read before the first item;
- a text line of a located item;
- a whole whitespace-only line, `{time}` stamp or `[[Page]]` marker.

Upstream's skip patterns match only a line's start, so a skipped line that
carries text after its marker is text no item holds; it is listed, as are the
lines of unlocated items and the line a partial parse failed on. A caller that needs the whole granule requires
`parse_status == "complete"` and an empty `unaccounted_lines`. Over the 535 real
granules of the replay above, every one is complete and none lists a line.

### Partial parses and refusals

- **`parse_status` is upstream's own.** When an item raises, upstream keeps the
  items before it; the document says `partial` and `parse_error` names the
  exception type, message and the line being read. `lines_exhausted` is
  `False`. A partial parse is never reported as complete, and a parser build
  that does not report completion at all refuses.
- **Every upstream failure is a `RecordSpeechesError` naming the granule**:
  a granule absent from the MODS, a body with no `<pre>` block, and a header
  cut short or astray, which upstream raises as `CRParseError` and the refusal
  wraps, saying which header line failed.
- **Granule ids must be this issue's.** The id becomes the file name upstream
  reads the accessId from, up to the first dot, so an id with a dot, a path
  separator or another date's prefix refuses.
- **The body's header must start on the id's page, in the MODS record's
  issue.** Upstream compares neither, so a body retained under the wrong id
  would read as that granule.
  - *Page.* A granule id names its first page (`-PgH5835-8` starts on H5835)
    or only its section: front matter (`-PgH-FrontMatter`) and, in 1994, a
    section's first granule (`-PgH`, `-PgD`). The adapter refuses when the
    header's first page differs, compares the section alone where the id names
    no page or the header states no page number, and refuses an id that names
    neither. GovInfo states no page number in 1994 (`[Page H]` in the header,
    `<start>H</start>` in the MODS), and there an id's number (`-PgH10`) orders
    the section's granules. Every granule accessId in the 2026-09-28 reviews'
    retained package MODS, 1994 to 2026, has one of these shapes, and all 129
    granules of CREC-1994-03-25 read complete held to their section
    (`rereview-fixes/replay/` under
    `~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/`).
  - *Issue.* The header's volume and number must equal the ones upstream reads
    from the granule's MODS record (its searchTitle); a record that states none
    is not compared. One granule id can be in two packages with different
    bodies (CREC-2025-03-11-pt1-PgS-FrontMatter is in No. 45 and in No. 46),
    and held to its section only, either body would read under either MODS.
  - *What it cannot see:* another granule that starts on the same page of the
    same issue. 418 of the 523 granules of the review's four issues share
    their first page, or front matter its section, with another granule of
    their issue (`rereview-fixes/replay/shared_pages.txt`); the Kiggans body
    reads complete under `-PgH5835-7`, with no bioguide id for her because
    that record does not name her. That a body is its id's is the
    [GovInfo body routes'](govinfo-bodies.md) to prove.

Parses may run concurrently. Upstream writes each document's speaker pattern
from its MODS into the line-kind table that document reads, and the pin copies
the table per document, so another document read meanwhile leaves it as it was.
A test reads a granule whose speaker only its MODS names while another granule
is read between that write and its items, and gets its reading alone; with one
shared table the speech folds into the item before it. The speaker list alone
decides a speech rarely: on the review's 535 real granules and the 250
labelled documents, #90's general pattern matched the first line of all 22,030
speech items without it (`rereview-fixes/mods-only-speakers/`).

## What this does not establish

- **Who spoke, beyond the MODS.** `speaker_bioguide` is the id the granule's
  MODS record states for the speaker name upstream matched. A presiding officer,
  the Speaker pro tempore or a clerk has none, and a name the MODS does not list
  has none. Nothing here resolves a person.
- **Segmentation accuracy across the corpus.** The fixtures pin a few
  granules, and the replays read 535 from 1996 to 2026 and all 129 of
  CREC-1994-03-25 complete with every line accounted for. That shows every
  line landed in some item, not that each item's kind is right. At the pin, the speaker pattern matched 768 of the 772
  hand-labelled speech starts in PR #90's 250 labelled windows (99.5%,
  precision 99.6%; `measurements.txt` in `~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/pin-3715651a/`); upstream's rules are line
  patterns, and other kinds and eras are not measured here.
- **Completeness of a partial parse.** Its items are the ones before the
  failure; the rest of the granule was not read.
- **Acquisition.** The adapter parses bytes a caller retained; identity of the
  body and MODS is proved by the [GovInfo body routes](govinfo-bodies.md).

## The pin

The extra installs `congressionalrecord==2.3.0` from
[mikewolfd/congressional-record](https://github.com/mikewolfd/congressional-record),
branch `spicy-docs-pin`, at the commit `PARSER_PIN` names in
`sources/congress/record_speeches.py`, and `beautifulsoup4==4.14.3`, the version
the `html` extra pins and the gate tests; without the pin a host resolves
whatever is newest (spicy-regs resolved 4.15.0 in the review's simulation).
Over upstream `84a5af4` the fork branch carries three changes offered upstream,
one upstream pull request merged in, and two commits that stay on the fork:

- [unitedstates/congressional-record#92](https://github.com/unitedstates/congressional-record/pull/92)
  ships the `govinfo` subpackage and SQL files in the wheel, admits a speaker
  line indented up to three spaces, and adds `parse_status`/`parse_error`.
- [unitedstates/congressional-record#93](https://github.com/unitedstates/congressional-record/pull/93)
  declares what the package's non-PostgreSQL modules import -- the parser, the
  downloader and the schema: `beautifulsoup4`, `lxml`, `urllib3`, `certifi`,
  `pydantic>=2` -- moves the PostgreSQL writer's `psycopg2-binary`,
  `SQLAlchemy`, `PyYAML` and `unicodecsv` behind a `postgres` extra, and drops
  `numpy`, `requests`, `future` and `soupsieve`, which nothing imports. The
  `record-speeches` extra does not ask for `postgres`: a clean
  `uv sync --frozen --no-dev --extra record-speeches` on 2026-09-28 added
  `congressionalrecord`, `beautifulsoup4`, `soupsieve`, `lxml`, `urllib3`,
  `certifi` and `pydantic` with its three dependencies, and none of the
  PostgreSQL stack, `numpy` or `requests` (re-run at this pin).
- [unitedstates/congressional-record#94](https://github.com/unitedstates/congressional-record/pull/94)
  copies the line-kind table per document instead of writing each document's
  speaker pattern into the class's, returns `None` rather than the string
  `"None"` for an absent value, raises `CRParseError` for a header cut short or
  astray, and indexes a MODS's accessIds once instead of scanning the whole
  MODS per granule.
- [unitedstates/congressional-record#90](https://github.com/unitedstates/congressional-record/pull/90)
  (jutton1, `fix-text-mislabeling`), merged in: a wider speaker pattern and
  `<bullet>` folding. On the review's 523 real granules its only change to the
  items was the whitespace of three items in two documents (`measurements.txt`
  in `pin-3715651a/`).
- Fork-only commits pin the build backend to `setuptools==84.0.0`, so the
  wheel a host vendors is reproducible, and prune the tests from the sdist.

The reasons for a fork are recorded under
["congressionalrecord is a pinned fork dependency, not a port"](../decisions.md#congressionalrecord-is-a-pinned-fork-dependency-not-a-port).

`PARSER_PIN` in the module, the `[tool.uv.sources]` revision and the commit
`uv.lock` resolves are held equal by a test.

**What `parser_pin` on a document guarantees.** Every revision of the fork
installs as `congressionalrecord==2.3.0`, so the version cannot tell them
apart. A git install records the commit it resolved (`direct_url.json`), and a
read refuses unless that commit is `PARSER_PIN`, naming both. A vendored wheel
records none, so every install is also held to the fork's surface:
`CRParseError`, `parse_status` on the document and a line-kind table of the
document's own; a build lacking any of them refuses. So on a git install
`parser_pin` is the commit that read the document; on a wheel it is the commit
the host built the wheel from, which that surface and the wheel digest in the
host's lock stand behind.

**A vendored wheel is built by one rule, all four parts of it:**

1. `git archive` the pinned fork commit into an empty directory;
2. `umask 022` before extracting and building, because the zip records each
   file's mode;
3. `SOURCE_DATE_EPOCH` set to that commit's time (`git log -1 --format=%ct`),
   because the zip records timestamps;
4. `uv build --wheel`, with the build backend the branch pins.

Nothing else moves the digest. For the pin as of 2026-09-28 that is
`SOURCE_DATE_EPOCH=1790630841`, giving a 26,308-byte, 23-file wheel with sha256
`abb9a47cfae7991c01258da76427092b05290f572489278ff09a0fe79a73cbe2`, identical
from separate archives built by the fork's owner and again for this repository
(receipts `pin-3715651a/`, with `SHA256SUMS`, and
`review-fixes/repin-3715651a/wheel/`, under
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/`).
Under `umask 002` the previous pin's archive gave
`e8adfa11b055c53c6629ee212b9cb6aafa177079ff634e566868df2060715401` instead of
its `b5fd9280…` (`review-fixes/wheel-umask/`), and without the variable the zip
timestamps, and so the digest, change per checkout.

**Move the pin** by changing the revision in `pyproject.toml` and `PARSER_PIN`
together, running `uv lock`, rebuilding the wheel by the rule above, recording
its digest here, and running this guide's tests.
**When upstream merges #92, #93, #94 and #90 and publishes a release**, delete the
`congressionalrecord` entry from `[tool.uv.sources]`, pin the release in the
extra, and replace `PARSER_PIN` and its lockstep test with the release version.

### Hosts

A host that vendors spicy-docs wheels, as spicy-regs does, cannot resolve this
extra from a registry: nothing is published under `congressionalrecord`. It
vendors the `congressionalrecord` wheel built by the rule above beside the
spicy-docs wheel, declares `congressionalrecord==2.3.0` directly in both of its
`source-readers` lists (the optional-dependency extra and the dependency
group), and binds it to the wheel in `[tool.uv.sources]`, for example
`congressionalrecord = { path = "vendor/congressionalrecord-2.3.0-py3-none-any.whl" }`.
That is the shape spicy-regs already uses for `deltatrack`, which reaches it
only through spicy-docs' `bill-diff` extra, and for `rulespec-artifacts`: a uv
source binds only a dependency the project itself declares, so without the
direct declaration uv looks for `congressionalrecord` in the registry and the
resolve fails (the review's spicy-regs simulation, 2026-09-28:
`regs-lock-without-direct.log` fails, `regs-lock.log` resolves, under
`~/Work/corpora/fork-execution-2026-09-21/record-speeches-review/`). The vendored
wheel's sha256 then goes into the host's lock, and its `vendor/README.md`
records how it was built.

### To raise upstream

Still true at the pin (file:line there); the adapter works around both.

- **Files are read in the locale's encoding.** Both `open()` calls pass no
  encoding (`cr_parser.py:89`, `:342`), so the same bytes read differently
  under another locale. The adapter writes in that encoding and proves the
  read-back (Input shape, above).
- **MODS is read with BeautifulSoup's HTML parser** (`cr_parser.py:90`), which
  lower-cases element names and warns on a document with an XML declaration,
  as a granule's own MODS has. Upstream looks its tags up lower-cased, so it
  reads correctly; the warning is filtered in the tests.

## Fixtures

Whole granule bodies, granules' own MODS and bounded package-MODS excerpts are
in [`tests/fixtures/record_speeches/`](../../tests/fixtures/record_speeches/README.md),
with their provenance and the excerpt method.
