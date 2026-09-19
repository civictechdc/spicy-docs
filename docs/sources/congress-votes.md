# House Clerk and Senate LIS roll-call votes

Capture one roll-call vote's full tally and member-level roster from its
publisher of record: the House Clerk's EVS XML for House votes, the Senate's
LIS XML for Senate votes. Both are keyless. Neither Congress.gov route that
touches a vote -- `bill/{c}/{type}/{n}/actions`'s `recordedVotes` references
and `house-vote/{c}/{session}/{roll}/members` -- carries the tally or, for
the Senate, any member-level detail at all; see "Decision" below.

Congress.gov's `house-vote` route is a House-only index; it has no Senate
counterpart. `VoteAcquirer.list_senate_votes` reads the Senate's own session
index instead -- the LIS vote-menu file -- so a consumer that needs "every
roll call this session" for the Senate has a route at all. See "Senate vote
menu" below.

## What the files are

Two unrelated XML grammars, one per chamber, joined only by the identity
every recorded vote carries (congress, chamber, session, roll number):

| | House Clerk | Senate LIS |
| --- | --- | --- |
| Root element | `<rollcall-vote>` | `<roll_call_vote>` |
| DOCTYPE | External (`-//US Congress//DTDs/vote v1.0 20031119 //EN`), tolerated but not resolved | None |
| Member key | bioguide (`legislator/@name-id`) | LIS (`member/lis_member_id`) |
| Vote values seen | `Yea`, `Nay`, `Not Voting` (measured; `Aye`/`No`/`Present` are in the wider DTD vocabulary this module also accepts) | `Yea`, `Nay`, `Not Voting` (measured) |

Senate votes carry no bioguide id at all -- only `lis_member_id`. The only
LIS-to-bioguide crosswalk already in this package is
[`sources/legislators.py`](../../src/spicy_docs/sources/legislators.py)'s
`LegislatorsFile.by_lis`, so `parse_senate_vote` takes one as an optional
parameter instead of this module building a second crosswalk (the Senate's
own `cvc_member_data.xml` is a Table C candidate, not built here). A LIS id
the crosswalk does not carry resolves to `bioguide_id=None`, not a refusal:
`docs/research/legislative-data-map-2026-09-18.md` measured this as a real,
common absence -- roughly 4 of 99 voters on any one 119th-Congress vote,
almost always a member who has just left the seat the crosswalk's current
roster no longer lists.

## URL grammars

| Publisher | Grammar | Example |
| --- | --- | --- |
| House Clerk | `clerk.house.gov/evs/{year}/roll{roll_number:03d}.xml` | `https://clerk.house.gov/evs/2025/roll240.xml`, `https://clerk.house.gov/evs/2025/roll050.xml` |
| Senate LIS | `senate.gov/legislative/LIS/roll_call_votes/vote{congress:03d}{session}/vote_{congress:03d}_{session}_{roll_number:05d}.xml` | `https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00001.xml` |

The roll number is zero-padded to three digits (`roll050.xml`, `roll096.xml`
-- measured in `billtrax-raw-data-2026-09-19.json`'s real `recordedVotes`
urls, `evs/2025/roll050.xml` among them); a roll past 999 still prints in
full, since `:03d` is a minimum width, not a truncation.

The Senate's URL states congress, session and the roll number directly (both
in the folder and the filename; `locator_from_recorded_vote_url` refuses a
url where the two disagree). The Clerk's URL states only a calendar year and
the roll number -- no congress or session -- so `VoteLocator`'s Clerk URL
builder and its reverse parser both go through one fixed rule: session 1 of
Congress *N* convenes January 3 of the odd calendar year `1789 + 2*(N-1)`;
session 2 falls in the following (even) year. The 20th Amendment fixed this
from the 74th Congress (1935) onward, and the Clerk's EVS archive begins in
1990 (101st Congress, per the data map), well inside that range, so the rule
is exact everywhere this source reaches; `clerk_url`/`locator_from_recorded_vote_url`
refuse a congress before the 74th rather than guess at an irregular session.

