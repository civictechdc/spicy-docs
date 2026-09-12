# Choose a source workflow

SpicyDocs helps you obtain source records, keep their provenance, and check the
result later. You choose the source and requested scope. A successful source
release retains the evidence used to accept that collection, its selected
records, and an outcome describing coverage and record rejections.

Retained evidence covers the responses or objects used by acquisition and
selected refused bodies. Retry responses and unretained discovery probes are
not part of that evidence.

## Choose the output you need

| What goes in? | What happens? | What comes out? | How do you check it? |
| --- | --- | --- | --- |
| A supported source and exact dates, agencies, or product IDs | `publish` acquires evidence, applies the source's identity and selection rules, and verifies the staged result | An immutable source release, separate evidence blobs, source records, any rendition links, and a collection outcome | Preserve the release pin and blob store. `inspect` checks admission and reports the outcome; `verify` reconstructs records and failures from retained evidence. |
| An admitted Federal Register or Mirrulations source release | `publish-public-table` preserves selected fields in a flat layout and checks every output row | Immutable Parquet files and a pin to the input release | The table reader checks admitted members. Keep the input release for original evidence. `verify-public-table` performs admission; the library's full table verifier also checks rows. |
| A Mirrulations object listing or CourtListener bulk dump | A raw reader streams parsed source records | Dictionaries and reader-specific counters for a caller-managed run | The caller retains input pins, failures, checkpoints and completion evidence. A raw read alone is not a verified source release. |

These are working paths. The [CLI guide](cli.md) gives commands, and the
[raw-reader guide](sources/raw-readers.md) gives the lower-level interfaces.
The [offline GAO example](../examples/offline_release.py) needs no network or
credentials and leaves its output available for inspection.

## Know what each source supplies

| Source | Requested input and retained evidence | Useful result and coverage limit |
| --- | --- | --- |
| [Federal Register](sources/federal-register.md) | Inclusive publication dates; exact API responses, including capped-window probes | Publisher metadata and body/rendition links. Two consecutive crawls must agree; they do not establish a frozen publisher-wide version. |
| [Regulations.gov through Mirrulations](sources/regulations-gov.md) | Named agencies, collection and dates; exact listed JSON objects in bounded ZIP packs | Documents, dockets or comments selected under that collection's rules. Dates are applied after the live agency listing is acquired; each object is pinned separately. |
| [Community public comments](sources/public-comments.md) | Named agencies; exact Parquet parts and capture metadata | Faithful table rows. Discovery assumes contiguous part names and stops at the first missing part; later parts are unrequested. |
| [GAO product pages](sources/gao.md) | Explicit product IDs; exact HTML and capture metadata | Product identity and one literal publisher topic. This captures those pages, not the GAO catalog or linked report files. |

Prefer the community's SpicyRegs tables when they supply the required data.
Use origin acquisition for coverage they cannot supply. This is the
[supply decision](decisions.md#community-supply-precedes-origin-acquisition),
not an automatic fallback: the command requires you to choose a source.
SpicyRegs maintains its own public-data pipeline; this package's public-table
export is a separate, optional output from a verified source release.

## Read the result before using it

An accepted release can contain records, rejected record observations, or no
record observations. Read `collectionOutcome` for exact selectors, discovery
rules, assumptions and counts. Read the failure sample when records were
rejected. Empty accepted input says what was observed; it does not prove that
the source contains no matching material or that an unrequested collection is
empty. [Collection outcomes](source-native-outcomes.md) explains the fields.

An acquisition refusal leaves the requested collection unresolved and publishes
no valid-looking partial release. Bounded refused responses may still have
diagnostic blob references in `failedAcquisition`; transport failures, byte
limits or credential suppression can prevent retaining the body. The report
states that limitation. [Failed-run evidence](cli.md#output-and-failures)
explains how to inspect those references.

Verification checks that the retained bytes, source rules, and published
records agree. Hashes and an accepted verifier identity do not independently
authenticate the publisher. Admission uses bounded memory but reads payloads
to check their hashes; full replay also repeats source interpretation.

## Stop at a useful boundary

After publication, you can inspect coverage, stream source records, or retain
the release for later use without starting a dataset experiment. If flat rows
are sufficient, export a supported public table. If your application already
owns persistence and recovery, a raw reader may be sufficient.

Rendition rows describe document candidates: a locator and whatever metadata
the source supplied. They do not mean that a PDF, attachment or body was fetched
or that its content was hashed. GAO's HTML is acquisition evidence; its profile
does not enumerate or fetch linked report files. Federal Register's
[body-source API](federal-register-body-sources.md) separately acquires an
explicitly selected GovInfo granule or MODS-resolved granule, checks its printed
identity and returns exact bytes. It also derives publisher XML/text locators;
those routes do not yet have a qualified acquisition implementation. You can
retain the GovInfo capture directly without a dataset application. DocSpec's
candidate selection and fetcher adapter remain separate work.

For a dataset assembled from sources, chosen document fetchers, processors and
successive runs, use DocSpec. If you also have the optional neighboring DocSpec
checkout, its local guides are the
[offline walkthrough](../../DocSpec/docs/offline-walkthrough.md) and
[current capabilities](../../DocSpec/README.md#what-you-can-use-today). Its
[GAO topic example plan](../../DocSpec/docs/dataset-experiments-todo.md#d51)
owns catalog filtering and processing. These links require that sibling checkout;
SpicyDocs setup and source examples do not. A GAO topic is a publisher label; it does
not establish a legal requirement, applicability, classification, or a match
to a separate taxonomy.

A schema or [source reference](source-reference.md) describes fields and supported shapes. It does
not establish that a live fetcher exists, has run, or currently works. Use the
working paths listed above and their source guides; planned integrations remain
in the [to-do list](simplification-todo.md). Offline fixtures test behavior under
their retained inputs and do not prove live-source availability or coverage.
