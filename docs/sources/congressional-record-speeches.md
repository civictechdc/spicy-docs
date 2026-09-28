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

A granule's own MODS is a few kilobytes and is the cheap route. With a
package MODS, parse it once with `read_record_issue(mods, max_mods_bytes=...)`
and read each granule with `issue.speeches(granule_html, granule_id,
max_html_bytes=...)`: upstream parses the MODS with BeautifulSoup, measured on
2026-09-28 at 0.4-0.7 s and about 55 MB retained for the 3.6 MB CREC-2026-09-16
package MODS, against 1-9 ms per granule after that.

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
  the column `record_issues.package_id` joins on, and the granule id must begin
  with it. The two routes serialize the same granule MODS differently (for
  CREC-2026-09-16-pt1-PgH5835-8, 6,432 bytes keyless and 7,833 keyed, equal
  apart from whitespace and namespace-declaration order), and both read alike.
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
text. Every CREC body the supply corpus retained on 2026-09-28 (32 distinct,
1996-2026, this guide's fixtures among them), the three issue MODS retained
that day and both granule-MODS captures are ASCII with no carriage return, so none of these refusals has been
seen on publisher bytes.

Upstream looks up the granule's accessId and reads the record around it, so
the granule's own MODS and the package MODS give it the same record. Measured
2026-09-28, the adapter's documents from the two are equal apart from
`mods_sha256` for CREC-2026-09-16-pt1-PgH5835-8 (both granule-MODS routes), and
upstream's are equal for CREC-2026-09-18-pt1-PgS4837-4.

## Output

`RecordSpeechDocument` carries the granule and package ids, `parse_status`,
`parse_error`, `lines_exhausted`, upstream's `header` (read through `vol`, `num`,
`chamber`, `pages` and `extension`), `title`, `doc_title`, the related bills,
laws, U.S. Code sections and Statutes at Large pages upstream read from the
granule's MODS record, unmodified, the items, `source_lines`, both inputs'
`sha256:` digests and `parser_pin`.

Each `RecordSpeechItem` carries upstream's `kind`, `speaker` exactly as upstream
spelled it, `speaker_bioguide`, `text`, `turn` (speech items only), the line
span and `source_item`, the whole item upstream emitted as a read-only mapping.
Upstream spells an absent bioguide id and an unmatched search title as the
string `"None"`; `speaker_bioguide` and `doc_title` read those as `None`.

### Line spans

Upstream records no source position, so the adapter locates each item.
`source_lines` is the granule's `<pre>` text as upstream's own reader split it,
up to the last line it read. `line_start` and `line_end` are 0-based, inclusive
indexes into it.

- The first item starts on the line where upstream's title scan stopped,
  observed from upstream's own run, not inferred.
- Every later line is found in order and never backtracking, passing over only
  the lines upstream drops from an item's text: whitespace-only lines, `{time}`
  stamps and `[[Page]]` markers. A span therefore contains the item's lines and
  any dropped lines between them.
- An item whose lines are not found that way is `unlocated`, with both
  coordinates `None`, and so is every item after it. A span is never guessed.

On all three fixtures every item is located, the spans tile the text after the
title, and each span's lines less the dropped ones join to the item's text; the
test checks this with its own line rule, not upstream's patterns.

### Partial parses and refusals

- **`parse_status` is upstream's own.** When an item raises, upstream keeps the
  items before it; the document says `partial` and `parse_error` names the
  exception type, message and the line being read. `lines_exhausted` is
  `False`. A partial parse is never reported as complete, and a parser build
  that does not report completion at all refuses.
- **Every upstream failure is a `RecordSpeechesError` naming the granule**:
  a granule absent from the MODS, a body with no `<pre>` block, a header too
  short to read.
- **Granule ids must be this issue's.** The id becomes the file name upstream
  reads the accessId from, up to the first dot, so an id with a dot, a path
  separator or another package's prefix refuses.

Parses run one at a time. Upstream keeps its line-kind table on the class and
writes each document's speaker pattern into it (`cr_parser.py:259`), which its
item builder reads mid-parse, so two threads would read each other's speakers.

## What this does not establish

- **Who spoke, beyond the MODS.** `speaker_bioguide` is the id the granule's
  MODS record states for the speaker name upstream matched. A presiding officer,
  the Speaker pro tempore or a clerk has none, and a name the MODS does not list
  has none. Nothing here resolves a person.