The Senate congress is also zero-padded to three digits, matching
`SENATE_URL_RE`. Every real congress this route can serve already is three
digits: measured 2026-09-19, `senate.gov/.../vote_menu_101_1.xml` serves a
real 149,123-byte listing while `vote_menu_100_1.xml` and `vote_menu_099_1.xml`
each redirect to `roll-call-vote-not-available.htm`, so the Senate LIS
archive's floor is the 101st Congress -- the same floor the Clerk's EVS
archive measures. `senate_url`/`locator_from_recorded_vote_url` refuse a
congress below 101 rather than build or accept an unmeasured two-digit-congress
url.

`VoteLocator(chamber, congress, session, roll_number).url()` dispatches to
the right grammar; `locator_from_recorded_vote_url(url)` parses either one
back, for exactly the shape a Congress.gov `recordedVotes[].url` names
(`docs/research/billtrax-raw-data-2026-09-19.md` §5).

## Field tables

**House Clerk** (`parse_clerk_vote`) -- every `vote-metadata` field, both
totals blocks, and every `recorded-vote`:

| Field | Source element/attribute | Kept as |
| --- | --- | --- |
| `majority` | `vote-metadata/majority` | `RollCallVote.majority` |
| `congress`, `session` (shared identity) | `.../congress`, `.../session` (ordinal, e.g. `1st`) | `RollCallVote.congress` (int), `.session` (int, parsed from the ordinal) |
| `session_raw`, `chamber_raw` | `.../session`, `.../chamber` verbatim | kept beside the normalized `session`/`chamber` |
| `chamber` (shared identity) | `.../chamber` (`U.S. House of Representatives`) | normalized to `RollCallVote.chamber = "house"` |
| `rollcall-num` (shared identity) | `.../rollcall-num` | `RollCallVote.roll_number` |
| `legis-num` | `.../legis-num` | `RollCallVote.legis_num` |
| `vote-question` | `.../vote-question` | `RollCallVote.question` |
| `vote-type` | `.../vote-type` | `RollCallVote.vote_type` |
| `vote-result` | `.../vote-result` | `RollCallVote.result` |
| `action-date` | `.../action-date` | `RollCallVote.date` |
| `action-time` (text and `time-etz`) | `.../action-time` | `RollCallVote.action_time`, `.action_time_etz` |
| `vote-desc` | `.../vote-desc` | `RollCallVote.vote_desc` |
| Totals by party | `vote-totals/totals-by-party` (repeated) | `RollCallVote.party_totals: tuple[PartyTotal, ...]`, each `{party, counts}` with the publisher's own count names |
| Overall totals | `vote-totals/totals-by-vote` | `RollCallVote.tallies`, the publisher's own count names (`yea-total`, `nay-total`, `present-total`, `not-voting-total`) |
| `recorded-vote/legislator/@name-id` | bioguide | `MemberVote.bioguide_id` |
| `.../@sort-field`, `@unaccented-name`, `@role` | | `MemberVote.sort_field`, `.unaccented_name`, `.role` |
| `.../@party`, `@state` | | `MemberVote.party`, `.state` |
| legislator element text | display name | `MemberVote.name` |
| `recorded-vote/vote` | spelled vote | `MemberVote.vote` (raw), `.vote_normalized` (see below) |

**Senate LIS** (`parse_senate_vote`) -- every top-level field, `count`,
`tie_breaker`, `document`, `amendment`, and every `member`:

