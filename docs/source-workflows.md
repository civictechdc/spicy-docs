# Choose a source workflow

Choose the output first. SpicyDocs acquires source records and preserves their
provenance; the caller chooses the source and scope.

## Choose the output you need

| You need | Use | Keep and check |
| --- | --- | --- |
| Records with exact acquisition evidence and offline replay | `publish` a supported source for explicit dates, agencies, or product IDs | Keep the release, blob store, and artifact pin. `inspect` checks admission and reports outcomes; `verify` reconstructs records and failures. |
| Flat Parquet rows from a release | `publish-public-table` for Federal Register or Mirrulations | Keep the table pin and input release. Publication checks every row; `verify-public-table` checks admission. The library verifier also checks rows. |
| Parsed dictionaries in an application that owns recovery | A Mirrulations, CourtListener or FEC raw reader | The caller retains input pins, failures, checkpoints, and completion evidence. A raw read has no release verification. |
| An immutable release of a retained OpenFEC committee census | The [FEC committee profile](sources/fec.md#publish-a-retained-committee-census) and existing publisher | Pin every capture, replay exact JSON, check page/count/ID membership, and retain observed-crawl scope. Other FEC families remain raw-reader inputs. |

Use the [CLI commands](cli.md), [raw-reader APIs](sources/raw-readers.md), or
[offline GAO example](../examples/offline_release.py). The example requires no
network or credentials and leaves inspectable output.

## Know what each source supplies

| Source | Input | Captured result and coverage limit |
| --- | --- | --- |
| [Federal Register](sources/federal-register.md) | Inclusive publication dates | Exact API responses, metadata, and body links. Two consecutive crawls agree within the requested dates; no frozen publisher-wide version is established. |
| [Mirrulations](sources/regulations-gov.md) | Agencies, collection, dates | Exact JSON objects and selected documents, dockets, or comments. Date selection follows live listing acquisition; objects are pinned individually. |
| [Community comments](sources/public-comments.md) | Agencies | Exact Parquet parts and rows. Discovery stops at the first missing numbered part; later parts are unrequested. |
| [FEC](sources/fec.md) | Explicit API filters, bulk prefixes, sitemaps or selected originals | Metadata and retained responses; linked bodies are acquired separately. The committee census profile can seal one pinned observed traversal. Raw-reader output and other families do not automatically become releases. |
| [GAO](sources/gao.md) | Product IDs | Exact HTML, product identity, and one literal publisher topic per page. Other products and linked report files are outside the capture. |

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
acquires an explicitly selected GovInfo granule, checks identity, and returns
exact bytes. Publisher XML/text routes currently provide locators only.

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