- **Segmentation accuracy across the corpus.** Three granules from September
  2026 are pinned. Upstream's rules are line patterns; how often they misclassify
  a line in other eras is not measured here.
- **Completeness of a partial parse.** Its items are the ones before the
  failure; the rest of the granule was not read.
- **Acquisition.** The adapter parses bytes a caller retained; identity of the
  body and MODS is proved by the [GovInfo body routes](govinfo-bodies.md).

## The pin

The extra installs `congressionalrecord==2.3.0` from
[mikewolfd/congressional-record](https://github.com/mikewolfd/congressional-record),
branch `spicy-docs-pin`, pinned to commit
`6bb521b11b498f2e8dbac614a4394c703c6773ac`. Over upstream `84a5af4` it carries
two changes offered upstream and one that stays on the fork:

- [unitedstates/congressional-record#92](https://github.com/unitedstates/congressional-record/pull/92)
  ships the `govinfo` subpackage and SQL files in the wheel, admits a speaker
  line indented up to three spaces, and adds `parse_status`/`parse_error`.
- [unitedstates/congressional-record#93](https://github.com/unitedstates/congressional-record/pull/93)
  declares what the parser imports -- `beautifulsoup4`, `lxml`, `urllib3`,
  `certifi`, `pydantic>=2` -- moves the PostgreSQL writer's `psycopg2-binary`,
  `SQLAlchemy`, `PyYAML` and `unicodecsv` behind a `postgres` extra, and drops
  `numpy`, `requests`, `future` and `soupsieve`, which nothing imports. The
  `record-speeches` extra does not ask for `postgres`: a clean
  `uv sync --frozen --no-dev --extra record-speeches` on 2026-09-28 added
  `congressionalrecord`, `beautifulsoup4`, `soupsieve`, `lxml`, `urllib3`,
  `certifi` and `pydantic` with its three dependencies, and none of the
  PostgreSQL stack, `numpy` or `requests`.
- A fork-only commit pins the build backend to `setuptools==84.0.0`, so the
  wheel a host vendors is reproducible.

The reasons for a fork are recorded under
["congressionalrecord is a pinned fork dependency, not a port"](../decisions.md#congressionalrecord-is-a-pinned-fork-dependency-not-a-port).

`PARSER_PIN` in the module, the `[tool.uv.sources]` revision and the commit
`uv.lock` resolves are held equal by a test.

**A vendored wheel is built from the pinned commit with `SOURCE_DATE_EPOCH` set
to that commit's time** (`git log -1 --format=%ct`), from a `git archive` of it
in an empty directory, with `uv build --wheel`; the branch pins the build
backend, so the digest depends on nothing else. At the pin that is
`SOURCE_DATE_EPOCH=1790623777`, giving a 24,814-byte, 23-file wheel with sha256
`b5fd928072ec1fc38d5a82842b622fb55ab14bcc18b9ca576bee1731855fc897`, identical
from two separate archives (2026-09-28; receipt
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/`,
with `SHA256SUMS`). Without the variable the zip timestamps, and so the digest,
change per checkout.

**Move the pin** by changing the revision in `pyproject.toml` and `PARSER_PIN`
together, running `uv lock`, rebuilding the wheel by the rule above, and
running this guide's tests.
**When upstream merges #92 and #93 and publishes a release**, delete the
`congressionalrecord` entry from `[tool.uv.sources]`, pin the release in the
extra, and replace `PARSER_PIN` and its lockstep test with the release version.

### To raise upstream

Not patched here; file:line is at the pin.

- **`find(text=...)` is deprecated** in BeautifulSoup 4.13 and later
  (`cr_parser.py:239`); a release that removes `text` breaks the accessId
  lookup. `string=` is the replacement.
- **Shared class state.** `gen_file_metadata` writes the document's speaker
  pattern into the class-level `item_types` (`cr_parser.py:259`), so parses are
  not thread-safe. The adapter serializes them.
- **Sentinel strings.** A missing bioguide id, member attribute or search
  title is the string `"None"` (`cr_parser.py:143-154`, `:250`), not `None`.
- **A short body raises `StopIteration`** out of `get_header`
  (`cr_parser.py:295-322`) rather than a parse error.
- **The `Issues` project URL** misspells the organization (`unitestates`,
  `pyproject.toml:35`).

## Fixtures

Three whole granule bodies and two bounded MODS excerpts are in
[`tests/fixtures/record_speeches/`](../../tests/fixtures/record_speeches/README.md),
with their provenance and the excerpt method.