| Field | Source element | Kept as |
| --- | --- | --- |
| `congress`, `session`, `vote_number` (shared identity) | top-level | `RollCallVote.congress`, `.session`, `.roll_number` |
| `congress_year` | top-level | `RollCallVote.congress_year` |
| `vote_date` | top-level | `RollCallVote.date` |
| `modify_date` | top-level | `RollCallVote.modify_date` |
| `vote_question_text` | top-level | `RollCallVote.vote_question_text` |
| `vote_document_text` | top-level | `RollCallVote.vote_document_text` |
| `vote_result_text` | top-level | `RollCallVote.vote_result_text` |
| `question` | top-level | `RollCallVote.question` |
| `vote_title` | top-level | `RollCallVote.vote_title` |
| `majority_requirement` | top-level | `RollCallVote.majority_requirement` |
| `vote_result` | top-level | `RollCallVote.result` |
| `count/{yeas,nays,present,absent}` | | `RollCallVote.tallies`, the publisher's own count names; a blank count (`<present/>`) is `0` |
| `tie_breaker/{by_whom,tie_breaker_vote}` | | `RollCallVote.tie_breaker: TieBreaker`, both `None` when the vote was not tied |
| `document/document_congress`, `document_type`, `document_number`, `document_name`, `document_title`, `document_short_title` | | `RollCallVote.document: VoteDocument`, `None` when the file carries no `<document>` at all |
| `amendment/amendment_number`, `amendment_purpose`, `amendment_to_amendment_number`, `amendment_to_amendment_to_amendment_number`, `amendment_to_document_number`, `amendment_to_document_short_title` | | `RollCallVote.amendment: VoteAmendment`, every field `None` when the vote carried no amendment (the pinned fixture's own case) |
| `member/member_full`, `last_name`, `first_name` | | `MemberVote.member_full` (also mirrored onto the shared `.name`), `.last_name`, `.first_name` |
| `member/party`, `state` | | `MemberVote.party`, `.state` |
| `member/vote_cast` | spelled vote | `MemberVote.vote` (raw), `.vote_normalized` |
| `member/lis_member_id` | | `MemberVote.lis_id`, and `.bioguide_id` when a crosswalk resolves it |

`document`/`amendment` are kept verbatim as the publisher's own statement of
what the vote was on; matching either to a Congress.gov bill or nomination
record is `vote_matching`'s job (the data map's `senate-vote→document`
edge), not this reader's -- the Clerk's own bill linkage stays on
`legis_num`, unchanged.

`RollCallVote.chamber` is always the normalized `"house"`/`"senate"`; a
Clerk-only field is `None`/`()` on a Senate record and vice versa.

## Vote value normalization

`normalize_vote` maps every spelled value either chamber's DTD carries to one
of four buckets, case-insensitively: `Yea`/`Aye` → `yea`; `Nay`/`No` → `nay`;
`Present` → `present`; `Not Voting` → `not_voting`. `MemberVote.vote` keeps
the exact publisher spelling beside `.vote_normalized`. Both pinned fixtures
only ever spell `Yea`, `Nay` and `Not Voting`; `Aye`/`No`/`Present` are
accepted but unexercised by them (a plain RECORDED VOTE, rather than a
YEA-AND-NAY vote, is where the Clerk uses `Aye`/`No`).

## Identity rule

`parse_clerk_vote(body, locator)` and `parse_senate_vote(body, locator, crosswalk=None)`
both take the `VoteLocator` the caller requested the file for, and check the
file's own stated congress/session/roll number against it before returning
anything. A mismatch raises `VoteIdentityError` (a `VoteSourceError`), naming
both the requested locator and what the file actually stated. This proves
the fetched bytes are the vote requested, not only that the request URL was
built correctly -- the same shape as `press_releases.py`'s
`_check_feed_identity`, which proves a Senate RSS response is the requested
committee's feed rather than a byte-identical default channel.

## Senate vote menu

The Senate LIS also publishes a session-level index -- the vote menu --
which `VoteAcquirer.list_senate_votes(congress, session)` reads through
`parse_senate_vote_menu`. This closes gap A4
(`docs/research/closing-the-gaps-2026-09-19.md`): Congress.gov's `house-vote`
route is a House-only index, so before this the Senate had none at all. The
menu lists every roll call for one session in the publisher's own
newest-vote-first order (`SenateVoteMenu.votes[0]` is the most recent roll),
matching the order the gap names for the votes rollup: it "walks it newest
first with the same held-set skip" the House side already uses, so a rollup
can stop the walk as soon as it reaches a roll number it already has, rather
than re-reading a whole session on every run.

