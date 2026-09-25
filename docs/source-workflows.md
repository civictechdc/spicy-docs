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
| An immutable release of a retained OpenFEC committee, filing, candidate, legal-search or audit query | The [FEC profiles](sources/fec.md#publish-a-retained-committee-census) and existing publisher | Pin every capture, replay exact JSON, check page/count/ID membership, and retain observed-crawl scope. Other FEC families remain raw-reader inputs. |
| An immutable inventory of retained FEC bulk originals | The [bulk file profile](sources/fec-bulk.md) and existing publisher | Stream exact originals; retain every ZIP member, including duplicate names. Release counts mean files; the separate row profile counts positional observations. |
| An immutable release of positional FEC bulk rows or native filing records | The [row profile](sources/fec-rows.md) and existing publisher | Select one original/member and explicit syntax. Keep row coordinates, literal fields and separate filing-body references; financial interpretation remains downstream. |
| Complete GovInfo MODS metadata | The [MODS mapping](sources/govinfo-metadata.md), available with annual CFR edition capture | Keep the original response and mapped package/constituents. Repeated fields, attributes and unknown extensions survive; advertised links remain unfetched. |
| GovInfo preservation metadata and a selected file's digest check | The [PREMIS reader](sources/govinfo-premis.md) and comparison API | Keep both exact captures. Every metadata object survives; only an unambiguous file location and supported digest can establish byte consistency. |
| The body of one committee report, hearing, Record issue, congressional document, directory or bill text | The [GovInfo body routes](sources/govinfo-bodies.md), by package id | Keep the summary, MODS and body captures. The package MODS states which renditions exist; an unoffered format redirects to a 200 error page and is refused, never recorded as absence. |
| Every field an appropriations committee's own press-release feed states | The [press-release source](sources/press-releases.md), keyless | Keep the exact channel and item bytes; identity is proved by checking the channel `<title>`/`<link>`, never the request URL alone. |
| One bill version's parsed sections, or the diff rows between two versions | [Bill tree and section diff](sources/congress-bill-tree.md), over already-acquired bill text XML | Keep the dropped-element inventory beside the sections. The diff engine is the pinned DeltaTrack dependency behind the `bill-diff` extra; without it, both modules still import and refuse by naming why. |
| Recorded House and Senate roll-call votes, tallied, with every member's vote | The [vote readers](sources/congress-votes.md), by chamber, Congress, session and roll number | Keep the exact XML and its receipt; identity is proved against the locator, an empty roster refuses, and Senate members resolve to bioguide ids through the legislators crosswalk. The archive floors are the 101st Congress for both publishers. |
| One public law, one statute compilation, or a whole bulkdata zip of either | The [USLM routes](sources/uslm-laws.md) | Keep the exact XML or zip and its receipt. Native identity is proved per file; compilation currency stays as the compiler wrote it. |
| Exact pages of a publisher list query with declared counts checked | The [list routes](sources/listings.md): Congress.gov, GovInfo, GAO feed, LDA, CourtListener, SAM.gov, USAspending, FCC ECFS | Keep every page's bytes; the walk refuses to end early or inconsistently. A count is that day's statement, and zero is not absence. |
| One Unified Agenda edition with every record proved, or its citations and timetables | The [Unified Agenda route](sources/unified-agenda.md) and its projection | Keep the exact XML; acquisition refuses the 2004 editions as malformed, and the projection repairs a retained copy in memory. |
| A U.S. Code title at a release point, an annual archive, the Popular Name Tool or Table III | The [U.S. Code routes](sources/uscode.md) | Keep the exact zip, page or bulk file; identity is proved from each title's own meta, never its file name. |
| A Supreme Court term index and the opinion PDFs it states | The [Supreme Court route](sources/supreme-court.md) | Keep the index render and each PDF; links are byte-exact revision tokens and the index is a live render. |
| A CRS, GAO, regulations.gov or CBO document PDF | The [CRS files](sources/crs-files.md), [GAO files](sources/gao-files.md), [regulations.gov API](sources/regulations-gov-api.md) and [CBO](sources/cbo.md) routes | Keep the exact bytes; every PDF is proved by its magic, its trailer and the final URL, plus each publisher's own completeness witness. |
| Text and observations from retained PDFs or images | The [extraction API](extraction/pdf-extraction-api.md), with an explicit page strategy and backend | Retain source bytes, metadata, body blocks and raw observations separately. Model output is derived evidence; extraction does not publish a source release. |
| GPO print artifacts stripped from extracted bill or report PDF text, before any text-driven parser reads it | [GPO text normalization](extraction-gpo.md), a post-extraction step over `DocumentExtractor` page text | Keep the `GpoCleanupRecord` beside the normalized pages; gated on page-level evidence (a gutter line number), never applied unconditionally. |
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
| [FEC](sources/fec.md) | Explicit API filters, bulk prefixes, sitemaps or selected originals | Metadata and retained responses; linked bodies are acquired separately. Committee, processed-filing, candidate, legal-search and audit profiles can seal one pinned observed query. The bulk profile seals selected original files and ZIP member inventories; the row profile seals selected positional streams. Raw-reader output and other families do not automatically become releases. |
| [GAO](sources/gao.md) | Product IDs | Exact HTML, product identity, and one literal publisher topic per page. Other products and linked report files are outside the capture. |
| [Congressional bills](sources/congress-bills.md) | Explicit bill IDs and text-version package IDs | BILLSTATUS metadata and selected XML text with exact captures and identity checks. This API does not enumerate a collection or publish a release. |
| [Bill sections and section diff](sources/congress-bill-tree.md) | One or two bill text-version XML byte strings | Parsed content-bearing sections with a dropped-element count, or the diff rows between two versions. The diff engine is a pinned dependency behind the `bill-diff` extra. |
| [Appropriations press releases](sources/press-releases.md) | Two fixed, keyless feed URLs (House and Senate) | Exact RSS 2.0 channel and item bytes, every field kept whole; identity checked against the channel `<title>`/`<link>`, not the request URL. |
| Roll-call votes (House and Senate) | *In flight, not yet on `main`* | See the [port status](research/billtrax-port-2026-09-15.md) for progress. |
| [CFR/eCFR](sources/cfr.md) | Explicit route, title and date/edition where supported | Regulation XML and separately requested annual edition metadata, including publisher-stated cover-only status. Exact payloads and native identity/date checks; no collection discovery or release publication. |
| [Public laws and statute compilations](sources/uslm-laws.md) | Congress, kind and law number; compilation file identifier; or one bulkdata zip | Exact USLM XML with native identity checks per file. Archives validate every entry against its own name. No release publication; private-law folders exist for only some Congresses. |
| [Publisher list pages](sources/listings.md) | One explicit list query per publisher: a date or lastModified window, a package's granules, a search, a registration window, a POST body, or the GAO feed | Exact JSON or RSS pages with rows as the publisher spelled them. Declared counts are checked against observed rows where the publisher states one; a bounded walk that cannot reach the terminal page refuses. |
| [Unified Agenda](sources/unified-agenda.md) | One edition file stem | Exact edition XML; every record proves its RIN and edition. |
| [U.S. Code](sources/uscode.md) | Release point and title, an archive year, or a Table III key | Exact OLRC files with native identity; absent acts answer 200 with a truncated page and are refused. |
| [Supreme Court](sources/supreme-court.md) | Term code, then an index-stated PDF link | Exact index and PDF bytes; a wrong-term render is refused. |
| [CRS files](sources/crs-files.md) | The publisher's stated file URL, or id and version | Exact signed PDF; family directories are not always the id prefix. |
| [GAO files](sources/gao-files.md) | Product id and rendition | Exact PDF from the keyless file host; the web host is gated. |
| [regulations.gov API](sources/regulations-gov-api.md) | A filtered document query, a document id, or a stated attachment locator | Exact pages and PDFs; the reachable count is capped at forty pages and the declared count drifts. |
| [SEC rule comments](sources/sec-comments.md) | The rulemaking-activity index, a rule-page URL (its received-comments links), a stated listing URL, a file number (legacy derived listing), or a stated comment-file locator | Exact index, rule-page and listing HTML plus comment files; a listing is identified by its stated URL and docket directory, a comment by its absolute URL. A rule page with no file number or no listing link is kept as an observation; a 404 is never read as absence. |
| [FERC eLibrary](sources/ferc.md) | A docket (with optional subdocket), an accession number, an advanced search, a new-docket date window, or one docket's sheet | Exact eLibrary API responses: docket descriptions, comment/accession rows, file lists, new dockets and docket-sheet documents; every requested-empty answer stays a retryable key with its timestamp, never absence. |
| [CFTC comments](sources/cftc-comments.md) | A release year, one rule's comment list, or a stated comment page | Exact pages and comment-letter PDFs, with direct/proxy recovery for intermittent walls. Files opened from 2026-04-28 onward use the separate Regulations.gov workflow. |
| [USITC EDIS](sources/usitc-edis.md) | An investigation number, phase, known document id, retained bulk ZIP, or the new-document feed | Exact XML metadata and qualified token-authenticated public PDFs. Basket and direct-HTTP bulk jobs matched one selected document's complete attachment set. Direct bulk requests require a web session; package integration, larger batches and recovery remain open. See the source guide for archive validation and mirror ownership. |
| [CBO](sources/cbo.md) | A Congress number, or a feed-stated document link | Exact per-Congress feed; the site's XML feed and documents sit behind a bot wall. The estimate *index* is keyless in the BILLSTATUS bulk zips and the letter *text* is reprinted in the bill's committee report ([routes](research/cbo-cost-estimate-routes-2026-09-20.md)); neither needs this host. |

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

The [Federal Register body API](sources/federal-register-body-sources.md) separately
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
