# Community legislators crosswalk

Capture the two `unitedstates/congress-legislators` JSON files that name
every bioguide, Senate LIS and FEC candidate id a member of Congress has ever
carried, plus their terms. Both routes are keyless, and this is the only
route in this package to a *former* senator's LIS id: Congress.gov and the
Senate's own XML both key votes and member pages on the seat's current
occupant, so once a senator leaves office no publisher file states it any
more.

## What the files are

`unitedstates/congress-legislators` is a civil-society project maintained on
GitHub, not a government publisher. It ships two files relevant here:

| File | What it holds |
| --- | --- |
| `legislators-current.json` | Everyone serving in Congress today. |
| `legislators-historical.json` | Everyone who has ever served and left. |

Both are one JSON array of records with the same shape: `id` (a bag of
cross-reference ids), `name`, `bio`, and `terms` (one entry per election won,
carrying `type`, `start`, `end`, `state`, `party`, `district` and other
fields this module does not read) — see the shape-rule table below for how
`party` and `district` are kept. There is no third "everyone, ever" file, and
no field in either file states when the file itself was generated.

## Routes, bounds and their measured basis

| Route | Answered 2026-09-19 | Credential |
| --- | --- | --- |
| `https://unitedstates.github.io/congress-legislators/legislators-current.json` | `200`, `application/json`, 1,468,926 bytes, 539 records | none |
| `https://unitedstates.github.io/congress-legislators/legislators-historical.json` | `200`, `application/json`, 13,483,039 bytes, 12,231 records | none |

Both are plain GitHub Pages: one `GET`, no pagination, no redirect observed.
`docs/research/legislative-data-map-2026-09-18.md`, Table D, measured the
historical file the day before at the identical byte count and record count;
re-measuring it here on 2026-09-19 reproduced both exactly, so the file had
not changed in that window. That table also measured 228 historical and 100
current records carrying `id.lis`, and 995 historical and 537 current
records carrying `id.fec` — this module's tests assert at least those counts
against the live routes.

`LegislatorsBudget.max_bytes` bounds the current route (default 4 MiB, capped
at 8 MiB — roughly 2.8x and 5.6x the measured size). `max_historical_bytes`
bounds the historical route at a hard **16 MiB** ceiling, matched to the
measured 12.86 MiB file with headroom for the file's slow, append-heavy
growth rather than open-ended trust in its future size. `parse_legislators`
enforces the same 16 MiB ceiling directly, so it refuses an oversized body
even called outside the acquirer.

## Shape rules, and why each exists

`parse_legislators(body, *, max_bytes, max_records)` proves shape before
returning anything; a violation refuses the **whole file**, naming the
offending record's position (`community legislators record 3862 ...`) so the
day a publisher record breaks a rule, it is visible rather than silently
dropped or half-parsed.

| Rule | Why |
| --- | --- |
| The file is a JSON list. | The publisher's whole contract is "an array of legislators"; anything else is not this file. |
| JSON numbers decode as integers only, never floats. | Every number in this file (`govtrack`, `icpsr`, ...) is an integer id; a float would be a different, unexpected shape, not a normal id. |
| Every record has a non-empty `id.bioguide`. | This is the join key every other Congress.gov/GovInfo route already uses; a record with no bioguide cannot be crosswalked to anything. |
| `id.lis`, when present, matches `S\d{3}`. | The Senate LIS id is exactly what this source exists to carry; any other shape is not an LIS id. |
| `id.fec`, when present, is a list of strings, each matching a real FEC candidate id shape. | Garbage in this field would silently poison FEC lookups keyed on it. |
| `terms` is a non-empty list; each entry's `type` is `rep` or `sen`, `start` is a real ISO calendar date, and `end` is a real ISO calendar date **when present**. | A person with no terms is not a legislator record this crosswalk can place in time. The regex proves a date is spelled `####-##-##`; `datetime.date.fromisoformat` proves it is a real date (`2026-13-45` matches the regex but is not a month). `end` is optional because the publisher omits it elsewhere in these files for an in-progress item; refusing the whole file over that shape would be wrong even though no term lacks it today (measured 2026-09-19). |
| A bioguide, LIS or FEC id names **at most one** record in the file. | These are the join keys this crosswalk exists to supply; a duplicate would make a lookup ambiguous, which is worse than refusing the file. |

**`Term.party` is the publisher's one value per term, not a history.** It
cannot represent a mid-term party change — Strom Thurmond's 1964 switch, for
example, collapses to whichever party the row states — and this crosswalk's
job is ids, not party history; a future revision wanting that history reads
`party_affiliations` from the raw record, which stays unread here.
**`Term.district`** is the publisher's `terms[].district` (absent on a `sen`
term), kept as the spelled decimal string rather than parsed to `int` — an
at-large `"0"` included — because a table column keys and joins on it and
does neither better as a number.