**URL grammar.** `senate.gov/legislative/LIS/roll_call_lists/vote_menu_{congress:03d}_{session}.xml`,
for example `https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_119_1.xml`.
Same three-digit congress and bare session number as `senate_url`, and the
same 101st-Congress floor (measured 2026-09-19: `vote_menu_101_1.xml` serves
a real 149,123-byte listing while `vote_menu_100_1.xml`/`vote_menu_099_1.xml`
each redirect to `roll-call-vote-not-available.htm`); `senate_vote_menu_url`
refuses a congress below 101 the same way `senate_url` does.

**Field table** (`parse_senate_vote_menu`) -- every field one `<vote>` row states:

| Field | Source element | Kept as |
| --- | --- | --- |
| `congress`, `session` (shared identity) | top-level `<vote_summary>` | checked against the requested congress/session, then `SenateVoteMenu.congress`, `.session` |
| `congress_year` | top-level | `SenateVoteMenu.congress_year` |
| `vote_number` | `vote/vote_number` | `SenateVoteMenuEntry.vote_number` (the roll number `locator_from_menu_entry` resolves) |
| `vote_date` | `vote/vote_date` | `SenateVoteMenuEntry.vote_date` (a bare day-month, e.g. `"18-Dec"`; the year lives on `congress_year`, not per vote) |
| `issue` | `vote/issue` | `SenateVoteMenuEntry.issue`; `None` on an `en_bloc` vote (see below) |
| `question`, its nested `measure` | `vote/question`, `vote/question/measure` | `SenateVoteMenuEntry.question`, `.question_measure` (`None` when the question carries no `<measure>`); both `None` on an `en_bloc` vote |
| `result` | `vote/result` | `SenateVoteMenuEntry.result`; `None` on an `en_bloc` vote |
| `vote_tally/{yeas,nays}` | `vote/vote_tally` | `SenateVoteMenuEntry.tallies`, the publisher's own count names (the menu states no `present`/`absent`, unlike the vote file itself) |
| `title` | `vote/title` | `SenateVoteMenuEntry.title` |
| `en_bloc/matter/{issue,question,result}` (repeated) | `vote/en_bloc/matter` | `SenateVoteMenuEntry.matters: tuple[SenateVoteMenuMatter, ...]`, each one item's own `issue`/`question`/`result` inside a batch confirmation vote (measured: 9 of 659 votes in the 119th Congress's 1st session are `en_bloc`) |

**Identity rule.** `parse_senate_vote_menu(body, *, congress, session)` checks
the file's own stated `<congress>`/`<session>` against the `congress`/
`session` it was called with before returning anything; a mismatch raises
`VoteMenuIdentityError` (a `VoteSourceError`), the same proof
`parse_clerk_vote`/`parse_senate_vote` make against a `VoteLocator`, one
level up (a session's worth of votes, not one vote's roll number). A
well-formed menu listing zero `<vote>` rows is also a refusal, not an empty
success -- the same rule `parse_clerk_vote`/`parse_senate_vote` apply to an
empty roster.

`locator_from_menu_entry(menu, entry)` builds the `VoteLocator` for one menu
row (always `"senate"`, since every row on the menu is a Senate vote by
construction), so a caller can walk the menu and then `VoteAcquirer.acquire`
each roll's full tally and roster without building the url by hand.

## Refusals

| Error | When |
| --- | --- |
| `VoteUnavailableError` | HTTP 404 or 410 |
| `VoteRefusedError` | HTTP 401/403 on either keyless host -- no credential exists to reject, so this is recast from `CredentialRefusedError` the way `LegislatorsRefusedError` and `PressReleaseFeedRefusedError` already are |
| `VoteIdentityError` | The fetched file's own congress/session/roll number does not match the locator |
| `VoteMenuIdentityError` | The fetched vote menu's own congress/session does not match what `list_senate_votes`/`parse_senate_vote_menu` was called with |
| `VoteSourceError` | Any other shape violation (wrong root element, a missing required field, an unrecognized vote value, a non-integer count, or a well-formed file with zero `recorded-vote`/`member`/`vote` rows -- empty success is not absence) |

Every refusal from `VoteAcquirer.acquire`/`.list_senate_votes` carries the
fetched bytes: `.capture` (when a body was received) and `.refused_response`
(bounded evidence, credential-safe by construction since neither host takes
one).

