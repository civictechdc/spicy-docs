# Choose a source workflow

Choose the output first. SpicyDocs acquires source records and preserves their
provenance; the caller chooses the source and scope.

## Choose the output you need

| You need | Use | Keep and check |
| --- | --- | --- |
| Records with exact acquisition evidence and offline replay | `publish` a supported source for explicit dates, agencies, or product IDs | Keep the release, blob store, and artifact pin. `inspect` checks admission and reports outcomes; `verify` reconstructs records and failures. |
| Flat Parquet rows from a release | `publish-public-table` for Federal Register or Mirrulations | Keep the table pin and input release. Publication checks every row; `verify-public-table` checks admission. The library verifier also checks rows. |
| Exact metadata or original files from a caller-selected public publisher | `spicy_docs.transport.download.BoundedAcquirer` | Supply URL validation and byte bounds; optional public-site Zyte recovery uses the same request budget and blob writer. Dataset selection and recovery remain with the caller. |
| Parsed dictionaries in an application that owns recovery | A Mirrulations, CourtListener or FEC raw reader | The caller retains input pins, failures, checkpoints, and completion evidence. A raw read has no release verification. |
| An immutable release of a retained OpenFEC committee census or filing query | The [FEC profiles](sources/fec.md#publish-a-retained-committee-census) and existing publisher | Pin every capture, replay exact JSON, check page/count/ID membership, and retain observed-crawl scope. Other FEC families remain raw-reader inputs. |
| Complete GovInfo MODS metadata | The [MODS mapping](sources/govinfo-metadata.md), available with annual CFR edition capture | Keep the original response and mapped package/constituents. Repeated fields, attributes and unknown extensions survive; advertised links remain unfetched. |
| One public law, one statute compilation, or a whole bulkdata zip of either | The [USLM routes](sources/uslm-laws.md) | Keep the exact XML or zip and its receipt. Native identity is proved per file; compilation currency stays as the compiler wrote it. |
| Exact pages of a publisher list query with declared counts checked | The [list routes](sources/listings.md): Congress.gov, GovInfo, GAO feed, LDA, CourtListener, SAM.gov, USAspending, FCC ECFS | Keep every page's bytes; the walk refuses to end early or inconsistently. A count is that day's statement, and zero is not absence. |
| One Unified Agenda edition with every record proved | The [Unified Agenda route](sources/unified-agenda.md) | Keep the exact XML; the 2004 editions refuse as malformed and stay the caller's to repair. |
| A U.S. Code title at a release point, an annual archive, the Popular Name Tool or Table III | The [U.S. Code routes](sources/uscode.md) | Keep the exact zip, page or bulk file; identity is proved from each title's own meta, never its file name. |
| A Supreme Court term index and the opinion PDFs it states | The [Supreme Court route](sources/supreme-court.md) | Keep the index render and each PDF; links are byte-exact revision tokens and the index is a live render. |
| A CRS, GAO, regulations.gov or CBO document PDF | The [CRS files](sources/crs-files.md), [GAO files](sources/gao-files.md), [regulations.gov API](sources/regulations-gov-api.md) and [CBO](sources/cbo.md) routes | Keep the exact bytes; every PDF is proved by its magic, its trailer and the final URL, plus each publisher's own completeness witness. |
| Text and observations from retained PDFs or images | The [extraction API](pdf-extraction-api.md), with an explicit page strategy and backend | Retain source bytes, metadata, body blocks and raw observations separately. Model output is derived evidence; extraction does not publish a source release. |
| Source fields from retained FOIA XML or Oversight.gov report pages | The [agency-report readers](sources/agency-reports.md) | Native XML elements remain traceable; HTML descriptions and recommendation tables stay separate from metadata. Linked originals are acquired independently. |

Use the [CLI commands](cli.md), [raw-reader APIs](sources/raw-readers.md), or
[offline GAO example](../examples/offline_release.py). The example requires no
network or credentials and leaves inspectable output.

## Know what each source supplies

| Source | Input | Captured result and coverage limit |
| --- | --- | --- |
| [Federal Register](sources/federal-register.md) | Inclusive publication dates | Exact API responses, metadata, and body links. Two consecutive crawls agree within the requested dates; no frozen publisher-wide version is established. |
| [Mirrulations](sources/regulations-gov.md) | Agencies, collection, dates | Exact JSON objects and selected documents, dockets, or comments. Date selection follows live listing acquisition; objects are pinned individually. |
| [Community comments](sources/public-comments.md) | Agencies | Exact Parquet parts and rows. Discovery stops at the first missing numbered part; later parts are unrequested. |
| [FEC](sources/fec.md) | Explicit API filters, bulk prefixes, sitemaps or selected originals | Metadata and retained responses; linked bodies are acquired separately. Committee and processed-filing profiles can seal one pinned observed query. Raw-reader output and other families do not automatically become releases. |
| [GAO](sources/gao.md) | Product IDs | Exact HTML, product identity, and one literal publisher topic per page. Other products and linked report files are outside the capture. |
| [Congressional bills](sources/congress-bills.md) | Explicit bill IDs and text-version package IDs | BILLSTATUS metadata and selected XML text with exact captures and identity checks. This API does not enumerate a collection or publish a release. |
| [CFR/eCFR](sources/cfr.md) | Explicit route, title and date/edition where supported | Regulation XML and separately requested annual edition metadata, including publisher-stated cover-only status. Exact payloads and native identity/date checks; no collection discovery or release publication. |
| [Public laws and statute compilations](sources/uslm-laws.md) | Congress, kind and law number; compilation file identifier; or one bulkdata zip | Exact USLM XML with native identity checks per file. Archives validate every entry against its own name. No release publication; private-law folders exist for only some Congresses. |
| [Publisher list pages](sources/listings.md) | One explicit list query per publisher: a date or lastModified window, a package's granules, a search, a registration window, a POST body, or the GAO feed | Exact JSON or RSS pages with rows as the publisher spelled them. Declared counts are checked against observed rows where the publisher states one; a bounded walk that cannot reach the terminal page refuses. |
| [Unified Agenda](sources/unified-agenda.md) | One edition file stem | Exact edition XML; every record proves its RIN and edition. |
| [U.S. Code](sources/uscode.md) | Release point and title, an archive year, or a Table III key | Exact OLRC files with native identity; absent acts answer 200 with a truncated page and are refused. |
| [Supreme Court](sources/supreme-court.md) | Term code, then an index-stated PDF link | Exact index and PDF bytes; a wrong-term render is refused. |
| [CRS files](sources/crs-files.md) | The publisher's stated file URL, or id and version | Exact signed PDF; family directories are not always the id prefix. |
| [GAO files](sources/gao-files.md) | Product id and rendition | Exact PDF from the keyless file host; the web host is gated. |
| [regulations.gov API](sources/regulations-gov-api.md) | A filtered document query, a document id, or a stated attachment locator | Exact pages and PDFs; the reachable count is capped at forty pages and the declared count drifts. |
| [CBO](sources/cbo.md) | A Congress number, or a feed-stated document link | Exact per-Congress feed; the site's XML feed and documents sit behind a bot wall. |

Prefer community SpicyRegs tables when they supply the needed data; choose origin
acquisition for uncovered needs. This [supply rule](decisions.md#community-supply-precedes-origin-acquisition)
requires an explicit source choice. SpicyRegs' public pipeline and this package's
optional public-table export are separate products.

## Read the result before using it

Read `collectionOutcome` for selectors, discovery assumptions, counts, and record
rejections. **Accepted empty input describes an observation, not source absence.**
An acquisition refusal leaves the request unresolved and publishes no partial
release. See [outcomes](source-native-outcomes.md) and
[failed-run evidence](cli.md#output-and-failures).

Verification checks agreement among retained bytes, source rules, and records;
it does not authenticate the publisher. Retention covers acquisition inputs and
selected refused bodies, not every retry or discovery probe. Admission uses
bounded memory but reads payloads to check hashes; full replay repeats source
interpretation.

## Stop at a useful boundary

An admitted release is usable on its own: inspect it, stream records, retain it,
or export a supported table. Rendition rows describe locators and source metadata;
they do not establish downloaded or hashed body content.

The [Federal Register body API](federal-register-body-sources.md) separately
prefers publisher XML, checks identity, and returns exact bytes. It falls back
to GovInfo HTML only after XML 404/410; strict XML and explicit HTML are available.

Use DocSpec when combining sources, document fetchers, processors, and successive
runs. Its optional sibling-checkout [walkthrough](../../DocSpec/docs/offline-walkthrough.md),
[capabilities](../../DocSpec/README.md#what-you-can-use-today), and
[GAO example plan](../../DocSpec/docs/dataset-experiments-todo.md#d51) cover that
work. Literal publisher topics alone establish no legal requirement,
applicability, or taxonomy match.

A schema or [field reference](source-reference.md) describes supported data,
not a working live fetcher. Offline fixtures establish behavior for their inputs,
not live availability or coverage. Planned integrations stay in the
[to-do list](simplification-todo.md).
