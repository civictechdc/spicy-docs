# Read retained agency reports

SpicyDocs provides two offline readers for agency-report inputs. Prefer native
FOIA XML. Use Oversight.gov HTML for the report fields and recommendations present
in retained pages. Keep each original beside the returned source digest; parse
results do not contain the original bytes or establish current collection coverage.

```python
from pathlib import Path
from spicy_docs.sources.foia import parse_foia_annual_report
from spicy_docs.sources.oversight import parse_oversight_report

annual = parse_foia_annual_report(Path("fec-2025.xml").read_bytes())
report = parse_oversight_report(
    Path("report.html").read_bytes(),
    url="https://www.oversight.gov/reports/evaluation-fecs-data-act-compliance",
)
```

FOIA parsing uses the core package's bounded XML scanner. Oversight parsing needs
the `html` extra (`spicy-docs[html]`), which supplies BeautifulSoup. Importing either
module needs neither HTTP support nor HTML dependencies. Both functions accept
bytes and return JSON-compatible dictionaries; neither makes network requests.

## FOIA annual XML

`parse_foia_annual_report(body, *, max_bytes=4*1024**2, max_elements=100_000)`
supports native NIEM FOIA exchange versions `1.02` and `1.03`. Version `1.02`
names its year `DocumentFiscalYear`; `1.03` uses `DocumentFiscalYearDate`.
The reader requires one nonblank scalar fiscal year and a native organization.
The fiscal year remains literal text, including source whitespace.

| Output | Meaning |
| --- | --- |
| `source` | SHA-256 prefixed with `sha256:` and input byte count. |
| `metadata` | Schema version, fiscal year, organizations and creation dates, with indices into `elements`. |
| `elements` | Every element in source order: expanded tag and attribute names, declarations of namespace prefixes, direct text, tail text, parent index and child-index path. |

Paths count element children from zero; the root path is `[]`. Namespace
declarations belong to their declaring element and can be inherited along the
parent chain. Repeated associations, unknown elements, empty fields, nil attributes
and numeric spellings survive. The reader does not coerce amounts, resolve
associations, deduplicate entries or validate an XSD. Comments, processing
instructions and lexical XML spelling remain in the original bytes.

The scanner rejects malformed XML, DTDs/entities, excessive bytes/elements and
nesting beyond 64 elements. `FoiaReportError` also distinguishes unsupported roots,
including Word Flat OPC packages published with an `.xml` extension. Retain those
packages for separate document processing; they are not native FOIA statistics.

## Oversight report HTML

`parse_oversight_report(body, *, url, max_bytes=8*1024**2, max_fields=1000,
max_depth=128)` reads one retained UTF-8 report page. Supply its explicit HTTPS
`www.oversight.gov/reports/…` URL without query parameters or fragments. This URL
provides provenance and relative-link resolution; it does not authenticate the
bytes. A report needs one `main`, one report article, one page title and native
field containers. The title can appear in the page header, outside `main`.

| Output | Meaning |
| --- | --- |
| `source` | Supplied URL, input SHA-256 and byte count. |
| `metadata.fields` | Ordered native field names, labels, values/items, dates, numeric attributes, links and source positions. Unknown and repeated fields remain visible. |
| `bodies` | Report descriptions and recommendation sections. Metadata references their indices; description text/items live here. |
| `bodies[].tables` | Recommendation rows/cells in source order, including headers, attributes, spans, blank cells, literal amounts and narrative rows. |
| `assets` | Declared report links and document candidates from fields, with field associations and original/resolved URLs. Repeated links remain separate occurrences. |

All links under `main` also remain in `metadata.links`. A decoded Outlook Safe
Links target is an observation, not approval to fetch it. Linked originals are
acquired separately through the existing bounded downloader. Collection selection,
allowlisted source hosts and retry policy stay with the caller.

Text uses BeautifulSoup's whitespace-normalized display extraction. Locations are
one-based lines and zero-based character columns in decoded HTML, not byte offsets.
Outermost field items preserve repeated agencies without treating nested file-media
wrappers as additional values. Recommendation sections outside the report article
are included. The reader preserves numbered rows and following narrative rows as
printed; it does not infer joins, totals or current recommendation status.

`OversightReportError` reports unsupported shapes, duplicate attributes, nested
fields/recommendation sections/tables/rows, unclosed report containers and exceeded
bounds. These checks recognize the supported page shape; they are not a general
HTML validator. Unmapped markup remains available in retained originals. Byte and
depth bounds limit parsing; disjoint source blocks prevent repeated extraction of
nested records.

## Evidence and remaining work

Pinned fixtures cover complete native FOIA XML and an Oversight page with report
metadata, a linked PDF and recommendation tables. The
[qualification record](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-agency-interfaces-2026-09-14/README.md>)
records retained-source replay, known-answer tests, deliberate failure checks and
package validation. The initial replay exposed the older fiscal-year name above;
that input now remains a regression fixture.

These readers promote source parsing from research into the provider API.
Historical research scripts remain dated evidence. Receiving applications still
need to adopt the package; dataset backfills, Word extraction, recurring refresh,
immutable release profiles and SpicyRegs rollups have separate completion criteria.