## Use the route

```python
from spicy_docs.sources.congress.votes import VoteAcquirer, VoteBudget, VoteLocator
from spicy_docs.sources.legislators import LegislatorsAcquirer, LegislatorsBudget

budget = VoteBudget(max_requests=2, max_bytes=512 * 1024, timeout_seconds=30, min_request_interval_seconds=1.0)

with VoteAcquirer(budget=budget) as source:
    house = source.acquire(VoteLocator("house", 119, 1, 240))

legislators_budget = LegislatorsBudget(
    max_requests=2, max_bytes=4 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1.0
)
with LegislatorsAcquirer(budget=legislators_budget) as legislators, VoteAcquirer(budget=budget) as source:
    crosswalk = legislators.acquire_current().file
    senate = source.acquire(VoteLocator("senate", 119, 1, 1), crosswalk=crosswalk)

print(house.vote.tallies)  # {'yea-total': 397, 'nay-total': 1, 'present-total': 0, 'not-voting-total': 32}
print(senate.vote.tallies)  # {'yeas': 84, 'nays': 9, 'present': 0, 'absent': 6}
```

A `recordedVotes[].url` from the Congress.gov bill-actions route resolves to
a locator without any network access:

```python
from spicy_docs.sources.congress.votes import locator_from_recorded_vote_url

locator = locator_from_recorded_vote_url("https://clerk.house.gov/evs/2025/roll240.xml")
```

Walking a session's Senate votes: read the menu once, then resolve each
row's full tally and roster from its own locator.

```python
from spicy_docs.sources.congress.votes import VoteAcquirer, VoteBudget, locator_from_menu_entry

menu_budget = VoteBudget(max_requests=2, max_bytes=2 * 1024**2, timeout_seconds=30, min_request_interval_seconds=1.0)
with VoteAcquirer(budget=menu_budget) as source:
    menu = source.list_senate_votes(119, 1).menu
    newest = source.acquire(locator_from_menu_entry(menu, menu.votes[0]))

print(menu.votes[0].vote_number, menu.votes[0].title)
print(newest.vote.tallies)
```

## Evidence

Real, unmodified vote-body fixtures with provenance, plus the Senate vote
menu's byte-exact head-and-tail excerpt (over the 200 KB fixture bound; the
full body's digest is recorded beside it):
[`tests/fixtures/congress_votes/README.md`](../../tests/fixtures/congress_votes/README.md).
`tests/test_congress_votes.py` includes three `@pytest.mark.integration`
tests, one per publisher route (House vote, Senate vote, Senate vote menu),
excluded by default (`-m 'not integration and not httpfs'`).

## Change and check

Owner: [`votes.py`](../../src/spicy_docs/sources/congress/votes.py).

```sh
uv run --frozen pytest -q tests/test_congress_votes.py
```

Run the live routes explicitly before trusting a re-pin:

```sh
uv run --frozen pytest -q -m integration tests/test_congress_votes.py
```

## Decision

**The Clerk and Senate LIS files are the tally source; the Congress.gov
house-vote route and `recordedVotes` references are the index.** Neither
Congress.gov route this package already reads carries a vote's actual tally.
`recordedVotes` is a reference -- six identity fields plus the url this
module resolves, nothing else (`billtrax-raw-data-2026-09-19.md` §5).
`house-vote/{c}/{session}/{roll}/members` does carry a member-level House
roster, but it only reaches the 115th Congress on and it is bioguide-keyed
for House votes only; it names the Clerk XML as its own `sourceDataURL`, and
the data map's comparison (`Congress.gov house-vote members vs Clerk roll
XML`) found the two agree on every member, every position and every total
for a sampled vote. The Senate has no member-level API route at all -- the
LIS file is the *only* source. Given that, one reading path for both
chambers, rather than a House-only shortcut through the API plus a
Senate-only file, is the plainer design and the only one that also fills
`RollCallVote.tallies`, which no Congress.gov route states for either
chamber. This is a proposal for the maintainer to move into
`docs/decisions.md`, not a decision recorded there yet.