**FEC ids come in two real shapes, discovered against the live data, not
assumed.** A House or Senate candidate id embeds the office letter, a decade
digit and the member's state postal abbreviation — `S8WA00194` (Maria
Cantwell). A presidential candidate id carries no state, because a
presidential run is not tied to one, so the FEC assigns `P` plus eight
digits instead — `P80003023`. `parse_legislators` accepts either shape
(`_fec_id_shape_ok`). Restricting the check to the congressional shape alone
would refuse every record of anyone who ever filed for President — including
Mark Warner (`W000805`), a **sitting** senator in the current 539-record
file, and eight more scattered through the historical file (Alexander,
Bachmann, Boxer, Harkin, Hatch, Landrieu, McCain, McCaskill). Five of those
eight (Alexander, Boxer, Landrieu, McCain, McCaskill) are in the fixture
excerpt below, alongside Warner. See the module docstring in
[`legislators.py`](../../src/spicy_docs/sources/legislators.py) for the full
list and reasoning.

Fields this module reads but does not gate a refusal on — `id.icpsr`,
`id.govtrack`, `id.opensecrets`, `id.wikidata` — are read as optional. Real
records are missing each of them: `id.icpsr` is absent on 252 current-era and
many historical records, `id.opensecrets` on the large majority of historical
records (its tracking starts around 1989), and a freshly seated House member
(`G000607`, current file) has no `id.wikidata` yet. All three are real,
common absences, not malformed input.

## This is a civil-society source, not a publisher

There is no version, edition, release date or "as of" field anywhere in
either file. The pin for a capture is therefore what was actually read: the
exact bytes, their SHA-256, and the observed time — never a publisher-stated
release, because none exists.

**Cadence check.** The JSON itself carries no date, so the only signal for
"has this changed, and when" is the GitHub repository's own commit history:
<https://github.com/unitedstates/congress-legislators/commits/main>. Diff a
newly captured SHA-256 against the previously pinned one; if it differs, the
commit history is where to read *why* — a member left office, an id was
corrected, a new Congress was seated — not the JSON, which states none of
that.

**What a changed SHA-256 between runs means, and what it does not.** A
changed digest means the file was re-published since the last capture. It
does **not** by itself mean any one record changed: re-parse both captures
with `parse_legislators` and diff the resulting `LegislatorsFile.records` (or
the relevant `by_bioguide` entries) to find what actually moved. Conversely,
a matching SHA-256 means nothing observable changed between the two
captures; it does not prove the upstream data was ever correct — this module
proves shape, not truth.

## Use the route

Install the `acquisition` extra. No key, no env variable.

```python
from spicy_docs.sources.legislators import LegislatorsAcquirer, LegislatorsBudget

budget = LegislatorsBudget(max_requests=2, max_bytes=4 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1.0)
with LegislatorsAcquirer(budget=budget) as source:
    current = source.acquire_current()
    historical = source.acquire_historical()

warner = current.file.by_bioguide["W000805"]
print(warner.lis, warner.fec)  # S327 ('S6VA00093', 'P80003023')

graham = historical.file.by_lis["S293"]  # left office 2026-07-11; no longer in the current file
print(graham.bioguide, graham.terms[-1].end)
```

`acquire_current` additionally refuses a file whose `by_lis` is empty
(`LegislatorsSourceError`, "carries no id.lis entries"): roughly 100 sitting
senators always carry one, so a file with none is a bad file, not a fact
about Congress, and only this check would have caught it before a caller
found an empty crosswalk downstream.

Both routes are keyless, but GitHub Pages can still answer 401/403 (for
example when rate limited). There is no credential to reject, so that
refusal is recast as `LegislatorsRefusedError` — catchable as a
`LegislatorsSourceError` like every other refusal here — instead of escaping
as the shared client's `CredentialRefusedError`. The refusal body, when one
exists, is retained on `refused_response`.

`result.capture` carries the exact bytes, both URLs, status, observed time
and SHA-256 (`sha256:...`); retain `capture.body` as the pin. `result.file`
is a reading of those bytes, indexed by `by_bioguide`, `by_lis` and `by_fec`.

## Evidence

Reduced excerpts with per-record provenance:
[`tests/fixtures/legislators/README.md`](../../tests/fixtures/legislators/README.md).
Full-file bytes and digests are not retained in this repository; re-capture
live to re-measure. `tests/test_legislators.py` includes one
`@pytest.mark.integration` test that acquires both live files and asserts at
least the counts measured above.


## Change and check

Owner: [`legislators.py`](../../src/spicy_docs/sources/legislators.py).

```sh
uv run --frozen pytest -q tests/test_legislators.py
```

The `@pytest.mark.integration` test makes live requests and is excluded by
default (`-m 'not integration and not httpfs'`); run it explicitly with
`uv run --frozen pytest -q -m integration tests/test_legislators.py` before
trusting a re-pin.
