# Documentation

Start with the [offline example](../README.md#start-here) and
[contribution guide](../CONTRIBUTING.md). These guides describe the current
implementation; the [release specification](superpowers/specs/2026-08-25-source-native-release-spec.md)
states the adopted format and publication requirements.

| What you need to do | Read |
| --- | --- |
| Install only the reader, acquisition tools, or Parquet tools you need | [Installation choices](installation.md) |
| Choose raw records, a verified source release, or a flat table | [Source workflows and useful stopping points](source-workflows.md) |
| Find the code that owns a change | [Architecture and ownership](architecture.md) |
| Review planned simplification, component ownership, and DocSpec wheel reuse | [Simplification to-do list](simplification-todo.md) |
| Understand which source capabilities to keep, share, or retire | [Source ownership decisions](source-ownership.md) |
| Publish or verify a release or public table | [Operator commands](cli.md) |
| Inspect collection counts, scope, and rejected records | [Collection outcomes](source-native-outcomes.md) |
| Add a profile or change shared publication | [Release lifecycle and extension](releases.md) |
| Understand Federal Register scope, identity, and evidence | [Federal Register](sources/federal-register.md) and [body sources](federal-register-body-sources.md) |
| Change Mirrulations collection rules | [Regulations.gov](sources/regulations-gov.md) |
| Change exact GAO page capture | [GAO product pages](sources/gao.md) |
| Capture community comment partitions | [Public comments](sources/public-comments.md) |
| Use a raw Mirrulations or CourtListener reader | [Raw readers and projections](sources/raw-readers.md) |
| Find source-field references or investigate documented-value drift | [Source references](source-reference.md) and [documented-value drift](source-domain-drift.md) |
| Run a campaign, replay retained evidence, or inspect corpus receipts | [Operational modules](cli.md#campaigns-replay-and-source-tools) and [corpus diagnostics](../tools/README.md) |
| Understand why an unusual rule exists | [Acquisition decisions](decisions.md) and [maintenance decisions](maintenance-decisions.md) |
| Update these guides or recover the former wiki | [Documentation maintenance and provenance](documentation.md) |

Keep source observations, run measurements, and large captures with their corpus
receipts. Commit only bounded fixtures and the guidance needed to reproduce or
review the work.
