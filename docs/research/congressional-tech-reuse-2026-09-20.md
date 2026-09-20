# What spicy-docs can reuse from `civictechdc/congressional-tech`

Status: review only; nothing adopted. Written 2026-09-20 against
`civictechdc/congressional-tech` HEAD
[`acc8e59`](https://github.com/civictechdc/congressional-tech/commit/acc8e59313d1165c90af02df292a0eb2b48abe6b)
and spicy-docs `main` at `95aa6e1` (v0.23.0). Every `path:line` below is in the
congressional-tech tree at that sha; re-verify before acting. The one
measurement here is offline over that repository's own committed captures —
script, command and output retained at
`~/Work/corpora/supply-2026-09-02/receipts/congressional-tech-reuse-2026-09-20/`.

**The one-line answer.** One hand-curated CSV is worth taking; everything else
is either a capability spicy-docs already does better, a design note rather than
code, or a downstream product that should stay downstream. There is no wheel to
pin and nothing to vendor.

## 1. What the repository is

A [Turborepo](https://github.com/civictechdc/congressional-tech/blob/main/turbo.json)
monorepo that is mostly a **public catalog and a website**, with a small Python
tool graph attached — a civic-tech project board, not a data library.

| Fact | Value |
| --- | --- |
| Layout | npm workspaces: `apps/{site,committee_youtube,inflation_gsheets}`, `packages/{congress_shared,congress_api,youtube_api,committee_meeting}`, one submodule |
| Size | 153 tracked files; **2,380 lines of Python** across 27 non-empty modules; 29 MB checked out, of which 11 MB is committed capture data |
| Tests | **None.** No `tests/`, no `test_*.py`, no test job in any workflow |
| CI | Three scheduled/push workflows: Pages deploy, monthly CPI refresh, weekly YouTube refresh. No lint, no type check, no test, no publish step |
| Releases | **None** — no tags on `main` (reproducible from the clone); `gh release list` was empty when run on 2026-09-20, output not retained |
| Published artifacts | **Neither PyPI nor npm.** Every package is `version = "0.1.0"` and resolves its siblings through `[tool.uv.sources]` path entries (e.g. [`congress_api/pyproject.toml:28-30`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/pyproject.toml#L28-L30)) |
| License | Apache-2.0 at the root, but the file still carries the template's unfilled `Copyright [yyyy] [name of copyright owner]`, **no `pyproject.toml` declares a `license`**, and [`apps/committee_youtube/README.md:90`](https://github.com/civictechdc/congressional-tech/blob/main/apps/committee_youtube/README.md#L90) says "MIT or public domain depending on underlying sources" |
| Activity | 254 commits. Humans: Alex Gurvich 179 (mostly 2025-08/09), Mike Deeb 33 (2026-07), Evan Tung 10 (2025-08 → 2026-02). **Last human commit 2026-07-25**; every commit since is `github-actions[bot]` refreshing YouTube and CPI data |
| Open work | 23 open issues and 0 open PRs as `gh` reported on 2026-09-20 (output not retained), 1 stale unmerged branch (`78-implement-library-for-data-warehouse`) |

**Sibling dependency.** The only declared dependency on another org repository is
the submodule
[`submodules/congress_meeting_map` → `civictechdc/congress_meeting_map`](https://github.com/civictechdc/congress_meeting_map).
Despite the name it is **not** congressional committee-meeting data: it is a
TypeScript/Vite knowledge-graph explorer over the transcript, audio and
whiteboard photos of one Civic Tech DC working session, with Gemini/OpenAI
extraction prompts and JSON-LD outputs. Unlicensed (no `LICENSE` file), last
pushed 2025-09-20. Nothing in it is reusable here, and nothing in
congressional-tech's Python graph imports it.

`DeltaTrack` and `BillTrax` are linked from the README as sister projects but are
separate repositories, not dependencies of this one. DeltaTrack stays what it
already is here: [a pinned dependency, never a port](../decisions.md#deltatrack-is-a-pinned-dependency-not-a-port).

### What the Python graph actually does

Two halves, only one of which runs.

- **`youtube_api`** — fetches every upload on a committee's YouTube channel
  through `googleapiclient`, stores it in a per-committee TinyDB JSON file, then
  counts how many video titles/descriptions carry the Congress.gov **Event ID**
  that links the recording back to the official proceeding. This half runs
  weekly in CI and produces the live dashboard.
- **`congress_api`** — a thin `requests` client for the Congress.gov API
  (`committee/{chamber}`, `committee-meeting/{congress}/{chamber}`) with a
  page-aggregating helper and TinyDB persistence. **This half has never produced
  committed output**: `apps/committee_youtube/data/` holds only
  `youtube_*.json` and the report CSV — no `events.json`, no
  `committee-summaries.json` — and no workflow invokes `congress-fetch`. The
  detail fetcher `CongressEventFetcher.process_events`
  ([`congress_event_fetcher.py:53`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/fetch/congress_event_fetcher.py#L53))
  is never called by the CLI path, which stops at `fetch_event_list`
  ([`fetch/main.py:32-34`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/fetch/main.py#L32-L34)).

`packages/committee_meeting` is a README describing an ER model with a
`print("Hello from committee-meeting!")` behind it
([`main.py:1-6`](https://github.com/civictechdc/congressional-tech/blob/main/packages/committee_meeting/src/committee_meeting/main.py#L1-L6)).
The implementation is stranded on branch `78-…` and, by the owner's own review
([`docs/data-warehouse-design.md:39-52`](https://github.com/civictechdc/congressional-tech/blob/main/docs/data-warehouse-design.md#L39-L52)),
does not import: a `back_populates` name mismatch raises at SQLAlchemy mapper
configuration, so the code was never executed.

## 2. The measurement

The dashboard's headline number — how many committee videos are missing their
Event ID — rests on one regex,
[`youtube_api/analyze/main.py:27`](https://github.com/civictechdc/congressional-tech/blob/main/packages/youtube_api/src/youtube_api/analyze/main.py#L27):

```python
EVENT_ID_REGEX = ".*(\\d{6}|eventid).*"
```

Applied case-insensitively to each video's title and description. Run over the
repository's own 21,755 committed video rows and compared against a strict
`EventID=<digits>` reading of the same bytes:

| Reading | Videos counted as carrying an Event ID |
| --- | --- |
| The repository's rule (`\d{6}` **or** the literal `eventid`) | 5,229 |
| Strict `EventID=<digits>` | 3,980 |
| Loose-only | **1,249 — 23.9 % of the loose hits** |
| Strict-only | 0 (so the loose rule's recall is not the problem) |

The false positives are appropriations hearing descriptions where some unrelated
six-digit run appears; the rule cannot tell an event id from a docket number, a
phone number or a date. Counted the other way, 25 videos spell the marker
`EvenID=` and similar, which a naive strict rule would drop, and the observed id
lengths are 4 (76), 5 (4) and 6 (3,900) digits — so `\d{6}` is not the id's
shape either.

The published report is also narrower than it looks: it carries **12 of the 18
committees** the crosswalk names, and **exactly one handle per committee** — for
all six two-handle committees it is the *secondary* handle that survives
(`@HouseAgDems`, not `@AgRepublicans`). The cause is
[`analyze/main.py:130`](https://github.com/civictechdc/congressional-tech/blob/main/packages/youtube_api/src/youtube_api/analyze/main.py#L130):
`final_reports.extend(reports)` sits outside the `for handle in handles` loop, so
each committee contributes only its last handle's rows.

Inputs, commands, outputs and what the measurement could not see:
`~/Work/corpora/supply-2026-09-02/receipts/congressional-tech-reuse-2026-09-20/`.

**Why this matters for reuse.** It settles the direction of every "should we
port the linkage logic?" question below: the *idea* (a committee's own recording
belongs to a Congress.gov `event_id`) is valuable and matches an open gap; the
*implementation* is a one-line heuristic with a measured 76 % precision, no
test, and a reporting bug that silently drops half the handles. Take the demand,
not the code.

## 3. Ranked reuse table

| # | Piece | Where it lives | What it fills or replaces here | Evidence | How to pull it in | Request upstream |
| --- | --- | --- | --- | --- | --- | --- |
| **1** | **Committee → YouTube handle crosswalk**: 18 House standing committees as `committee, systemCode, handle, secondary` | [`congress_shared/…/youtube/youtube-accounts.csv`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv) (19 lines) | **A capability spicy-docs lacks entirely.** No publisher states which YouTube channel belongs to which committee; `committee_meetings.videos_json` (`schemas/congress_index_tables.py:155`) only keeps the video links the Congress.gov *detail* happens to state. Its key is `systemCode`, already the identity of the `committees` contract, so it joins with no new identity | Hand-curated, unversioned, **untested and partly unverified**: 17 of 18 codes match the `hs<2-3 letters><2 digits>` shape our own committee fixtures carry; `hsed00a` (Education & Workforce) has a trailing `a` that appears nowhere in `tests/` here. Six committees declare a minority handle; the reader's `[secondary] * (secondary != " ")` at [`tables.py:32`](https://github.com/civictechdc/congressional-tech/blob/main/packages/youtube_api/src/youtube_api/tables.py#L32) compares against a *space*, so an empty cell yields an empty handle that two downstream sites then skip by hand | **Copy the data, not the code** — 18 rows of facts, reformatted as a spicy-docs reference table with a captured-on date and the `system_code` spelling our `committees` contract uses, each row provable against the `committee` route. Attribution to congressional-tech in the module docstring. A git or wheel pin for 19 lines of CSV would be ceremony | Ask that the CSV gain the Senate rows and a `verified_on` column, and that `hsed00a` be checked against the `committee` route. If it grows, ask for it to become a standalone data package with a real version |
| **2** | **The Event-ID linkage demand** (recording ↔ `event_id`), plus proposals I.1 "Unified Congressional Hearing & Markup Data Platform" and III.5 "Witness Database" | [`apps/site/src/content/proposals/I.1.md`](https://github.com/civictechdc/congressional-tech/blob/main/apps/site/src/content/proposals/I.1.md), [`III.5.md`](https://github.com/civictechdc/congressional-tech/blob/main/apps/site/src/content/proposals/III.5.md) | **Names a consumer for open register rows** A7 (meetings/hearings chain unhosted) and D4, and for the `docs.house.gov` row the data map still marks `candidate` ([legislative data map](legislative-data-map-2026-09-18.md), the `proceedings` row). I.1's field list is exactly `committee_meetings` plus a video link and a docs.house.gov link; III.5 asks for witness *names*, which we count (`witness_count`) but do not keep | Requirements written by Hill staff, not code. The register's A7 landed the contract with no named consumer; this is one | **Not a code pull — a prose citation.** Cite I.1 as the demand in the A7 follow-up and in whatever picks up `docs.house.gov` | Nothing. These are already public |
| **3** | **Congress calendar reference**: 106th–119th with start/end dates, per-session date ranges and party control per chamber | [`congress_shared/…/data/congress_metadata.json`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_shared/src/congress_shared/data/congress_metadata.json) (14 entries) | **Partly a capability we lack**: nothing here maps a Congress number to its dates. But the dates and sessions are exactly what the Congress.gov **`/congress`** route serves, and `LIST_ROUTES` (`sources/congress/listing.py:220`) has no `congress` entry — so the gap is a missing route, not a missing file. Only **party control** is genuinely absent from every publisher route | The file has no provenance line, no capture date, no source URL and no licence note; it is committed twice, byte-identical, at `congress_shared/data/` and `apps/site/src/data/` | **Do not take the file.** Add a `congress` entry to `LIST_ROUTES` and let the publisher state dates and sessions, the way every other route works. Take only the party-control column, and only if a consumer asks, as a small reference table with its own cited source (not this file) | Ask for the file's source and capture date to be recorded, and for the duplicate copy under `apps/site/src/data/` to be dropped in favour of one |
| **4** | **`docs/data-warehouse-design.md`** — the Parquet + DuckDB-WASM direction and the "a schema lands with a caller, or it doesn't land" rule | [`docs/data-warehouse-design.md`](https://github.com/civictechdc/congressional-tech/blob/main/docs/data-warehouse-design.md) | Reinforces what spicy-regs already does (Parquet, DuckDB, Hive-style partitions) and what our own [ownership doc](../source-ownership.md) already says about consolidating behind a wheel. Its §2.8 diagnosis — abstraction built with no consumer to falsify it — is the same reasoning the register applies to A7 | A design note by this repository's own owner; it explicitly says "Nothing here is decided" | **Nothing to pull.** Cite it if the two datasets are ever reconciled | Nothing |

### Nothing here warrants a wheel, a git pin or a vendored artifact

The DeltaTrack pattern in `pyproject.toml:59-67` —
a full-sha git pin behind an extra, with the reason beside the pin — exists
because DeltaTrack is a real engine with measured behavior that we do not want
to copy. Nothing in congressional-tech meets that bar: the largest reusable unit
is 19 lines of CSV, and the code around it is untested, unversioned, unreleased
and unpublished. **Pin nothing. Copy 18 rows of facts with attribution.**

## 4. Not worth pulling, and why

| Piece | Why not |
| --- | --- |
| `congress_api` — the Congress.gov client ([`api.py`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/api.py), 78 lines) | Strictly worse than what we run. It accumulates **every page of a paginated route into one in-memory dict** before returning ([`api.py:48-61`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/api.py#L48-L61)) — O(total rows) memory for a route with 92,450 rows — where `reading/paged_json.py` streams with reach bounds. It has no retry, no budget, no evidence capture, no resume, and no credential scrubbing. `generic_request`'s XML fallback raises `AttributeError` inside its own error path (`e.message` on a plain exception, [`api.py:77`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/api.py#L77)) |
| `congress_api` credential handling | [`congress_event_fetcher.py:101`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/fetch/congress_event_fetcher.py#L101) prints `f"…try: {url}&api_key={self.api_key}"` on an unexpected error, and [`update-youtube.yml:43`](https://github.com/civictechdc/congressional-tech/blob/main/.github/workflows/update-youtube.yml#L43) passes the YouTube key as a command-line argument. Both violate [keep credentials out of evidence](../../AGENTS.md); `transport/credentials.py` is the answer we already have |
| `congress_api` resume behavior | On HTTP 429 it **stops the whole run** ([`:85-89`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/fetch/congress_event_fetcher.py#L85-L89)) and on an unexpected exception it prints and advances past the row ([`:100-103`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/fetch/congress_event_fetcher.py#L100-L103)) — the opposite of rule 2 in [write recoverable fetchers](../../AGENTS.md). `crs_summaries.py` is the pattern that already does this correctly |
| `CommitteeSummary` / `CommitteeDetails` dataclasses | A module-global mutable registry (`INDEX`, [`committee_summary.py:10,247`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/analyze/committee_summary.py#L247)) whose `upsert_from_dict` at `:230` calls `from_dict(data, index=self)` against a signature that takes no `index` — an unreachable `TypeError`. `CommitteeDetails.from_system_code` hardcodes `"house"` ([`committee_details.py:136-138`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/analyze/committee_details.py#L136-L138)). `analyze/main.py:22` tests `isinstance(committee, dict)` where `committees` was meant — a `NameError` on the first dict-valued payload. Our `schemas/roster_tables.py` and `sources/congress/committee_rosters.py` cover the same ground with tests and a measured API-vs-file comparison |
| `xml_to_dict.py` / `json_to_tinydb.py` | A 27-line recursive XML-to-dict that discards attributes, namespaces, mixed content and byte offsets. [Mapped markup](../markup-reading.md) exists precisely to keep those |
| TinyDB as the store | A JSON document store re-read and re-written per row; `youtube_06.json` is already 3.1 MB. Our releases are immutable, verifiable and evidence-linked; this is not a step toward them |
| `packages/committee_meeting` and branch `78-…` | A schema with no implementation on `main` and a non-importing implementation on a stale branch, whose entities (Committee, CommitteeMeeting, Recording, Transcript) are already covered by `committees`, `committee_meetings` and `hearing_transcripts` — with `congress` and provenance columns that the branch's model [lacks by the owner's own review](https://github.com/civictechdc/congressional-tech/blob/main/docs/data-warehouse-design.md#L54-L68) |
| `apps/inflation_gsheets` (BLS CPI, FRED, Adobe, PriceStats) | Out of scope: economic indicators, not federal legislative or regulatory source records. The adapter shape ([`sources/base.py`](https://github.com/civictechdc/congressional-tech/blob/main/apps/inflation_gsheets/src/sources/base.py)) is clean, but it is a thinner `SourceNativeProfile` with a pandas return type, and it has no tests. Pulling it would add a pandas dependency to buy a pattern we already have |
| `apps/site` (Astro) and the dashboard React island | Downstream presentation. [Ownership](../source-ownership.md) puts interpretation and display outside SpicyDocs, and the dashboard is a product of spicy-regs-style tables anyway |
| `youtube_api` fetch/analyze code | See §2. The channel-walk pagination is ordinary `googleapiclient` paging with an "already seen, stop" break ([`youtube_event_fetcher.py:227-243`](https://github.com/civictechdc/congressional-tech/blob/main/packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py#L227-L243)) that is correct only while the channel is strictly append-only; class-level mutable state at `:27-29` is shared across instances. If spicy-docs ever acquires committee video metadata it should be a normal source adapter over the YouTube Data API, reusing `transport/` and the release format |
| The submodule `congress_meeting_map` | Not congressional meeting data (see §1); unlicensed |
| The devcontainer, `turbo.json`, the three workflows | Repository plumbing for a different stack. `turbo.json` declares no tasks at all |

## 5. Overlaps where this repository's version stays

| Capability | congressional-tech | spicy-docs | Verdict |
| --- | --- | --- | --- |
| Congress.gov list routes | Two hardcoded endpoints, one page-aggregating helper | `LIST_ROUTES`: ~30 routes stated as data, with per-route sort/date-window/param validation, reach bounds and a route-table test | **spicy-docs.** Breadth 30 vs 2, and the parameter rules are checked rather than assumed |
| Committee rosters | `committee/{chamber}` list + per-committee detail into TinyDB | `sources/congress/committee_rosters.py` + `schemas/roster_tables.py`, with the API-vs-chamber-file comparison measured (API 555 vs files 541 for the 119th, all 14 API-only with ended terms) | **spicy-docs.** Ours has a measured coverage floor; theirs has none |
| Committee meetings / hearings | `committee-meeting/{congress}/{chamber}` list only; the detail fetcher is never invoked and has produced no committed output | `committee_meetings` keyed `(congress, chamber, event_id)` over 27 columns, with `hearing_jacket`, `bill_ids_json`, `document_urls_json`, `videos_json`, and edges re-run both ways on the captured pair (jacket 64431 ↔ event 119003) | **spicy-docs**, decisively |
| Credential handling | Three-way arg/env/home-file loader with no scrubbing; keys reach stdout and the CI command line | `transport/credentials.py`: `read_api_key` + two-pass `scrub_credential`, scrub-before-truncate, mutation-checked tests | **spicy-docs** |
| Persistence | TinyDB JSON files, mutated in place, committed to the repository (11 MB, previously via git LFS) | Immutable releases with evidence, digests, replay and full verification | **spicy-docs** |
| Bill / PDF / report parsing | None | DeltaTrack (pinned), `reconstruction/`, `extraction/`, `agency_reports/` | **spicy-docs**, and DeltaTrack stays upstream |
| Congress → dates and sessions | A committed JSON file with no provenance | Nothing — but the publisher route exists and is unbuilt | **Neither yet.** See §3 row 3: build the route, do not copy the file |
| Committee → YouTube channel | The CSV | Nothing | **congressional-tech**, and it is the only row in this table that goes that way |

## 6. Recommended order of adoption

Ordered by value per unit of work. Rows 3 and 4 are conditional on a consumer
asking; nothing here is a commitment until it has a `docs/decisions.md` record.

1. **Take the committee → YouTube handle crosswalk as reference data** (§3 row 1).
   Eighteen rows, no dependency, fills a real blank.
2. **Cite proposal I.1 as the named consumer** for the A7 meetings/hearings chain
   and for the `docs.house.gov` candidate row (§3 row 2). Free; it converts an
   unconsumed contract into one with a stated demand.
3. **Add a `congress` route to `LIST_ROUTES`** so Congress dates and session
   boundaries come from the publisher rather than a copied file (§3 row 3). Only
   worth doing when something needs the dates; the party-control column is a
   separate, later question with its own sourcing problem (no route this note
   read states it, and none was probed for it, so its absence is unverified).
4. **Report the two defects upstream** (§2). They are the owner's repositories,
   the dashboard is live, and both findings are one-line fixes with a measurement
   attached — this is the [retain value](../decisions.md) reciprocal of taking
   their CSV.

Everything else in §4 is a decline, not a deferral: re-open only if
congressional-tech publishes a tested, versioned package.

### The first three concrete steps

1. **Land the crosswalk.** Add `src/spicy_docs/sources/congress/committee_channels.py`
   holding the 18 rows as a frozen table with a `captured_on` date, the
   `system_code` spelling `schemas/roster_tables.py` uses, an attribution line
   naming congressional-tech at sha `acc8e59` and its Apache-2.0 licence, and a
   docstring stating what the table is *not* (House only; no publisher states it;
   `hsed00a` unverified). Add a test that every `system_code` in it parses under
   the committee-code rule and that no handle is empty — the two defects
   [`tables.py:32`](https://github.com/civictechdc/congressional-tech/blob/main/packages/youtube_api/src/youtube_api/tables.py#L32)
   routes around. Update `docs/architecture.md` and `docs/README.md`.
2. **Verify `hsed00a` with one keyed request** against
   `LIST_ROUTES["committee-detail"]` for the House, and record the answer beside
   the table — the code either resolves or it is a typo for `hsed00`, and a
   crosswalk whose key does not join is worse than no crosswalk. Retain the
   receipt under `supply-2026-09-02/receipts/`.
3. **File the two upstream issues** on `civictechdc/congressional-tech`, each
   with the measurement from §2: (a) `EVENT_ID_REGEX` counts any six-digit run —
   1,249 of 5,229 hits (23.9 %) carry no event id, and 25 videos spell the marker
   `EvenID=`; (b) `analyze/main.py:130` drops every committee's non-final handle,
   so the published report covers 12 of 18 committees with one handle each.
   Suggest the minimal fix for (b) — move the `extend` inside the loop — and for
   (a) the marker rule `EventID\s*=\s*(\d+)` with the near-miss spellings listed.
   Record the issue numbers here when filed.

## 7. Sources

- Repository: <https://github.com/civictechdc/congressional-tech> at
  [`acc8e59`](https://github.com/civictechdc/congressional-tech/commit/acc8e59313d1165c90af02df292a0eb2b48abe6b)
- [`packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv)
- [`packages/congress_shared/src/congress_shared/data/congress_metadata.json`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_shared/src/congress_shared/data/congress_metadata.json)
- [`packages/youtube_api/src/youtube_api/analyze/main.py`](https://github.com/civictechdc/congressional-tech/blob/main/packages/youtube_api/src/youtube_api/analyze/main.py)
- [`packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py`](https://github.com/civictechdc/congressional-tech/blob/main/packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py)
- [`packages/youtube_api/src/youtube_api/tables.py`](https://github.com/civictechdc/congressional-tech/blob/main/packages/youtube_api/src/youtube_api/tables.py)
- [`packages/congress_api/src/congress_api/api.py`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/api.py)
- [`packages/congress_api/src/congress_api/fetch/congress_event_fetcher.py`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/fetch/congress_event_fetcher.py)
- [`packages/congress_api/src/congress_api/analyze/committee_summary.py`](https://github.com/civictechdc/congressional-tech/blob/main/packages/congress_api/src/congress_api/analyze/committee_summary.py)
- [`packages/committee_meeting/README.md`](https://github.com/civictechdc/congressional-tech/blob/main/packages/committee_meeting/README.md)
  and branch [`78-implement-library-for-data-warehouse`](https://github.com/civictechdc/congressional-tech/tree/78-implement-library-for-data-warehouse)
- [`docs/data-warehouse-design.md`](https://github.com/civictechdc/congressional-tech/blob/main/docs/data-warehouse-design.md)
- [`apps/site/src/content/proposals/`](https://github.com/civictechdc/congressional-tech/tree/main/apps/site/src/content/proposals)
- [`.github/workflows/update-youtube.yml`](https://github.com/civictechdc/congressional-tech/blob/main/.github/workflows/update-youtube.yml)
- Submodule: <https://github.com/civictechdc/congress_meeting_map>
- Measurement receipt (outside this repository):
  `~/Work/corpora/supply-2026-09-02/receipts/congressional-tech-reuse-2026-09-20/`
