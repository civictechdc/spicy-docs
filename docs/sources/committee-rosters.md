# Capture committee rosters and today's assignments

Congress.gov's `committee` and `member` routes are the rosters of record for
identity and history. What they do not carry is who sits where *today*: that
lives in two chamber files, and this package reads all three. All routes are
keyless.

| Route | Answered 2026-09-19 | Credential |
| --- | --- | --- |
| `committee/{congress}` — the Congress.gov list route (identity, history via `committee/{chamber}/{code}`) | 236 rows served of 238 declared | api.data.gov |
| House Clerk [`MemberData.xml`](https://clerk.house.gov/xml/lists/MemberData.xml) — every seat, filled or vacant, with today's committee assignments | 556,936 bytes; 441 members, 2,516 assignments | none |
| Senate [`cvc_member_data.xml`](https://www.senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml) — the senators and their committee seats | 67,618 bytes; 100 senators, 450 committee entries | none |

## What each file states about itself, and what the readers demand

`spicy_docs.sources.congress.committee_rosters` refuses a file that cannot
say what it is:

- **The House file states its Congress and session** (`congress-num`, `session`
  in `title-info`, with the publish date and the Clerk's name). The reader
  takes the Congress the caller requested and checks the file's own statement
  against it before any member is read; a mismatch raises
  `CommitteeRosterIdentityError` naming both sides.
- **The Senate file states no Congress** — only a root element and a
  `<lastUpdate>` date. The reader proves what the file states (its root, its
  update date, that every senator carries both a LIS id and a bioguide, and
  that neither repeats), and an assignment row shaped from it carries the
  caller's Congress with `congress_basis = "caller"` so the weaker provenance
  is published, not hidden.
- **Zero members or senators refuses.** The House file lists every seat,
  filled or vacant; an empty roster is a bad file, not a fact about the House.
  A repeated LIS id or bioguide refuses too: the file promises one seat per
  senator, and a duplicate would give one person two rows under one key.
- **A vacancy is a seat without a member.** Two of the House file's 441
  members are vacancies: every `member-info` field empty and a single
  `<committee rank=""/>` placeholder (seven seated members carry the same
  placeholder as their only assignment — nine placeholders in all, counting
  the two vacancies). A placeholder is counted and skipped as "no
  assignment"; a vacancy that still lists a real assignment refuses as a
  malformed file.

## System codes are the join

Congress.gov keys committees on `systemCode`; the roster files retain their
own literal codes in `committee_code`. These are different namespaces.
For House rows, `HouseMemberData.system_code(code)` uses the names block's
literal committee `type`: standing committees derive `hs{code}`, while select
committees and their listed subcommittees derive `hl{code}`. Thus `II00`
becomes `hsii00`, while native select `IG00` and its child `IG01` become
`hlig00` and `hlig01`. Parent join codes use the same context. A name containing
“select” never changes the rule; the native type does.

The context-free `HouseAssignment.system_code` property and calls to
`house_system_code` without `committee_type` preserve the legacy standing-style
spelling. Use the roster-aware method for assignment rows. House joint codes
remain unresolved: the standing-style spelling is retained for compatibility,
not established as a Congress.gov identity. Do not repair these by committee
name; a publisher can list several distinct codes with the same name.

The Senate code is lowercased (`SPAG00` becomes `spag00`). A literal code can
still be absent from a caller-selected Congress's committee dimension; this
is a coverage or scope gap, not permission to change the source code. The
Senate roster states no Congress, so `congress_basis=caller` remains explicit.

## The LIS crosswalk stays where it was

The Senate file states each senator's LIS id beside the bioguide, and the
assignment rows publish it — but the crosswalk table remains
[the legislators JSON](legislators.md), which is still the only route to a
*former* senator's LIS id. Nothing here builds a second crosswalk; the
`lis_id` column is the file's own statement, one fact among the seat's fields.

## Capture both files

From the checkout, install acquisition dependencies with
`uv sync --frozen --extra acquisition`. Each output directory must be new.

```sh
uv run --frozen python - <<'PY'
from spicy_docs.sources.congress.committee_rosters import (
    CommitteeRosterAcquirer, CommitteeRosterBudget,
)

budget = CommitteeRosterBudget(max_requests=2, max_bytes=4 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1)
with CommitteeRosterAcquirer(budget=budget) as source:
    house = source.acquire_house(congress=119, session=2)
    senate = source.acquire_senate()
print(len(house.roster.members), len(senate.roster.senators))
PY
```

A 401/403 from either host becomes `CommitteeRosterRefusedError` — there is
no credential here to reject — and an unavailable answer is retained with its
bytes. The `committees` rows come from the Congress.gov list route through
[the listings reader](listings.md), with the detail record folded onto the
same row where one was captured; `committee_assignments` is one row per
member per seat from the two chamber files. Both contracts are in
`schemas/roster_tables.py`; see [Tables](../tables.md). The 2026-09-19
captures, the parse checks and the 555-vs-541 member comparison against the
API (all 14 API-only members with ended terms) are in
`corpora/supply-2026-09-02/receipts/roster-comparison-2026-09-19/`.
